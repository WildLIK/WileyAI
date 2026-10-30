"""Own SIWC registration, never ChatGPT backend-api or another application's token cache."""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from urllib.parse import urlencode, urlsplit

import httpx

from core.chatgpt import ChatGPT, ChatGPTError, AUTHORIZE, TOKEN, RESOURCE, SCOPES
from ..protocol import Capability, GatewayError, Model, OAuthAdapter, ProviderEvent
from ..store import new_id
from .compatible import upstream_error
from ..sse import bounded_lines


class VaultSession(ChatGPT):
    def __init__(self, store, owner, connection_id, client=None):
        self.store, self.owner, self.record_id = store, owner, "credential-" + connection_id
        super().__init__(store.root / "oauth-locks" / owner / connection_id, client)

    def read(self):
        try:
            return self.store.get(self.owner, self.record_id, "credential")
        except GatewayError as error:
            if error.status == 404:
                return {}
            raise

    def write(self, value):
        self.store.put(self.owner, self.record_id, "credential", value)

    def login_result(self, error=None, stage=""):
        # No provider URLs, exception repr, cookies, identity claims or tokens in logs.
        self.error = "Не удалось завершить вход ChatGPT." if error else ""
        self.diagnostic = {"code": "authorization_failed", "stage": stage} if error else {}


