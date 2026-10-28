import asyncio
import base64
import hashlib
import json
import os
import socket
import ssl
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from core import chatgpt, providers
from core.api import create_app
from core.config import Settings


@pytest.fixture
def vault(monkeypatch):
    values = {}
    monkeypatch.setattr(chatgpt.keyring, "get_password", lambda service, key: values.get((service, key)))
    def store(service, key, value):
        # Model the native Windows limit, including python-keyring's encoding.
        if len(value.encode("utf-16-le")) > 2560:
            raise ValueError("Windows CredentialBlob exceeds 2560 bytes")
        values[service, key] = value
    monkeypatch.setattr(chatgpt.keyring, "set_password", store)
    monkeypatch.setattr(chatgpt.keyring, "delete_password", lambda service, key: values.pop((service, key), None))
    return values


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def identity(key, initial_nonce, **updates):
    claims = {"iss": chatgpt.ISSUER, "aud": "oaiapp_fixture", "sub": "account-fixture", "email": "user@example.test",
              "nonce": initial_nonce, "iat": int(time.time()), "exp": int(time.time()) + 600}
    return jwt.encode(claims | updates, key, algorithm="RS256", headers={"kid": "fixture"})


class Remote:
    def __init__(self, key):
        self.key = key
        self.nonce = ""
        self.requests = []
        self.claims = {}
        self.token_error = None
        self.scopes = chatgpt.SCOPES
        self.events = [{"type": "response.output_text.delta", "delta": "Ответ "}, {"type": "response.output_text.delta", "delta": "ChatGPT."},
                       {"type": "response.completed", "response": {"status": "completed"}}]

    def handle(self, request):
        self.requests.append(request)
        if str(request.url) == chatgpt.DISCOVERY:
            return httpx.Response(200, json={"issuer": chatgpt.ISSUER, "jwks_uri": chatgpt.ISSUER + "/.well-known/jwks.json",
                                           "revocation_endpoint": chatgpt.ISSUER + "/api/accounts/oauth/revoke"})
        if request.url.path == "/.well-known/jwks.json":
            public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(200, json={"keys": [public | {"kid": "fixture", "use": "sig"}]})
        if str(request.url) == chatgpt.TOKEN:
            if self.token_error:
                return httpx.Response(self.token_error[0], json={"error": self.token_error[1]})
            params = parse_qs(request.content.decode())
            refresh = params["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"id_token": identity(self.key, self.nonce, **self.claims), "access_token": "access-refreshed" if refresh else "access-fixture",
                                           "refresh_token": "refresh-rotated" if refresh else "refresh-fixture", "expires_in": 3600,
                                           "token_type": "Bearer", "scope": self.scopes})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"slug": "fixture-model", "display_name": "Доступная модель", "visibility": "list"},
                                                       {"slug": "hidden", "visibility": "hide"}]})
        if request.url.path == "/v1/responses":
            data = "\n\n".join("data: " + json.dumps(e, ensure_ascii=False) for e in self.events) + "\n\n"
            return httpx.Response(200, text=data, headers={"content-type": "text/event-stream"})
        raise AssertionError(str(request.url))


async def authorize(auth, remote, *, query=None, new_account=False, host=None):
    started = await auth.start(new_account)
    params = parse_qs(urlsplit(started["url"]).query)
    remote.nonce = auth.pending["nonce"]
    callback = params["redirect_uri"][0]
    values = {"state": params["state"][0], "client_id": "oaiapp_fixture", "code": "code-fixture"} | (query or {})
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await client.get(callback + "?" + urlencode(values), headers={"Host": host} if host else {})
    return result, params


