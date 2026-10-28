import asyncio
import hashlib
import json
import os
import ssl
import subprocess
from pathlib import Path
import time

import httpx
import pytest

from core.mobile import MobileGateway, allow_route, allowed_ip


@pytest.mark.parametrize("address,allowed", [
    ("127.0.0.1", True), ("192.168.1.2", True), ("10.20.30.40", True),
    ("172.31.255.1", True), ("100.64.0.1", True), ("100.127.255.255", True),
    ("100.128.0.1", False), ("172.32.1.1", False), ("8.8.8.8", False),
    ("169.254.1.1", False), ("::1", False), ("attacker.test", False),
])
def test_gateway_only_accepts_private_and_tailscale_ipv4(address, allowed):
    assert allowed_ip(address) is allowed


def test_only_explicit_mobile_routes_are_forwarded():
    assert allow_route("POST", "/chat") and allow_route("GET", "/messages")
    assert allow_route("POST", "/voice/transcribe") and allow_route("GET", "/tasks")
    for method, path in [("GET", "/settings"), ("POST", "/mobile/start"), ("POST", "/chatgpt/logout"),
                         ("GET", "/backups/export"), ("POST", "/models/pull"), ("POST", "/chat/../settings"),
                         ("DELETE", "/conversations/all"), ("GET", "/mail"), ("POST", "/voice/download")]:
        assert not allow_route(method, path)


def test_certificate_persists_and_mismatch_fails_closed(tmp_path):
    gateway = MobileGateway(tmp_path, "fixture-secret")
    cert, key = gateway._certificate()
    first = gateway.fingerprint
    assert len(first) == 64
    another = MobileGateway(tmp_path, "fixture-secret")
    assert another._certificate() == (cert, key) and another.fingerprint == first
    other = MobileGateway(tmp_path / "different", "fixture-secret")
    other._certificate()
    key.write_bytes((tmp_path / "different/mobile/server.key").read_bytes())
    with pytest.raises(ValueError, match="не совпадают"):
        another._certificate()


def test_corrupt_mobile_device_file_does_not_prevent_main_app_startup(tmp_path):
    directory = tmp_path / "mobile"; directory.mkdir()
    (directory / "devices.json").write_text("not-json")
    gateway = MobileGateway(tmp_path, "fixture-secret")
    assert "повреждён" in gateway.status()["error"]
    with pytest.raises(ValueError, match="повреждён"):
        asyncio.run(gateway.start(8000))
    assert (directory / "devices.json").read_text() == "not-json"