class ChatGPTAdapter(OAuthAdapter):
    def __init__(self, store, client=None, transport=None):
        self.store, self.http, self.transport = store, client, transport
        self.owns_client = client is None
        if client is None:
            self.http = httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False, transport=transport)
        self.sessions = {}

    def session(self, account):
        key = account["owner"], account["id"]
        if key not in self.sessions:
            self.sessions[key] = VaultSession(self.store, *key, client=self.http)
        return self.sessions[key]

    async def status(self, account):
        value = self.session(account).read()
        if not value.get("access_token"):
            return {"status": "authorization_required"}
        if "chatgpt.tokens.use.direct" not in value.get("scopes", []):
            return {"status": "plan_permission_required"}
        if value.get("expires_at", 0) <= time.time() and not value.get("refresh_token"):
            return {"status": "session_expired"}
        return {"status": "connected", "account": value.get("email", "")}

    async def start_auth(self, account, redirect):
        parsed = urlsplit(redirect)
        try:
            valid = parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.username is None and 1024 <= (parsed.port or 0) <= 65535 and parsed.path == "/auth/callback" and not parsed.query and not parsed.fragment
        except ValueError:
            valid = False
        if not valid:
            raise GatewayError("invalid_callback", "Вход требует локального callback 127.0.0.1 приложения.")
        session = self.session(account)
        async with session.guard():
            value = session.read()
            if not value.get("host_id"):
                value["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                session.write(value)
            for identifier, flow in self.store.list(account["owner"], "auth_flow"):
                if flow.get("connection_id") == account["id"] or flow.get("expires_at", 0) < time.time():
                    self.store.delete(account["owner"], identifier)
            import secrets
            verifier, state, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            client_id = value.get("client_id") or value.get("pending_client_id")
            identifier = new_id()
            flow = {"connection_id": account["id"], "redirect": redirect, "verifier": verifier, "state": state, "nonce": nonce,
                    "client_id": client_id, "subject": value.get("subject") if client_id else None, "expires_at": time.time() + 300}
            self.store.put(account["owner"], identifier, "auth_flow", flow)
            params = {"client_id": client_id or "dynamic_agent_client", "ext_agent_host_id": value["host_id"], "response_type": "code",
                      "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
                      "code_challenge_method": "S256", "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
            if client_id:
                params["prompt"] = "consent"
            else:
                params["agent_name_hint"] = "WileyAI Gateway"
            return {"flow_id": identifier, "url": AUTHORIZE + "?" + urlencode(params), "state": state, "expires_at": flow["expires_at"], "method": "loopback_pkce"}

    async def complete_auth(self, account, body):
        session = self.session(account)
        async with session.guard():
            flow = self.store.get(account["owner"], body.flow_id, "auth_flow")
            if flow["connection_id"] != account["id"] or not hmac.compare_digest(body.state, flow["state"]):
                raise GatewayError("invalid_state", "Вход не соответствует исходному запросу.", 403)
            self.store.delete(account["owner"], body.flow_id)
            if flow["expires_at"] < time.time():
                raise GatewayError("session_expired", "Время входа истекло. Начните вход заново.", 410)
            if body.error:
                raise GatewayError("access_denied", "Вход отменён или разрешение не выдано.", 403)
            issued = body.client_id or flow.get("client_id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,250}", issued) or issued == "dynamic_agent_client" or (flow.get("client_id") and issued != flow["client_id"]) or not body.code:
                raise GatewayError("authorization_failed", "ChatGPT не завершил регистрацию приложения.", 400)
            try:
                old = session.read()
                if not old.get("client_id"):
                    session.write({**old, "pending_client_id": issued})
                data = await session.request("POST", TOKEN, data={"grant_type": "authorization_code", "client_id": issued,
                                             "code": body.code, "code_verifier": flow["verifier"], "redirect_uri": flow["redirect"], "resource": RESOURCE})
                claims = await session.validate_identity(data.get("id_token", ""), issued, flow["nonce"], flow.get("subject"))
                value = session.credentials(data, {"host_id": old["host_id"], "client_id": issued, "subject": claims["sub"],
                                                  "email": str(claims.get("email", ""))[:320], "id_token": data["id_token"]})
                session.write(value)
            except ChatGPTError:
                raise GatewayError("authorization_failed", "Не удалось подтвердить вход ChatGPT. Начните вход заново.", 401) from None
        return await self.status(account)

    async def models(self, account):
        session = self.session(account)
        try:
            token = await session.token()
            data = await session.request("GET", RESOURCE + "/models", headers={"Authorization": "Bearer " + token})
            models = []
            entries = data.get("models", [])
            if not isinstance(entries, list):
                raise GatewayError("provider_changed", "Изменился формат каталога ChatGPT.", 502)
            for item in entries[:500]:
                if not isinstance(item, dict) or item.get("visibility") != "list" or not isinstance(item.get("slug"), str) or not 0 < len(item["slug"]) <= 200:
                    continue
                features = {feature: Capability(state="advertised", evidence="siwc_public_protocol", observed_at=time.time()) for feature in ("text", "streaming")}
                # Eligibility of the selected model is learned from explicit metadata, never its name.
                modalities = item.get("input_modalities", [])
                modalities = modalities if isinstance(modalities, list) else []
                if "image" in modalities:
                    features["vision"] = Capability(state="advertised", evidence="account_model_metadata", observed_at=time.time())
                if "file" in modalities:
                    features["file_upload"] = Capability(state="advertised", evidence="account_model_metadata", observed_at=time.time())
                for feature in ("image_generation", "image_editing", "audio_generation", "speech_recognition", "video_input", "video_generation", "mcp"):
                    features[feature] = Capability(state="unavailable", evidence="siwc_preview_limits", observed_at=time.time())
                modes = item.get("supported_reasoning_efforts", [])
                modes = [mode for mode in modes if isinstance(mode, str) and len(mode) < 40] if isinstance(modes, list) else []
                if modes:
                    features["reasoning_summary"] = Capability(state="advertised", evidence="account_model_metadata", observed_at=time.time())
                if item.get("supports_web_search") is True:
                    features["web_search"] = Capability(state="advertised", evidence="account_model_metadata", observed_at=time.time())
                models.append(Model(id=item["slug"], name=str(item.get("display_name", item["slug"]))[:200], capabilities=features, reasoning_modes=modes))
            return models
        except ChatGPTError as error:
            raise upstream_error(error.status or 401) from None

    async def stream(self, account, model, messages, options):
        session = self.session(account)
        completed = False
        try:
            token = await session.token()
            body = {"model": model.id, "store": False, "stream": True, "input": []}
            for message in messages:
                body["input"].append({"role": "developer" if message["role"] == "system" else message["role"], "content": message["content"]})
            if options.get("reasoning_mode"):
                body["reasoning"] = {"effort": options["reasoning_mode"], "summary": "auto"}
            if options.get("web_search"):
                body["tools"] = [{"type": "web_search"}]
            async with asyncio.timeout(600):
                async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), trust_env=False, follow_redirects=False,
                                             transport=self.transport) as client:
                    async with client.stream("POST", RESOURCE + "/responses", headers={"Authorization": "Bearer " + token}, json=body) as response:
                        if response.status_code != 200:
                            raise upstream_error(response.status_code)
                        async for line in bounded_lines(response):
                            if len(line) > 256 * 1024:
                                raise GatewayError("provider_changed", "Событие ChatGPT слишком большое.", 502)
                            if not line.startswith("data:"):
                                continue
                            event = json.loads(line[5:].strip())
                            kind = event.get("type")
                            if kind == "response.output_text.delta":
                                yield ProviderEvent("message.delta", {"text": event.get("delta", "")})
                            elif kind == "response.reasoning_summary_text.delta":
                                yield ProviderEvent("reasoning.summary", {"text": event.get("delta", "")})
                            elif kind == "response.output_text.annotation.added":
                                annotation = event.get("annotation", {})
                                if annotation.get("type") == "url_citation":
                                    yield ProviderEvent("citation.added", {"url": annotation.get("url", ""), "title": str(annotation.get("title", ""))[:300]})
                            elif kind == "response.completed":
                                completed = True
                            elif kind in {"response.failed", "response.incomplete", "error"}:
                                code = event.get("response", {}).get("error", {}).get("code", "")
                                raise GatewayError("quota_exceeded" if code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"} else "stream_interrupted", "ChatGPT не завершил ответ. Частичный текст сохранён.", 502)
                            elif kind == "response.output_item.done" and event.get("item", {}).get("type") in {"function_call", "custom_tool_call"}:
                                raise GatewayError("capability_unavailable", "Инструменты этого подключения пока не разрешены. Действие не выполнялось.", 422)
            if not completed:
                raise GatewayError("stream_interrupted", "Поток ChatGPT прервался до подтверждения завершения.", 502, True)
        except ChatGPTError as error:
            raise upstream_error(error.status or 401) from None
        except (httpx.HTTPError, TimeoutError):
            raise GatewayError("upstream_timeout", "Соединение с ChatGPT прервалось. Частичный ответ сохранён.", 502, True) from None
        except (ValueError, TypeError, AttributeError):
            raise GatewayError("provider_changed", "Изменился формат ответа ChatGPT.", 502) from None

    async def disconnect(self, account):
        result = await self.session(account).logout()
        self.store.delete(account["owner"], "credential-" + account["id"])
        return {"revoked_upstream": not result.get("error")}

    async def close(self):
        for session in self.sessions.values():
            await session.close()
        if self.owns_client:
            await self.http.aclose()