def test_real_loopback_pkce_signed_identity_and_secret_isolation(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                response, params = await authorize(auth, remote)
                assert response.status_code == 200 and "code-fixture" not in response.text
                assert params["client_id"] == ["dynamic_agent_client"] and params["agent_name_hint"] == ["WileyAI"]
                assert params["resource"] == [chatgpt.RESOURCE] and params["code_challenge_method"] == ["S256"]
                exchange = next(r for r in remote.requests if str(r.url) == chatgpt.TOKEN)
                form = parse_qs(exchange.content.decode())
                challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
                assert params["code_challenge"] == [challenge] and form["redirect_uri"] == params["redirect_uri"]
                assert form["client_id"] == ["oaiapp_fixture"] and "client_secret" not in form
                status = auth.status()
                assert status["connected"] and status["plan_enabled"] and status["email"] == "user@example.test"
                assert "access-fixture" not in json.dumps(status) and "refresh-fixture" not in json.dumps(status)
                assert not any("access-fixture" in p.read_text(errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
                assert all(len(v.encode("utf-16-le")) <= 2560 for (s, k), v in vault.items() if ":" in k)
                assert (await auth.models()) == [{"id": "fixture-model", "name": "Доступная модель", "size": 0}]
                host = auth.read()["host_id"]
                again = await auth.start()
                query = parse_qs(urlsplit(again["url"]).query)
                assert query["client_id"] == ["oaiapp_fixture"] and query["ext_agent_host_id"] == [host]
                assert "agent_name_hint" not in query and "id_token_hint" not in query
            finally:
                await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("updates", [{"nonce": "wrong"}, {"aud": "other-app"}, {"azp": "other-app"}, {"iss": "https://attacker.test"}, {"exp": 1}, {"sub": ""}])
def test_invalid_signed_identity_never_replaces_a_session(tmp_path, vault, signing_key, updates):
    async def scenario():
        remote = Remote(signing_key)
        remote.claims = updates
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                response, _ = await authorize(auth, remote)
                assert response.status_code == 400 and not auth.status()["connected"]
                assert "личность" in auth.status()["error"]
            finally:
                await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("host,query", [(None, {"state": "wrong"}), ("attacker.test", {})])
def test_foreign_callback_does_not_consume_the_pending_login(tmp_path, vault, signing_key, host, query):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                response, _ = await authorize(auth, remote, host=host, query=query)
                assert response.status_code != 200 and auth.status()["pending"]
                assert not any(str(r.url) == chatgpt.TOKEN for r in remote.requests)
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_declined_plan_permission_cannot_be_used_for_models_or_inference(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        remote.scopes = "openid profile email"
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                response, _ = await authorize(auth, remote)
                assert response.status_code == 200 and auth.status()["connected"] and not auth.status()["plan_enabled"]
                with pytest.raises(chatgpt.ChatGPTError, match="Разрешите"):
                    await auth.models()
                assert not any(r.url.host == "api.openai.com" for r in remote.requests)
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_refresh_is_serialized_across_instances_and_rotates_all_credentials(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            first = chatgpt.ChatGPT(tmp_path, client)
            second = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(first, remote)
                first.write(first.read() | {"expires_at": 1})
                assert await asyncio.gather(first.token(), second.token()) == ["access-refreshed"] * 2
                refreshes = [r for r in remote.requests if b"grant_type=refresh_token" in r.content]
                assert len(refreshes) == 1
                form = parse_qs(refreshes[0].content.decode())
                assert form["client_id"] == ["oaiapp_fixture"] and "scope" not in form
                assert second.read()["refresh_token"] == "refresh-rotated"
                assert "refresh-fixture" not in "".join(vault.values())
            finally:
                await first.close()
                await second.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("status,error,retained", [(400, "invalid_grant", False), (503, "temporarily_unavailable", True)])
def test_refresh_only_clears_confirmed_unusable_credentials(tmp_path, vault, signing_key, status, error, retained):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                auth.write(auth.read() | {"expires_at": 1})
                remote.token_error = status, error
                with pytest.raises(chatgpt.ChatGPTError):
                    await auth.token()
                assert auth.status()["connected"] is retained and auth.read()["client_id"] == "oaiapp_fixture"
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_logout_revokes_and_clears_tokens_but_preserves_host_registration(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                host = auth.read()["host_id"]
                assert not (await auth.logout())["connected"]
                request = next(r for r in remote.requests if r.url.path.endswith("/revoke"))
                assert parse_qs(request.content.decode())["token_type_hint"] == ["refresh_token"]
                assert auth.read()["host_id"] == host and auth.read()["client_id"] == "oaiapp_fixture"
                assert "access-fixture" not in "".join(vault.values()) and "refresh-fixture" not in "".join(vault.values())
                params = parse_qs(urlsplit((await auth.start())["url"]).query)
                assert "id_token_hint" not in params
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_atomic_credential_write_keeps_previous_generation_on_failure(tmp_path, vault, monkeypatch):
    auth = chatgpt.ChatGPT(tmp_path)
    auth.write({"host_id": "host", "access_token": "previous"})
    save = chatgpt.keyring.set_password
    def fail_commit(service, key, value):
        if key == auth.identifier:
            raise RuntimeError("fixture failure")
        save(service, key, value)
    monkeypatch.setattr(chatgpt.keyring, "set_password", fail_commit)
    with pytest.raises(chatgpt.ChatGPTError):
        auth.write({"host_id": "host", "access_token": "new" * 3000})
    assert auth.read()["access_token"] == "previous" and "newnewnew" not in "".join(vault.values())


def large_fixture_credentials():
    return {"client_id": "oaiapp_fixture", "host_id": "urn:uuid:fixture", "subject": "fixture-account",
            "email": "Проверка 😀@example.test", "access_token": "fixture-access-" + "a" * 31900,
            "refresh_token": "fixture-refresh-" + "r" * 31900, "id_token": "fixture-id-" + "i" * 31900,
            "scopes": ["openid", "chatgpt.tokens.use.direct"], "expires_at": time.time() + 300}


def test_large_session_uses_byte_safe_chunks_and_reads_more_than_fifty_parts(tmp_path, vault):
    auth = chatgpt.ChatGPT(tmp_path)
    expected = large_fixture_credentials()
    auth.write(expected)
    manifest = json.loads(vault[chatgpt.SERVICE, auth.identifier])
    assert 50 < manifest["parts"] <= chatgpt.MAX_CREDENTIAL_PARTS
    assert all(len(value.encode("utf-16-le")) <= 2560 for value in vault.values())
    assert chatgpt.ChatGPT(tmp_path).read() == expected
    auth.write({"access_token": "fixture-rotated"})
    assert len(vault) == 2  # Old large generation removed after the atomic commit.


def test_storage_failure_reports_a_safe_windows_error_code(tmp_path, vault, monkeypatch):
    class NativeFailure(OSError):
        winerror = 1783
    def fail(*args):
        raise NativeFailure("Do not include a secret from a backend exception")
    auth = chatgpt.ChatGPT(tmp_path)
    monkeypatch.setattr(chatgpt.keyring, "set_password", fail)
    with pytest.raises(chatgpt.ChatGPTError) as caught:
        auth.write({"access_token": "fixture"})
    assert caught.value.code == "windows_credential_1783" and caught.value.stage == "storage"
    assert "secret" not in str(caught.value)


@pytest.mark.skipif(os.name != "nt" or os.environ.get("WILEYAI_CREDENTIAL_TEST") != "1", reason="Opt-in native Windows Credential Manager test")
def test_real_windows_large_session_roundtrip_rotation_and_failed_write(tmp_path, monkeypatch, signing_key):
    # Synthetic credentials under a fresh namespace; never reads/changes the
    # user's ChatGPT connection or credentials for another application.
    service = "WileyAI.ChatGPT.Diagnostic." + uuid.uuid4().hex
    monkeypatch.setattr(chatgpt, "SERVICE", service)
    written, sizes = [], []
    original = chatgpt.keyring.set_password
    def tracked(namespace, name, value):
        assert namespace == service
        written.append(name)
        sizes.append(len(value.encode("utf-16-le")))
        original(namespace, name, value)
    monkeypatch.setattr(chatgpt.keyring, "set_password", tracked)
    auth = chatgpt.ChatGPT(tmp_path)
    try:
        # 24 KB exceeds the size of normal token sets without occupying almost
        # 200 global Windows vault entries during an atomic rotation. The
        # maximum 96 KB record is separately covered by the bounded fake vault.
        expected = large_fixture_credentials() | {
            "access_token": "fixture-access-" + "a" * 8000,
            "refresh_token": "fixture-refresh-" + "r" * 8000,
            "id_token": "fixture-id-" + "i" * 8000,
        }
        auth.write(expected)
        assert chatgpt.ChatGPT(tmp_path).read() == expected
        attempts = []
        def interrupted(namespace, name, value):
            attempts.append(name)
            if len(attempts) == 3:
                raise OSError("synthetic interrupted write")
            tracked(namespace, name, value)
        monkeypatch.setattr(chatgpt.keyring, "set_password", interrupted)
        with pytest.raises(chatgpt.ChatGPTError):
            auth.write(expected | {"access_token": "fixture-new-" + "b" * 8000})
        assert chatgpt.ChatGPT(tmp_path).read() == expected
        monkeypatch.setattr(chatgpt.keyring, "set_password", tracked)
        rotated = expected | {"access_token": "fixture-rotated-" + "c" * 8000}
        auth.write(rotated)
        assert chatgpt.ChatGPT(tmp_path).read() == rotated
        async def login():
            remote = Remote(signing_key)
            # A realistically large signed token must pass through the whole
            # callback, validation, native credential write and status flow.
            remote.claims = {"fixture_metadata": "large-signed-token" * 400}
            async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
                callback = chatgpt.ChatGPT(tmp_path / "callback", client)
                try:
                    response, _ = await authorize(callback, remote)
                    assert response.status_code == 200 and callback.status()["connected"]
                    assert callback.status()["plan_enabled"] and not callback.status()["error"]
                    assert chatgpt.ChatGPT(tmp_path / "callback").read() == callback.read()
                finally:
                    await callback.close()
        asyncio.run(login())
        assert max(sizes) <= 2560
        print(f"Native Windows vault: large session, restart, rollback, rotation and signed OAuth callback OK; max blob {max(sizes)} bytes")
    finally:
        for name in reversed(list(dict.fromkeys(written))):
            try:
                chatgpt.keyring.delete_password(service, name)
            except chatgpt.keyring.errors.PasswordDeleteError:
                pass


def test_failed_account_reauthorization_preserves_existing_connection(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                original = auth.read()
                remote.claims = {"sub": "another-person"}
                response, _ = await authorize(auth, remote)
                assert response.status_code == 400 and auth.read() == original
                response, _ = await authorize(auth, remote, new_account=True)
                assert response.status_code == 200 and auth.read()["subject"] == "another-person"
            finally:
                await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("endpoint,error_type", [(chatgpt.TOKEN, httpx.ConnectError), (chatgpt.DISCOVERY, httpx.ReadError)])
def test_transient_network_failure_completes_same_login(tmp_path, vault, signing_key, endpoint, error_type):
    async def scenario():
        remote, attempts = Remote(signing_key), []
        def handle(request):
            if str(request.url) == endpoint:
                attempts.append(request)
                if len(attempts) == 1:
                    raise error_type("private-network-detail", request=request)
            return remote.handle(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                response, _ = await authorize(auth, remote)
                assert response.status_code == 200 and auth.status()["connected"]
                assert len(attempts) == 2
                if endpoint == chatgpt.TOKEN:
                    assert attempts[0].content == attempts[1].content
                assert not auth.status()["diagnostic"]
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_lost_token_response_is_not_replayed_and_error_registration_survive_restart(tmp_path, vault, signing_key):
    async def scenario():
        remote, fail, exchanges = Remote(signing_key), True, []
        def handle(request):
            if str(request.url) == chatgpt.TOKEN:
                exchanges.append(request)
                if fail:
                    raise httpx.ReadError("SECRET-AUTH-CODE must never be displayed", request=request)
            return remote.handle(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            response, _ = await authorize(auth, remote)
            assert response.status_code == 400 and len(exchanges) == 1
            assert "передачи данных" in response.text
            assert not auth.status()["connected"] and auth.status()["registration_pending"]
            assert auth.status()["diagnostic"]["code"] == "network_transfer"
            assert auth.status()["diagnostic"]["stage"] == "token"
            assert auth.read()["pending_client_id"] == "oaiapp_fixture"
            await auth.close()
            restarted = chatgpt.ChatGPT(tmp_path, client)
            try:
                assert restarted.status()["error"] == auth.status()["error"]
                assert restarted.status()["registration_pending"]
                fail = False
                response, params = await authorize(restarted, remote)
                assert params["client_id"] == ["oaiapp_fixture"]
                assert "agent_name_hint" not in params
                assert response.status_code == 200 and restarted.status()["connected"]
                assert not restarted.status()["registration_pending"] and not restarted.status()["error"]
                assert "pending_client_id" not in restarted.read()
                contents = " ".join(p.read_text(errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
                assert all(secret not in contents for secret in ("access-fixture", "refresh-fixture", "code-fixture", "SECRET-AUTH-CODE", "id_token"))
            finally:
                await restarted.close()
    asyncio.run(scenario())


def test_exhausted_connect_retries_preserve_existing_account_and_show_reason(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                old = auth.read()
                attempts = []
                def unavailable(request):
                    attempts.append(request)
                    raise httpx.ConnectError("SENSITIVE TLS STRING", request=request)
                async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as broken:
                    auth.client = broken
                    response, _ = await authorize(auth, remote)
                assert response.status_code == 400 and len(attempts) == 3
                assert "VPN" in response.text and "SENSITIVE" not in response.text
                assert auth.read() == old and auth.status()["connected"]
                assert auth.status()["diagnostic"]["code"] == "network_connect"
            finally:
                await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("error,cause,code", [
    (httpx.ConnectError("private"), ssl.SSLError("private"), "network_tls"),
    (httpx.ConnectError("private"), socket.gaierror("private"), "network_dns"),
    (httpx.ProxyError("private"), None, "network_proxy"),
    (httpx.ReadTimeout("private"), None, "network_timeout"),
])
def test_network_diagnostics_classify_without_exposing_http_details(error, cause, code):
    error.__cause__ = cause
    result = chatgpt.network_failure(error, "discovery")
    assert result.code == code and result.stage == "discovery"
    assert "private" not in str(result) and "Этап:" in str(result)


def test_default_auth_and_inference_clients_honor_proxy_configuration(tmp_path, vault, signing_key, monkeypatch):
    async def scenario():
        remote, options = Remote(signing_key), []
        original = httpx.AsyncClient
        def client(**kwargs):
            options.append(kwargs)
            return original(transport=httpx.MockTransport(remote.handle))
        monkeypatch.setattr(chatgpt.httpx, "AsyncClient", client)
        auth = chatgpt.ChatGPT(tmp_path)
        try:
            await auth.request("GET", chatgpt.DISCOVERY)
            auth.write({"access_token": "fixture", "scopes": ["chatgpt.tokens.use.direct"], "expires_at": time.time() + 300})
            assert "".join([piece async for piece in auth.reply("fixture-model", [])]) == "Ответ ChatGPT."
            assert len(options) == 2
            assert all(item["trust_env"] and not item["follow_redirects"] and item.get("verify", True) for item in options)
        finally:
            await auth.close()
    asyncio.run(scenario())


def test_structured_decision_uses_responses_schema_and_keeps_local_history(tmp_path, vault, signing_key):
    async def scenario():
        remote = Remote(signing_key)
        remote.events[0]["delta"] = '{"mode":"fragments"}'
        remote.events.pop(1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                config = Settings(provider="chatgpt", chatgpt_connection=auth.identifier, model="fixture-model")
                schema = {"type": "object", "properties": {"mode": {"type": "string"}}, "required": ["mode"], "additionalProperties": False}
                result = await providers.structured(config, [{"role": "system", "content": "История WileyAI"}, {"role": "user", "content": "Прочитай"}], schema)
                assert json.loads(result) == {"mode": "fragments"}
                sent = json.loads(next(r.content for r in remote.requests if r.url.path == "/v1/responses"))
                assert sent["text"]["format"]["schema"] == schema and sent["input"][0]["content"] == "История WileyAI"
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_cancelling_an_answer_closes_the_provider_stream(tmp_path, vault):
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"type":"response.output_text.delta","delta":"First"}\n\n'
            await asyncio.sleep(60)
        async def aclose(self):
            closed.append(True)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            auth.write({"access_token": "fixture", "scopes": ["chatgpt.tokens.use.direct"], "expires_at": time.time() + 300})
            output = providers.chat(Settings(provider="chatgpt", chatgpt_connection=auth.identifier), [{"role": "user", "content": "hello"}])
            assert await anext(output) == "First"
            await output.aclose()
            assert closed == [True]
    asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["complete", "missing", "quota", "false-complete"])
def test_responses_stream_uses_plan_route_and_requires_terminal_success(tmp_path, vault, signing_key, ending):
    async def scenario():
        remote = Remote(signing_key)
        if ending == "missing": remote.events.pop()
        if ending == "quota": remote.events[-1] = {"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}}
        if ending == "false-complete": remote.events[-1]["response"]["status"] = "failed"
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote.handle)) as client:
            auth = chatgpt.ChatGPT(tmp_path, client)
            try:
                await authorize(auth, remote)
                config = Settings(provider="chatgpt", chatgpt_connection=auth.identifier, model="fixture-model")
                output = []
                async def consume():
                    async for text in providers.chat(config, [{"role": "system", "content": "Будь краткой"}, {"role": "user", "content": "Привет"}]):
                        output.append(text)
                if ending == "complete": await consume()
                else:
                    with pytest.raises(providers.IncompleteResponse, match="Лимит" if ending == "quota" else "ChatGPT"):
                        await consume()
                assert "".join(output) == "Ответ ChatGPT."
                sent = next(r for r in remote.requests if r.url.path == "/v1/responses")
                body = json.loads(sent.content)
                assert body["store"] is False and body["stream"] is True and body["input"][0]["role"] == "developer"
                assert "temperature" not in body and "max_tokens" not in body and "previous_response_id" not in body
                assert sent.headers["Authorization"] == "Bearer access-fixture"
            finally:
                await auth.close()
    asyncio.run(scenario())


def test_api_status_never_returns_credentials_and_profile_selection_is_bound(tmp_path, vault):
    token = "chatgpt-fixture-local-0123456789abcdef"
    app = create_app(tmp_path, token)
    auth = app.state.chatgpt
    auth.write({"access_token": "private-access", "refresh_token": "private-refresh", "scopes": ["chatgpt.tokens.use.direct"], "email": "fixture@example.test"})
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        assert client.get("/chatgpt/status", headers={"Authorization": ""}).status_code == 401
        status = client.get("/chatgpt/status")
        assert status.json()["connected"] and "private-access" not in status.text and "private-refresh" not in status.text
        config = client.get("/settings").json() | {"provider": "chatgpt", "chatgpt_connection": "a" * 64, "base_url": "https://attacker.test"}
        saved = client.put("/settings", json=config)
        assert saved.status_code == 200
        assert saved.json()["chatgpt_connection"] == auth.identifier and saved.json()["base_url"] == chatgpt.RESOURCE
        assert not saved.json()["has_api_key"]


def test_backup_cannot_select_another_profiles_oauth_registration(tmp_path):
    from core.storage import Store
    from core.backups import Backups
    source, target = Store(tmp_path / "source"), Store(tmp_path / "target")
    source.save_settings(Settings(provider="chatgpt", chatgpt_connection="a" * 64))
    target.save_settings(Settings(chatgpt_connection="b" * 64))
    manager = Backups(target)
    ticket = manager.preview(Backups(source).export())["ticket"]
    manager.restore(ticket, connections=True)
    assert target.settings().chatgpt_connection == "b" * 64


def test_chat_api_replies_with_account_credentials_and_no_api_key(tmp_path, vault, signing_key):
    token = "chatgpt-complete-route-0123456789abcdef"
    app = create_app(tmp_path, token)
    remote = Remote(signing_key)
    remote_client = httpx.AsyncClient(transport=httpx.MockTransport(remote.handle))
    app.state.chatgpt.client = remote_client
    app.state.chatgpt.write({"access_token": "access-fixture", "refresh_token": "refresh-fixture", "expires_at": time.time() + 300,
                             "scopes": ["chatgpt.tokens.use.direct"]})
    try:
        with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
            config = client.get("/settings").json() | {"provider": "chatgpt", "model": "fixture-model"}
            assert client.put("/settings", json=config).status_code == 200
            response = client.post("/chat", json={"text": "Расскажи коротко о звёздах"})
            events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
            done = next(e for e in events if e["type"] == "done")
            assert done["message"]["content"] == "Ответ ChatGPT."
            assert "access-fixture" not in response.text and "refresh-fixture" not in response.text
            sent = [r for r in remote.requests if r.url.path == "/v1/responses"]
            assert sent and all(r.headers["Authorization"] == "Bearer access-fixture" for r in sent)
            assert not client.get("/settings").json()["has_api_key"]
    finally:
        asyncio.run(remote_client.aclose())
