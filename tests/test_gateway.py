"""Remote Gateway invariants with isolated fake accounts; never reads personal provider sessions."""
import asyncio
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from gateway.app import create_app
from gateway.store import Store, new_id
from gateway.protocol import Capability, GatewayError, Model, ProviderEvent
from gateway.adapters.chatgpt import ChatGPTAdapter
from gateway.adapters.compatible import CompatibleAdapter
from gateway.adapters.testing import TestAdapter as FakeAdapter


@pytest.fixture
def gateway(tmp_path):
    key = secrets.token_bytes(32)
    store = Store(tmp_path, key)
    owner, stranger = new_id(), new_id()
    token, other = store.token(owner, "admin"), store.token(stranger)
    app = create_app(tmp_path, key, development=True, test_mode=True, store=store)
    with TestClient(app) as client:
        yield client, app, store, owner, {"Authorization": "Bearer " + token}, {"Authorization": "Bearer " + other}


def connected(gateway):
    client, app, store, owner, headers, other = gateway
    response = client.post("/api/v1/connections", headers=headers, json={"provider_id": "test-provider", "consent": True})
    assert response.status_code == 200, response.text
    account = response.json()["id"]
    response = client.post("/api/v1/conversations", headers=headers, json={"connection_id": account, "model_id": "test-text-v1"})
    assert response.status_code == 200, response.text
    return account, response.json()["id"]


def generate(gateway, conversation, text="Привет", request_id=None, **extra):
    client, _, _, _, headers, _ = gateway
    response = client.post(f"/api/v1/conversations/{conversation}/runs", headers=headers,
                           json={"request_id": request_id or new_id(), "text": text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def events(gateway, run, after=0):
    client, _, _, _, headers, _ = gateway
    response = client.get(f"/api/v1/runs/{run}/events?after={after}", headers=headers)
    assert response.status_code == 200, response.text
    return response.text


def test_requires_gateway_token_and_consent(gateway):
    client, app, store, owner, headers, other = gateway
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/info").status_code == 401
    assert client.get("/api/v1/info", headers=headers).json()["protocol"] == 1
    assert client.post("/api/v1/connections", headers=headers, json={"provider_id": "test-provider"}).status_code == 403
    assert client.post("/api/v1/connections", headers=headers, json={"provider_id": "deepseek", "consent": True}).status_code == 422


def test_unknown_features_and_model_are_rejected(gateway):
    client, _, _, _, headers, _ = gateway
    account, conversation = connected(gateway)
    assert client.post("/api/v1/conversations", headers=headers, json={"connection_id": account, "model_id": "fake-gpt"}).status_code == 422
    for options in ({"web_search": True}, {"reasoning_mode": "hidden"}, {"tools": []}, {"fallback": "another-provider"}):
        response = client.post(f"/api/v1/conversations/{conversation}/runs", headers=headers, json={"request_id": new_id(), "text": "Привет", "options": options})
        assert response.status_code == 422


def test_models_are_scoped_to_the_account(gateway):
    client, app, store, owner, headers, other = gateway
    account, conversation = connected(gateway)
    models = client.get(f"/api/v1/connections/{account}/models", headers=headers).json()["models"]
    assert models[0]["id"] == "test-text-v1"
    assert models[0]["capabilities"]["text"]["state"] == "verified"
    assert "vision" not in models[0]["capabilities"]
    for path in (f"connections/{account}/models", f"conversations/{conversation}"):
        assert client.get("/api/v1/" + path, headers=other).status_code == 404


def test_sse_completed_history_and_idempotency(gateway):
    client, app, store, owner, headers, other = gateway
    account, conversation = connected(gateway)
    request_id = new_id()
    run = generate(gateway, conversation, request_id=request_id)
    assert generate(gateway, conversation, request_id=request_id)["id"] == run["id"]
    stream = events(gateway, run["id"])
    assert "event: message.delta" in stream and "event: run.completed" in stream
    data = client.get(f"/api/v1/runs/{run['id']}", headers=headers).json()
    assert "Привет" in data["text"] and data["state"] == "completed"
    history = client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    again = generate(gateway, conversation, request_id=request_id)
    assert again["id"] == run["id"]
    assert len(client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]) == 2
    assert client.post(f"/api/v1/conversations/{conversation}/runs", headers=headers, json={"request_id": request_id, "text": "Другой текст"}).status_code == 409


def test_event_replay_has_monotonic_ids_without_generation(gateway):
    client, app, store, owner, headers, other = gateway
    _, conversation = connected(gateway)
    run = generate(gateway, conversation)
    original = events(gateway, run["id"])
    ids = [int(line[4:]) for line in original.splitlines() if line.startswith("id: ")]
    assert ids == list(range(1, len(ids) + 1))
    replay = events(gateway, run["id"], 2)
    assert "id: 1\n" not in replay and "id: 2\n" not in replay and "run.completed" in replay
    assert client.get(f"/api/v1/runs/{run['id']}/events", headers=other).status_code == 404
    assert len(app.state.manager.jobs) == 0


def test_partial_error_is_saved_and_not_retried(gateway):
    client, app, store, owner, headers, other = gateway
    _, conversation = connected(gateway)
    run = generate(gateway, conversation, "test-partial-error")
    assert "event: run.failed" in events(gateway, run["id"])
    value = client.get(f"/api/v1/runs/{run['id']}", headers=headers).json()
    assert value["state"] == "failed" and value["text"]
    assert value["error"]["code"] == "rate_limited"
    assert len(store.list(owner, "run")) == 1


def test_cancel_and_fork_preserve_old_history(gateway):
    client, app, store, owner, headers, other = gateway
    _, conversation = connected(gateway)
    run = generate(gateway, conversation, "слово " * 100)
    response = client.post(f"/api/v1/runs/{run['id']}/cancel", headers=headers)
    assert response.json()["state"] == "cancelled"
    assert "run.cancelled" in events(gateway, run["id"])
    fork = client.post(f"/api/v1/conversations/{conversation}/fork", headers=headers, json={"before_message": 0})
    assert fork.status_code == 200 and fork.json()["messages"] == []
    assert client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]