def test_pairing_private_peer_authentication_proxy_and_revoke(tmp_path):
    async def run():
        calls = []
        class Stream(httpx.AsyncByteStream):
            def __init__(self, value): self.value = value
            async def __aiter__(self): yield self.value
        def backend(request):
            calls.append(request)
            assert request.headers["authorization"] == "Bearer desktop-fixture-secret"
            if request.url.path == "/chat":
                return httpx.Response(200, stream=Stream('data: {"type":"delta","text":"Привет"}\n\n'.encode()), headers={"content-type": "text/event-stream"})
            return httpx.Response(200, stream=Stream('[{"id":"example","title":"Тест"}]'.encode()), headers={"content-type": "application/json"})
        gateway = MobileGateway(tmp_path, "desktop-fixture-secret")
        gateway.client = httpx.AsyncClient(base_url="http://127.0.0.1:1234", transport=httpx.MockTransport(backend))
        gateway.pair_code = "pairing-fixture-code-with-entropy"
        gateway.pair_expires = time.monotonic() + 300
        transport = httpx.ASGITransport(app=gateway.app, client=("192.168.10.3", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="https://fixture") as phone:
            assert (await phone.get("/api/conversations")).status_code == 401
            assert (await phone.post("/pair", json={"code": "wrong-pairing-code-123456", "name": "Тест"})).status_code == 403
            paired = await phone.post("/pair", json={"code": gateway.pair_code, "name": "Тестовый Android"})
            assert paired.status_code == 200
            token, device = paired.json()["token"], paired.json()["device_id"]
            assert token not in (tmp_path / "mobile/devices.json").read_text()
            assert gateway.devices[0]["hash"] == hashlib.sha256(token.encode()).hexdigest()
            assert (await phone.post("/pair", json={"code": "pairing-fixture-code-with-entropy", "name": "Test"})).status_code == 403
            headers = {"Authorization": "Bearer " + token}
            assert (await phone.get("/api/conversations", headers=headers)).json()[0]["title"] == "Тест"
            response = await phone.post("/api/chat", headers=headers, json={"text": "Привет"})
            assert response.status_code == 200 and "Привет" in response.text
            assert calls[-1].headers["authorization"] != "Bearer " + token
            assert (await phone.get("/api/settings", headers=headers)).status_code == 403
            assert (await phone.get("/ping", headers=headers)).json() == {"ok": True}
            assert (await phone.get("/ping")).status_code == 401
            assert (await phone.get("/api/conversations", headers=headers | {"Origin": "https://attacker.test"})).status_code == 403
            gateway.revoke(device)
            assert (await phone.get("/api/conversations", headers=headers)).status_code == 401
        await gateway.client.aclose()
        other = MobileGateway(tmp_path, "desktop-fixture-secret")
        assert other.devices == []
    asyncio.run(run())


def test_public_peer_pairing_expiry_and_rate_limit(tmp_path):
    async def run():
        gateway = MobileGateway(tmp_path, "fixture")
        gateway.pair_code, gateway.pair_expires = "fixture-pairing-code-valid-123456", time.monotonic() + 300
        public = httpx.ASGITransport(app=gateway.app, client=("8.8.8.8", 9999))
        async with httpx.AsyncClient(transport=public, base_url="https://fixture") as client:
            assert (await client.post("/pair", json={"code": gateway.pair_code})).status_code == 403
        private = httpx.ASGITransport(app=gateway.app, client=("10.0.0.2", 9999))
        async with httpx.AsyncClient(transport=private, base_url="https://fixture") as client:
            for _ in range(10):
                assert (await client.post("/pair", json={"code": "incorrect-pairing-code-123456"})).status_code == 403
            assert (await client.post("/pair", json={"code": gateway.pair_code})).status_code == 429
            gateway.failures.clear(); gateway.pair_expires = time.monotonic() - 1
            assert (await client.post("/pair", json={"code": gateway.pair_code})).status_code == 403
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("WILEYAI_MOBILE_NETWORK_TEST") != "1", reason="Opens temporary loopback HTTPS listeners")
def test_real_tls_pair_and_local_core_proxy(tmp_path, monkeypatch):
    async def run():
        requests = []
        async def local_core(reader, writer):
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode("ascii").split("\r\n")
            request_line = lines[0]
            headers = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in lines[1:] if ":" in line}
            if int(headers.get("content-length", "0")):
                await reader.readexactly(int(headers["content-length"]))
            requests.append((request_line, headers.get("authorization")))
            if request_line.startswith("POST /chat "):
                body = b'data: {"type":"delta","text":"hello"}\n\ndata: {"type":"done"}\n\n'
                content_type = "text/event-stream"
            else:
                body = b'[{"id":"fixture","title":"Test"}]'
                content_type = "application/json"
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain(); writer.close(); await writer.wait_closed()
        core = await asyncio.start_server(local_core, "127.0.0.1", 0)
        gateway = MobileGateway(tmp_path, "local-secret-do-not-expose")
        monkeypatch.setattr("core.mobile.local_addresses", lambda: ["127.0.0.1"])
        try:
            state = await gateway.start(core.sockets[0].getsockname()[1])
            assert state["running"] and state["port"] == 48443
            gateway.pair_code = "tls-test-pairing-code-123456789"
            gateway.pair_expires = time.monotonic() + 300
            context = ssl.create_default_context(cafile=str(tmp_path / "mobile/server.crt")); context.check_hostname = False
            reader, writer = await asyncio.open_connection("127.0.0.1", state["port"], ssl=context)
            certificate = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
            assert hashlib.sha256(certificate).hexdigest() == state["fingerprint"]
            writer.close(); await writer.wait_closed()
            async with httpx.AsyncClient(verify=context, trust_env=False, base_url=f'https://127.0.0.1:{state["port"]}') as phone:
                paired = await phone.post("/pair", json={"code": gateway.pair_code, "name": "Android test"})
                assert paired.status_code == 200
                token = paired.json()["token"]
                headers = {"Authorization": "Bearer " + token}
                assert (await phone.get("/api/conversations", headers=headers)).json()[0]["id"] == "fixture"
                streamed = await phone.post("/api/chat", headers=headers, json={"text": "hello"})
                assert streamed.status_code == 200 and '"type":"done"' in streamed.text
                assert all(auth == "Bearer local-secret-do-not-expose" for _, auth in requests)
                assert token not in (tmp_path / "mobile/devices.json").read_text()
            if os.environ.get("WILEYAI_ANDROID_JVM_PROBE") == "1":
                gateway.pair_code = "android-java-pairing-code-123456"
                gateway.pair_expires = time.monotonic() + 300
                classes = Path(__file__).resolve().parents[1] / "local/android-java-probe"
                java = os.environ.get("WILEYAI_JAVA", "java")
                result = await asyncio.to_thread(subprocess.run, [java, "-cp", str(classes), "PinProbe", "127.0.0.1", state["fingerprint"], gateway.pair_code],
                                                 capture_output=True, text=True, timeout=30)
                assert result.returncode == 0, result.stdout + result.stderr
                assert "wrong certificate rejected" in result.stdout
                assert all(auth == "Bearer local-secret-do-not-expose" for _, auth in requests)
            await gateway.shutdown()
            assert not gateway.status()["running"]
            restarted = MobileGateway(tmp_path, "local-secret-do-not-expose")
            assert restarted.enabled
            restarted_state = await restarted.start(core.sockets[0].getsockname()[1])
            assert restarted_state["running"] and restarted_state["fingerprint"] == state["fingerprint"]
            await restarted.stop()
            assert not MobileGateway(tmp_path, "local-secret-do-not-expose").enabled
        finally:
            await gateway.stop()
            core.close(); await core.wait_closed()
    asyncio.run(run())
