"""User-authorized ChatGPT plan access, isolated from API-key providers.

OAuth PKCE uses the system browser and a one-use loopback listener. Tokens live
only in the OS credential store; profile files contain an opaque connection ID.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
from html import escape
import json
import re
import secrets
import socket
import sqlite3
import ssl
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import keyring

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
SERVICE = "WileyAI.ChatGPT"
# Windows CredWrite limits CredentialBlob to 2560 BYTES. python-keyring
# writes UTF-16, so an ASCII JSON chunk of 1800 characters occupied 3600
# bytes and failed with WinError 1783. Leave room below 1280 code units.
CREDENTIAL_CHUNK_CHARS = 1000
MAX_CREDENTIAL_PARTS = 128
_connections = {}


class ChatGPTError(ValueError):
    def __init__(self, message, *, status=0, code="", request_id="", format_unsupported=False, stage=""):
        self.status, self.code, self.request_id = status, code, request_id
        self.format_unsupported = format_unsupported
        self.stage = stage
        super().__init__(message)


STAGES = {"callback": "возврат из браузера", "token": "получение сессии", "discovery": "проверка сервера входа",
          "jwks": "загрузка ключей подписи", "identity": "проверка аккаунта", "storage": "сохранение подключения"}


def network_failure(error, stage=""):
    """Only predefined diagnostics; HTTP exceptions may contain sensitive URLs."""
    chain, current = [], error
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__
    if any(isinstance(e, ssl.SSLError) for e in chain):
        message, code = "Не удалось установить защищённое соединение с ChatGPT. Проверьте дату Windows и сертификаты HTTPS в VPN или антивирусе.", "network_tls"
    elif any(isinstance(e, socket.gaierror) for e in chain):
        message, code = "Не удалось определить адрес сервера ChatGPT. Проверьте DNS и подключение VPN.", "network_dns"
    elif isinstance(error, httpx.ProxyError):
        message, code = "Не удалось соединиться с ChatGPT через настроенный прокси. Проверьте его подключение.", "network_proxy"
    elif isinstance(error, httpx.TimeoutException):
        message, code = "Сервер ChatGPT не ответил вовремя. Проверьте соединение и повторите вход.", "network_timeout"
    elif isinstance(error, httpx.ConnectError):
        message, code = "WileyAI не смог установить соединение с сервером ChatGPT. Проверьте, что VPN или прокси работает для приложения, и повторите вход.", "network_connect"
    else:
        message, code = "Соединение с ChatGPT прервалось во время передачи данных. Повторите вход из WileyAI.", "network_transfer"
    if stage:
        message += " Этап: " + STAGES.get(stage, "запрос к ChatGPT") + "."
    return ChatGPTError(message, code=code, stage=stage)


def failure(status, body, request_id=""):
    detail = body.get("error", {}) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        detail = {}
    code = str(detail.get("code", ""))[:100]
    message = str(detail.get("message", "")).casefold()
    text = ("Лимит ChatGPT для этого приложения исчерпан. Проверьте лимиты в ChatGPT → Настройки → Использование." if code == "subscription_sharing_usage_limit_exceeded" or status == 429 else
            "Использование плана ChatGPT недоступно. Проверьте разрешение приложению и состояние подписки." if code in {"subscription_sharing_usage_unavailable", "chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context"} else
            "Сессия ChatGPT отклонена. Войдите в аккаунт заново." if status == 401 else
            "ChatGPT не разрешил запрос. Проверьте доступность модели, разрешения аккаунта и регион." if status == 403 else
            "Выбранная модель ChatGPT недоступна. Обновите список моделей." if status == 404 else
            "ChatGPT временно недоступен. Повторите позже; подключение сохранено." if status >= 500 else
            "ChatGPT отклонил запрос. Обновите список моделей или повторите позже.")
    return ChatGPTError(text, status=status, code=code, request_id=request_id[:150],
                        format_unsupported=status in {400, 422} and any(s in message for s in ("text.format", "json_schema", "structured output")))


def connection(identifier):
    value = _connections.get(identifier)
    if value is None:
        raise ChatGPTError("Подключите аккаунт ChatGPT в настройках модели.")
    return value


class ChatGPT:
    def __init__(self, root, client=None):
        self.root = root.resolve()
        self.identifier = hashlib.sha256(str(self.root).casefold().encode()).hexdigest()
        self.client = client
        self.lock = asyncio.Lock()
        self.pending = None
        self.server = None
        self.timer = None
        self.callbacks = set()
        self.error = ""
        self.diagnostic = {}
        # Retain only non-secret failure details across app restarts.
        try:
            path = self.root / "logs/chatgpt-login.json"
            if path.stat().st_size <= 8192:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(previous, dict) and isinstance(previous.get("error"), str):
                    self.error = previous["error"][:2000]
                    self.diagnostic = {k: previous[k] for k in ("stage", "code", "http_status", "request_id") if k in previous}
        except (OSError, ValueError):
            pass
        self.jwks = None
        self.jwks_at = 0
        _connections[self.identifier] = self

    def login_result(self, error=None, stage=""):
        self.error = str(error) if error else ""
        self.diagnostic = ({"stage": error.stage or stage, "code": error.code[:100],
                            "http_status": error.status, "request_id": error.request_id[:150]} if error else {})
        path = self.root / "logs/chatgpt-login.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".part")
            temporary.write_text(json.dumps({"error": self.error, **self.diagnostic}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass  # Logging cannot prevent sign-in or a successful credential commit.

    def read(self):
        try:
            pointer = keyring.get_password(SERVICE, self.identifier)
            if not pointer:
                return {}
            manifest = json.loads(pointer)
            parts = manifest["parts"]
            if not isinstance(parts, int) or isinstance(parts, bool) or not 1 <= parts <= MAX_CREDENTIAL_PARTS or not re.fullmatch(r"[a-f0-9]{32}", manifest["revision"]):
                raise ValueError()
            chunks = [keyring.get_password(SERVICE, f'{self.identifier}:{manifest["revision"]}:{i}') for i in range(parts)]
            if any(c is None for c in chunks):
                raise ValueError()
            value = json.loads("".join(chunks))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except Exception as error:
            raise ChatGPTError("Не удалось прочитать подключение ChatGPT из системного хранилища.") from error

    def write(self, value):
        # Windows credentials have a small blob limit. Commit a new chunked
        # generation before deleting the old one, so refresh rotation is atomic.
        revision = uuid.uuid4().hex
        payload = json.dumps(value, ensure_ascii=True)
        chunks = [payload[i:i + CREDENTIAL_CHUNK_CHARS] for i in range(0, len(payload), CREDENTIAL_CHUNK_CHARS)]
        if len(chunks) > MAX_CREDENTIAL_PARTS:
            raise ChatGPTError("Сессия ChatGPT превышает размер защищённого хранилища.")
        old = None
        written = []
        try:
            old = keyring.get_password(SERVICE, self.identifier)
            for i, chunk in enumerate(chunks):
                name = f"{self.identifier}:{revision}:{i}"
                keyring.set_password(SERVICE, name, chunk)
                written.append(name)
            keyring.set_password(SERVICE, self.identifier, json.dumps({"revision": revision, "parts": len(chunks)}))
        except Exception as error:
            for name in written:
                try:
                    keyring.delete_password(SERVICE, name)
                except Exception:
                    pass
            winerror = getattr(error, "winerror", None)
            code = f"windows_credential_{winerror}" if isinstance(winerror, int) else "credential_write_failed"
            raise ChatGPTError("Не удалось сохранить сессию ChatGPT в системном хранилище.", code=code, stage="storage") from error
        if old:
            try:
                previous = json.loads(old)
                for i in range(min(previous["parts"], MAX_CREDENTIAL_PARTS)):
                    keyring.delete_password(SERVICE, f'{self.identifier}:{previous["revision"]}:{i}')
            except Exception:
                pass  # The committed new generation remains usable.

    @asynccontextmanager
    async def guard(self):
        async with self.lock:
            # A separate SQLite file is only a cross-process mutex. It contains
            # no credentials and never locks the user's conversation database.
            self.root.mkdir(parents=True, exist_ok=True)
            def acquire():
                db = sqlite3.connect(self.root / "chatgpt-session.lock", timeout=35, check_same_thread=False)
                try:
                    db.execute("BEGIN IMMEDIATE")
                    return db
                except BaseException:
                    db.close()
                    raise
            work = asyncio.create_task(asyncio.to_thread(acquire))
            try:
                db = await asyncio.shield(work)
            except asyncio.CancelledError:
                db = await work
                db.close()
                raise
            try:
                yield
            finally:
                db.close()

    async def _request_once(self, method, url, **kwargs):
        @asynccontextmanager
        async def transport():
            if self.client is not None:
                yield self.client
            else:
                # Honor the user's configured system/environment proxy, with
                # normal certificate verification and no redirects of tokens.
                async with httpx.AsyncClient(timeout=25, trust_env=True, follow_redirects=False) as client:
                    yield client
        try:
            async with transport() as client:
                async with client.stream(method, url, **kwargs) as response:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise ChatGPTError("ChatGPT вернул слишком большой ответ.")
                    try:
                        result = json.loads(data) if data else {}
                    except (ValueError, UnicodeDecodeError):
                        result = {}
                    if response.status_code not in {200, 201, 204}:
                        if url == TOKEN:
                            code = result.get("error", "") if isinstance(result, dict) else ""
                            if isinstance(code, dict):
                                code = code.get("code", "")
                            if response.status_code >= 500:
                                raise ChatGPTError("Сервис входа ChatGPT временно недоступен. Повторите позже; подключение сохранено.", status=response.status_code, code=str(code)[:100])
                            raise ChatGPTError("Не удалось обновить вход ChatGPT. Повторите вход в браузере.", status=response.status_code, code=str(code)[:100])
                        raise failure(response.status_code, result, response.headers.get("x-request-id", ""))
                    if not isinstance(result, dict):
                        raise ChatGPTError("ChatGPT вернул некорректный ответ.")
                    return result
        except httpx.HTTPError:
            raise

    async def request(self, method, url, **kwargs):
        stage = "token" if url == TOKEN else "discovery" if url == DISCOVERY else "jwks" if url == ISSUER + "/.well-known/jwks.json" else ""
        for attempt in range(3):
            try:
                return await self._request_once(method, url, **kwargs)
            except ChatGPTError as error:
                error.stage = error.stage or stage
                raise
            except httpx.HTTPError as error:
                # A connect failure precedes sending the OAuth request. GET
                # reads may also be repeated. Never replay a possibly consumed
                # authorization code or rotating refresh token after a read error.
                retry = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)) or (
                    method == "GET" and isinstance(error, (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError)))
                if not retry or attempt == 2:
                    raise network_failure(error, stage) from error
                await asyncio.sleep(0.4 * (attempt + 1))

    def status(self):
        value = self.read()
        return {"connection_id": self.identifier, "connected": bool(value.get("access_token")),
                "plan_enabled": "chatgpt.tokens.use.direct" in value.get("scopes", []),
                "email": value.get("email", "") if value.get("access_token") else "",
                "pending": self.pending is not None, "error": self.error, "diagnostic": dict(self.diagnostic),
                "registration_pending": bool(value.get("pending_client_id") and not value.get("access_token"))}

    def stop_pending(self):
        self.pending = None
        if self.server:
            self.server.close()
            self.server = None
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = None

    async def start(self, new_account=False):
        async with self.guard():
            self.stop_pending()
            value = self.read()
            if not value.get("host_id"):
                value["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self.write(value)
            verifier, state, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            client_id = (value.get("client_id") or value.get("pending_client_id")) if not new_account else None
            self.server = await asyncio.start_server(self.callback, "127.0.0.1", 0, limit=16384)
            port = self.server.sockets[0].getsockname()[1]
            redirect = f"http://127.0.0.1:{port}/auth/callback"
            self.pending = {"verifier": verifier, "state": state, "nonce": nonce, "client_id": client_id,
                            "subject": value.get("subject") if client_id else None, "redirect": redirect}
            params = {"client_id": client_id or "dynamic_agent_client", "ext_agent_host_id": value["host_id"],
                      "response_type": "code", "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE,
                      "state": state, "nonce": nonce, "code_challenge_method": "S256",
                      "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
            if client_id:
                # Keep retained ID tokens in the credential store. The normal
                # account selector is preferable to passing a token in a URL.
                if value.get("email"):
                    params["login_hint"] = value["email"]
                if "chatgpt.tokens.use.direct" not in value.get("scopes", []):
                    params["prompt"] = "consent"
            else:
                params["agent_name_hint"] = "WileyAI"
            self.login_result()
            pending = self.pending
            async def expire():
                await asyncio.sleep(300)
                if self.pending is pending:
                    self.login_result(ChatGPTError("Время входа ChatGPT истекло. Начните вход заново."), "callback")
                    self.stop_pending()
            self.timer = asyncio.create_task(expire())
            return {"url": AUTHORIZE + "?" + urlencode(params)}

    async def validate_identity(self, token, client_id, nonce=None, subject=None):
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 32000:
                raise ValueError()
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"RS256", "ES256"} or not isinstance(header.get("kid"), str):
                raise ValueError()
            for attempt in range(2):
                if self.jwks is None or time.time() - self.jwks_at > 3600 or attempt:
                    metadata = await self.request("GET", DISCOVERY)
                    if metadata.get("issuer") != ISSUER or metadata.get("jwks_uri") != ISSUER + "/.well-known/jwks.json":
                        raise ValueError()
                    self.jwks = await self.request("GET", metadata["jwks_uri"])
                    self.jwks_at = time.time()
                keys = self.jwks.get("keys", [])
                if not isinstance(keys, list) or len(keys) > 100:
                    raise ValueError()
                matches = [k for k in keys if isinstance(k, dict) and k.get("kid") == header["kid"] and k.get("use", "sig") == "sig"]
                if len(matches) == 1:
                    break
            if len(matches) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(matches[0], algorithm=header["alg"])
            claims = jwt.decode(token, key.key, algorithms=[header["alg"]], audience=client_id, issuer=ISSUER,
                                options={"require": ["iss", "aud", "exp", "iat", "sub"]}, leeway=30)
            if not isinstance(claims["sub"], str) or not claims["sub"] or (subject and claims["sub"] != subject):
                raise ValueError()
            if nonce is not None and (not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce)):
                raise ValueError()
            if claims.get("azp", client_id) != client_id or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id):
                raise ValueError()
            return claims
        except ChatGPTError:
            raise
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as error:
            raise ChatGPTError("Не удалось подтвердить личность аккаунта ChatGPT. Вход не сохранён.") from error

    def credentials(self, data, previous):
        access = data.get("access_token")
        lifetime = data.get("expires_in")
        refresh = data.get("refresh_token", previous.get("refresh_token", ""))
        if not isinstance(access, str) or not 1 <= len(access) <= 32000 or data.get("token_type", "").lower() != "bearer":
            raise ChatGPTError("ChatGPT не вернул действительную сессию.")
        if isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or not 0 < lifetime <= 365 * 86400:
            raise ChatGPTError("ChatGPT не указал срок действия сессии.")
        if not isinstance(refresh, str) or len(refresh) > 32000:
            raise ChatGPTError("ChatGPT вернул некорректную сессию.")
        scope = data.get("scope")
        if scope is not None and not isinstance(scope, str):
            raise ChatGPTError("ChatGPT вернул некорректные разрешения.")
        return {**previous, "access_token": access, "refresh_token": refresh,
                "expires_at": time.time() + lifetime, "scopes": scope.split() if scope is not None else previous.get("scopes", [])}

    async def callback(self, reader, writer):
        task = asyncio.current_task()
        self.callbacks.add(task)
        code, text = 400, "Не удалось завершить вход. Вернитесь в WileyAI."
        stage = "callback"
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(raw) > 16384:
                raise ValueError()
            lines = raw.decode("ascii").split("\r\n")
            method, target, protocol = lines[0].split(" ")
            query = urlsplit(target)
            params = parse_qs(query.query, keep_blank_values=True, max_num_fields=15)
            async with self.guard():
                pending = self.pending
                hosts = [line.split(":", 1)[1].strip().lower() for line in lines[1:] if line.lower().startswith("host:")]
                expected_host = urlsplit(pending["redirect"]).netloc if pending else ""
                if method != "GET" or protocol not in {"HTTP/1.0", "HTTP/1.1"} or query.path != "/auth/callback" or query.scheme or query.netloc or hosts != [expected_host]:
                    code = 404
                elif not pending or len(params.get("state", [])) != 1 or not hmac.compare_digest(params["state"][0], pending["state"]):
                    text = "Вход не подтверждён. Продолжите исходный вход из WileyAI."
                else:
                    self.stop_pending()  # Consume valid state exactly once, before exchange.
                    if params.get("error"):
                        raise ChatGPTError("Вход ChatGPT отменён или доступ приложению не разрешён.")
                    issued = params.get("client_id", [pending["client_id"]])
                    auth_code = params.get("code", [])
                    if len(issued) != 1 or not isinstance(issued[0], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,250}", issued[0]) or issued[0] == "dynamic_agent_client":
                        raise ChatGPTError("ChatGPT не завершил регистрацию приложения. Начните вход заново.")
                    if pending["client_id"] and issued[0] != pending["client_id"]:
                        raise ChatGPTError("ChatGPT вернул другое подключение. Повторите вход.")
                    if len(auth_code) != 1 or not 1 <= len(auth_code[0]) <= 8192:
                        raise ChatGPTError("ChatGPT не вернул код входа. Начните вход заново.")
                    if not pending["client_id"]:
                        # Registration exists on ChatGPT before token exchange.
                        # Retain its ID for retry, without activating an account
                        # or replacing any previously verified connection.
                        old = self.read()
                        if not old.get("client_id"):
                            self.write({**old, "pending_client_id": issued[0]})
                    data = await self.request("POST", TOKEN, data={"grant_type": "authorization_code", "client_id": issued[0],
                                              "code": auth_code[0], "code_verifier": pending["verifier"],
                                              "redirect_uri": pending["redirect"], "resource": RESOURCE})
                    stage = "identity"
                    claims = await self.validate_identity(data.get("id_token", ""), issued[0], pending["nonce"], pending["subject"])
                    old = self.read()
                    value = self.credentials(data, {"host_id": old["host_id"], "client_id": issued[0], "subject": claims["sub"],
                                                   "email": str(claims.get("email", ""))[:320], "id_token": data["id_token"]})
                    stage = "storage"
                    self.write(value)
                    self.login_result(None if "chatgpt.tokens.use.direct" in value["scopes"] else ChatGPTError("Аккаунт подключён, но использование плана не разрешено. Войдите снова и разрешите использование подписки."), stage)
                    code, text = 200, "Вход в ChatGPT завершён. Можно закрыть эту вкладку и вернуться в WileyAI."
        except ChatGPTError as error:
            self.login_result(error, stage)
            text = self.error + " Вернитесь в настройки WileyAI и повторите вход."
        except (ValueError, UnicodeDecodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            pass
        except Exception:
            self.login_result(ChatGPTError("Не удалось завершить вход ChatGPT. Повторите вход из настроек."), stage)
            text = self.error
        finally:
            body = ("<!doctype html><html lang=ru><meta charset=utf-8><title>WileyAI — ChatGPT</title>"
                    "<meta name=referrer content=no-referrer><p>" + escape(text) + "</p></html>").encode()
            try:
                writer.write(f"HTTP/1.1 {code} Result\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                await writer.drain()
            except (OSError, ConnectionError):
                pass
            writer.close()
            self.callbacks.discard(task)

    async def token(self):
        async with self.guard():
            value = self.read()
            if not value.get("access_token"):
                raise ChatGPTError("Войдите в ChatGPT в настройках модели.")
            if "chatgpt.tokens.use.direct" not in value.get("scopes", []):
                raise ChatGPTError("Разрешите WileyAI использовать план ChatGPT при входе в аккаунт.")
            if value.get("expires_at", 0) <= time.time() + 60:
                if not value.get("refresh_token"):
                    raise ChatGPTError("Сессия ChatGPT истекла. Войдите заново.")
                try:
                    data = await self.request("POST", TOKEN, data={"grant_type": "refresh_token", "client_id": value["client_id"],
                                               "refresh_token": value["refresh_token"], "resource": RESOURCE})
                except ChatGPTError as error:
                    if error.code in {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}:
                        self.write({k: v for k, v in value.items() if k not in {"access_token", "refresh_token", "id_token", "expires_at", "scopes"}})
                    raise
                updated = self.credentials(data, value)
                if data.get("id_token"):
                    claims = await self.validate_identity(data["id_token"], value["client_id"], subject=value["subject"])
                    updated.update(id_token=data["id_token"], email=str(claims.get("email", value.get("email", "")))[:320])
                self.write(updated)
                value = updated
            if "chatgpt.tokens.use.direct" not in value.get("scopes", []):
                raise ChatGPTError("Разрешение использовать план ChatGPT отозвано. Войдите заново.")
            return value["access_token"]

    async def models(self):
        token = await self.token()
        value = await self.request("GET", RESOURCE + "/models", headers={"Authorization": "Bearer " + token})
        models = value.get("models", [])
        if not isinstance(models, list):
            raise ChatGPTError("ChatGPT вернул некорректный список моделей.")
        return [{"id": m["slug"], "name": str(m.get("display_name", m["slug"]))[:200], "size": 0}
                for m in models if isinstance(m, dict) and m.get("visibility") == "list" and isinstance(m.get("slug"), str) and 0 < len(m["slug"]) <= 200]

    async def logout(self):
        async with self.guard():
            self.stop_pending()
            value = self.read()
            confirmed = not value.get("refresh_token")
            if value.get("refresh_token"):
                try:
                    discovery = await self.request("GET", DISCOVERY)
                    endpoint = discovery.get("revocation_endpoint", "")
                    url = urlsplit(endpoint)
                    if discovery.get("issuer") != ISSUER or url.scheme != "https" or url.netloc != "auth.openai.com" or url.query or url.fragment:
                        raise ChatGPTError("Не удалось подтвердить адрес отключения ChatGPT.")
                    await self.request("POST", endpoint, data={"token": value["refresh_token"], "token_type_hint": "refresh_token", "client_id": value["client_id"]})
                    confirmed = True
                except ChatGPTError:
                    pass
            self.write({k: v for k, v in value.items() if k not in {"access_token", "refresh_token", "id_token", "expires_at", "scopes"}})
            self.error = "" if confirmed else "Вход отключён на этом компьютере. Отзыв сессии на сервере не подтверждён; отключить WileyAI можно также в настройках ChatGPT."
            return self.status()

    async def cancel(self):
        async with self.guard():
            self.stop_pending()
            self.login_result()
            return self.status()

    async def close(self):
        self.stop_pending()
        for task in tuple(self.callbacks):
            task.cancel()
        if self.callbacks:
            await asyncio.gather(*tuple(self.callbacks), return_exceptions=True)

    async def reply(self, model, messages, schema=None):
        token = await self.token()
        body = {"model": model, "store": False, "stream": True, "input": []}
        for message in messages:
            role = "developer" if message["role"] == "system" else message["role"]
            if role not in {"developer", "user", "assistant"}:
                raise ChatGPTError("Неподдерживаемый тип сообщения ChatGPT.")
            body["input"].append({"role": role, "content": message["content"]})
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": "wileyai_decision", "strict": True, "schema": schema}}
        @asynccontextmanager
        async def transport():
            if self.client is not None:
                yield self.client
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), trust_env=True, follow_redirects=False) as client:
                    yield client
        try:
            async with transport() as client:
                async with client.stream("POST", RESOURCE + "/responses", headers={"Authorization": "Bearer " + token}, json=body) as response:
                    if response.status_code != 200:
                        raw = bytearray()
                        async for part in response.aiter_bytes():
                            raw.extend(part)
                            if len(raw) > 16384:
                                break
                        try:
                            error = json.loads(raw)
                        except ValueError:
                            error = {}
                        raise failure(response.status_code, error, response.headers.get("x-request-id", ""))
                    data = []
                    size = 0
                    async for line in response.aiter_lines():
                        size += len(line)
                        if size > 1024 * 1024:
                            raise ChatGPTError("ChatGPT вернул слишком большое событие ответа.")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            try:
                                item = json.loads("\n".join(data))
                            except ValueError as error:
                                raise ChatGPTError("Поток ChatGPT содержит некорректное событие.") from error
                            data, size = [], 0
                            if not isinstance(item, dict):
                                raise ChatGPTError("Поток ChatGPT содержит некорректное событие.")
                            kind = item.get("type")
                            if kind in {"response.output_text.delta", "response.refusal.delta"}:
                                if isinstance(item.get("delta"), str):
                                    yield item["delta"]
                            elif kind == "response.completed":
                                result = item.get("response", {})
                                if not isinstance(result, dict) or result.get("status") != "completed":
                                    raise ChatGPTError("ChatGPT не подтвердил завершение ответа.")
                                return
                            elif kind in {"response.failed", "error"}:
                                raise failure(0, item.get("response", item), response.headers.get("x-request-id", ""))
                            elif kind == "response.incomplete":
                                raise ChatGPTError("Ответ ChatGPT не завершён. Сохранённый текст можно продолжить.")
                    raise ChatGPTError("Соединение с ChatGPT оборвалось до завершения ответа. Сохранённый текст можно продолжить.")
        except httpx.HTTPError as error:
            raise ChatGPTError("Соединение с ChatGPT прервалось. Проверьте интернет; сессия сохранена.") from error