def test_sources_survive_stream_and_history(gateway):
    client, _, _, _, headers, _ = gateway
    _, conversation = connected(gateway)
    run = generate(gateway, conversation, "test-citation")
    assert "https://example.com/source" in events(gateway, run["id"])
    value = client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()
    assert value["messages"][-1]["citations"][0]["url"] == "https://example.com/source"


def test_attachments_are_owned_and_require_a_capability(gateway):
    client, app, store, owner, headers, other = gateway
    _, conversation = connected(gateway)
    response = client.post("/api/v1/attachments", headers={**headers, "Content-Type": "text/plain", "X-File-Name": "sample.txt"}, content=b"test data")
    assert response.status_code == 200
    identifier = response.json()["id"]
    assert "data" not in response.json()
    assert client.delete(f"/api/v1/attachments/{identifier}", headers=other).status_code == 404
    response = client.post(f"/api/v1/conversations/{conversation}/runs", headers=headers, json={"request_id": new_id(), "text": "Файл", "attachments": [identifier]})
    assert response.status_code == 422
    assert client.post("/api/v1/attachments", headers={**headers, "Content-Type": "image/png"}, content=b"not an image").status_code == 415
    assert client.post("/api/v1/attachments", headers={**headers, "Content-Type": "text/plain", "X-File-Name": "../secret"}, content=b"test").status_code == 400


def test_secrets_and_chat_are_encrypted_and_owner_bound(tmp_path):
    key = secrets.token_bytes(32)
    store = Store(tmp_path, key)
    try:
        store.put("owner", "id", "credential", {"secret": "sensitive-value", "text": "private chat"})
        assert store.get("owner", "id")["secret"] == "sensitive-value"
        raw = store.db.execute("SELECT payload FROM records").fetchone()[0]
        assert b"sensitive-value" not in raw and b"private chat" not in raw
        with pytest.raises(GatewayError):
            store.open("other", "id", raw)
    finally:
        store.close()
    store = Store(tmp_path, secrets.token_bytes(32))
    try:
        with pytest.raises(GatewayError):
            store.get("owner", "id")
    finally:
        store.close()


def test_validation_and_logs_never_echo_a_credential(gateway):
    client, app, store, owner, headers, other = gateway
    secret = "test_private_credential_123"
    response = client.post("/api/v1/connections", headers=headers, json={"provider_id": "test-provider", "consent": True, "credential": secret, "unknown": secret})
    assert response.status_code == 422 and secret not in response.text
    assert client.get("/api/v1/info", headers={**headers, "Origin": "https://untrusted.example"}).status_code == 403
    assert client.post("/api/v1/connections", headers={**headers, "Content-Length": str(300000)}, content=b"{}").status_code == 413


def test_only_admin_can_mint_client_tokens(gateway):
    client, app, store, owner, headers, other = gateway
    assert client.post("/api/v1/clients", headers=other, json={"label": "test"}).status_code == 403
    response = client.post("/api/v1/clients", headers=headers, json={"label": "test"})
    token = response.json()["token"]
    child = {"Authorization": "Bearer " + token}
    assert client.get("/api/v1/info", headers=child).json()["owner_id"] == owner
    assert client.delete("/api/v1/client-session", headers=child).status_code == 200
    assert client.get("/api/v1/info", headers=child).status_code == 401


def test_server_restart_marks_inflight_as_interrupted(gateway):
    client, app, store, owner, headers, other = gateway
    identifier = new_id()
    store.put(owner, identifier, "run", {"state": "running", "text": "partial"})
    app.state.manager.recover()
    assert store.get(owner, identifier)["state"] == "interrupted"
    assert store.get(owner, identifier)["text"] == "partial"
    assert not app.state.manager.jobs


def test_compatible_streams_and_does_not_follow_redirects():
    seen = []
    def route(request):
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "dynamic-id"}]})
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\ndata: [DONE]\n\n')
    async def run():
        adapter = CompatibleAdapter("https://approved.example/v1", httpx.MockTransport(route))
        models = await adapter.models({"credential": "test-secret"})
        assert models[0].id == "dynamic-id" and not models[0].supports("vision")
        result = [event async for event in adapter.stream({"credential": "test-secret"}, models[0], [{"role": "user", "content": "Hello"}], {})]
        assert result[0].data["text"] == "Hello"
    asyncio.run(run())
    assert all(request.headers["authorization"] == "Bearer test-secret" for request in seen)
    assert len(seen) == 2


def test_oauth_requires_loopback_issued_client_state_and_verified_identity(gateway):
    client, app, store, owner, headers, other = gateway
    response = client.post("/api/v1/connections", headers=headers, json={"provider_id": "chatgpt", "consent": True})
    identifier = response.json()["id"]
    path = f"/api/v1/connections/{identifier}/auth"
    for url in ("https://attacker.example/callback", "http://127.0.0.1:4/auth/callback", "http://localhost:15000/auth/callback", "http://127.0.0.1:15000/wrong"):
        assert client.post(path + "/start", headers=headers, json={"redirect_uri": url}).status_code == 400
    flow = client.post(path + "/start", headers=headers, json={"redirect_uri": "http://127.0.0.1:15000/auth/callback"}).json()
    params = parse_qs(urlsplit(flow["url"]).query)
    assert params["code_challenge_method"] == ["S256"] and params["resource"] == ["https://api.openai.com/v1"]
    assert flow["state"] == params["state"][0]
    wrong = client.post(path + "/complete", headers=headers, json={"flow_id": flow["flow_id"], "state": "wrong-state-long-enough", "code": "test", "client_id": "issued"})
    assert wrong.status_code == 403
    denied = client.post(path + "/complete", headers=headers, json={"flow_id": flow["flow_id"], "state": flow["state"], "error": "access_denied"})
    assert denied.status_code == 403
    assert client.post(path + "/complete", headers=headers, json={"flow_id": flow["flow_id"], "state": flow["state"], "code": "test", "client_id": "issued"}).status_code == 404


def test_cancel_before_creation_prevents_lost_ack_replay(gateway):
    client, _, _, _, headers, _ = gateway
    _, conversation = connected(gateway)
    request_id = new_id()
    assert client.post(f"/api/v1/requests/{request_id}/cancel", headers=headers).json()["state"] == "cancelled"
    response = client.post(f"/api/v1/conversations/{conversation}/runs", headers=headers,
                           json={"request_id": request_id, "text": "must never be sent"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "request_cancelled"
    assert client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"] == []


def test_context_is_seeded_only_once(gateway):
    client, _, _, _, headers, _ = gateway
    _, conversation = connected(gateway)
    seed = [{"role": "user", "content": "old question"}, {"role": "assistant", "content": "old answer"}]
    first = generate(gateway, conversation, context=seed)
    events(gateway, first["id"])
    second = generate(gateway, conversation, context=seed)
    events(gateway, second["id"])
    history = client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]
    assert len(history) == 6 and sum(m["content"] == "old question" for m in history) == 1


def test_history_pagination_and_server_deletion_are_owner_scoped(gateway):
    client, _, store, owner, headers, other = gateway
    _, conversation = connected(gateway)
    run = generate(gateway, conversation)
    events(gateway, run["id"])
    metadata = client.get(f"/api/v1/conversations/{conversation}?limit=0", headers=headers).json()
    assert metadata["messages"] == [] and metadata["message_count"] == 2
    last = client.get(f"/api/v1/conversations/{conversation}?limit=1", headers=headers).json()
    assert last["messages"][0]["role"] == "assistant" and last["next_before"] == 1
    first = client.get(f"/api/v1/conversations/{conversation}?limit=1&before=1", headers=headers).json()
    assert first["messages"][0]["role"] == "user" and first["next_before"] is None
    assert client.delete(f"/api/v1/conversations/{conversation}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/conversations/{conversation}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/runs/{run['id']}", headers=headers).status_code == 404
    assert not store.events(owner, run["id"])


def test_cancelling_an_unscheduled_job_produces_a_terminal_event(gateway):
    _, app, store, owner, _, _ = gateway
    identifier = new_id()
    store.put(owner, identifier, "run", {"state": "queued", "text": ""})
    async def run():
        task = asyncio.create_task(asyncio.sleep(300))
        app.state.manager.jobs[owner, identifier] = task
        assert (await app.state.manager.cancel(owner, identifier))["state"] == "cancelled"
    asyncio.run(run())
    assert store.events(owner, identifier)[-1][1]["type"] == "run.cancelled"


@pytest.mark.parametrize("data,code", [(b"x" * (256*1024+1), "provider_changed"), (b"data: incomplete", "stream_interrupted"), (b"data: \xff\n\n", "provider_changed")], ids=["oversized-line", "truncated-line", "invalid-utf8"])
def test_upstream_sse_is_bounded_before_line_parsing(data, code):
    from gateway.sse import bounded_lines
    async def run():
        response = httpx.Response(200, content=data)
        with pytest.raises(GatewayError) as error:
            _ = [line async for line in bounded_lines(response)]
        assert error.value.code == code
    asyncio.run(run())


@pytest.mark.parametrize("terminal", ["completed", "incomplete", "quota", "missing"])
def test_signed_siwc_oauth_discovery_refresh_and_responses(tmp_path, terminal):
    """The official protocol with locally signed identity tokens; no real account or network."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-signing-key", use="sig")
    seen, state = [], {}

    def route(request):
        seen.append(request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": "https://auth.openai.com", "jwks_uri": "https://auth.openai.com/.well-known/jwks.json", "revocation_endpoint": "https://auth.openai.com/revoke"})
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path.endswith("oauth/token"):
            fields = parse_qs(request.content.decode())
            assert fields["client_id"] == ["wiley-issued-test"]
            if fields["grant_type"] == ["authorization_code"]:
                assert fields["code_verifier"] == [state["verifier"]]
            now = int(time.time())
            identity = jwt.encode({"iss": "https://auth.openai.com", "aud": "wiley-issued-test", "sub": "mock-user", "iat": now, "exp": now+300, "nonce": state["nonce"]}, key, algorithm="RS256", headers={"kid": "test-signing-key"})
            return httpx.Response(200, json={"access_token": "mock-access", "refresh_token": "mock-refresh", "token_type": "Bearer", "expires_in": 3600, "scope": "chatgpt.tokens.use.direct", "id_token": identity})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"slug": "account-dynamic-model", "display_name": "Account model", "visibility": "list", "input_modalities": ["text", "image"], "supported_reasoning_efforts": ["low"], "supports_web_search": True}, {"slug": "not-for-menu", "visibility": "hidden"}]})
        if request.url.path == "/v1/responses":
            body = json.loads(request.content)
            assert body["model"] == "account-dynamic-model" and body["store"] is False and body["stream"] is True
            assert "max_output_tokens" not in body and "previous_response_id" not in body
            assert body["input"][0]["content"][1]["type"] == "input_image"
            stream = [{"type": "response.output_text.delta", "delta": "Ответ"}, {"type": "response.output_text.annotation.added", "annotation": {"type": "url_citation", "url": "https://example.com/evidence", "title": "Источник"}}]
            if terminal == "completed":
                stream.append({"type": "response.completed"})
            elif terminal != "missing":
                stream.append({"type": "response.incomplete" if terminal == "incomplete" else "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded" if terminal == "quota" else ""}}})
            return httpx.Response(200, text="".join("data: "+json.dumps(event)+"\n\n" for event in stream))
        if request.url.path == "/revoke":
            return httpx.Response(200, json={})
        raise AssertionError("Unexpected upstream route: " + request.url.path)

    async def run():
        store = Store(tmp_path, secrets.token_bytes(32))
        adapter = ChatGPTAdapter(store, transport=httpx.MockTransport(route))
        account = {"id": new_id(), "owner": new_id()}
        try:
            flow = await adapter.start_auth(account, "http://127.0.0.1:15000/auth/callback")
            state.update(store.get(account["owner"], flow["flow_id"]))
            from gateway.protocol import AuthComplete
            result = await adapter.complete_auth(account, AuthComplete(flow_id=flow["flow_id"], state=flow["state"], code="one-use-code", client_id="wiley-issued-test"))
            assert result["status"] == "connected"
            # Force the real rotating-refresh path, still with mock account tokens.
            value = adapter.session(account).read()
            value["expires_at"] = 0
            adapter.session(account).write(value)
            models = await adapter.models(account)
            assert len(models) == 1 and models[0].supports("vision") and not models[0].supports("image_generation")
            output = []
            try:
                async for event in adapter.stream(account, models[0], [{"role": "user", "content": [{"type": "input_text", "text": "Describe"}, {"type": "input_image", "image_url": "data:image/png;base64,dGVzdA=="}]}], {"reasoning_mode": "low", "web_search": True}):
                    output.append(event)
            except GatewayError as error:
                assert terminal != "completed"
                assert error.code == ("quota_exceeded" if terminal == "quota" else "stream_interrupted")
            else:
                assert terminal == "completed"
            assert output[0].data["text"] == "Ответ" and output[1].data["url"] == "https://example.com/evidence"
            assert (await adapter.disconnect(account))["revoked_upstream"]
            assert (await adapter.status(account))["status"] == "authorization_required"
            assert len([r for r in seen if r.url.path == "/v1/responses"]) == 1
            assert len([r for r in seen if r.url.path.endswith("oauth/token")]) == 2
        finally:
            await adapter.close()
            store.close()
    asyncio.run(run())
