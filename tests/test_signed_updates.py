import asyncio
import base64
import hashlib
import json
import shutil

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core import signed_updates as updates


@pytest.fixture
def release(tmp_path):
    data = b"test-only installer"
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    artifact = {"platform": "windows", "arch": "x64", "name": "WileyAI-Setup.exe", "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "version": "1.2.10"}
    payload = {"schema": 2, "tag": "v1.2.10", "notes": "Test notes", "artifacts": [artifact]}
    requests = []

    def envelope():
        raw = json.dumps(payload).encode()
        return {"payload": base64.b64encode(raw).decode(),
                "signature": base64.b64encode(key.sign(raw, ec.ECDSA(hashes.SHA256()))).decode()}

    def transport(request):
        requests.append(request)
        if request.url.host == "api.github.com":
            assert request.url.path.endswith("/releases/latest")
            return httpx.Response(200, json={"tag_name": payload["tag"], "prerelease": "-" in payload["tag"],
                                             "assets": [{"name": updates.MANIFEST}, {"name": artifact["name"]}]})
        if request.url.path.endswith(updates.MANIFEST):
            return httpx.Response(200, json=envelope())
        return httpx.Response(200, content=data)

    updater = updates.SignedUpdates(tmp_path, base64.b64encode(public).decode(), transport=httpx.MockTransport(transport))
    return updater, transport, requests, payload


def test_signed_check_download_cache_and_recheck(release):
    updater, _, requests, _ = release

    async def scenario():
        offer = await updater.check("1.2.9")
        assert offer["version"] == "1.2.10"
        await updater.download()
        await updater.download()
        assert sum(req.url.path.endswith(".exe") for req in requests) == 1
        updater.path.write_bytes(b"tampered")
        with pytest.raises(ValueError):
            updater.installer()
        assert await updater.check("1.2.10") is None
        assert not any("Authorization" in req.headers for req in requests)
    asyncio.run(scenario())


def test_no_prerelease_or_downgrade(release):
    updater, _, _, payload = release
    assert asyncio.run(updater.check("1.3.0")) is None
    payload["tag"] = "v1.3.0-rc.2"
    assert asyncio.run(updater.check("1.2.9")) is None


def test_missing_latest_signed_manifest_has_no_older_release_fallback(release):
    updater, _, _, _ = release
    urls = []

    def unsigned(request):
        urls.append(request.url.path)
        return httpx.Response(200, json={"tag_name": "v1.2.10", "assets": []})

    updater.transport = httpx.MockTransport(unsigned)
    with pytest.raises(ValueError, match="нет подписанного манифеста"):
        asyncio.run(updater.check("1.2.9"))
    assert len(urls) == 1 and urls[0].endswith("/releases/latest")


@pytest.mark.parametrize("scenario", ["tampered", "redirect", "disk", "truncated", "offline"])
def test_fails_closed(release, monkeypatch, scenario):
    updater, transport, _, _ = release

    def broken(request):
        response = transport(request)
        if scenario == "offline":
            raise httpx.ConnectError("offline")
        if scenario == "tampered" and request.url.path.endswith(updates.MANIFEST):
            content = response.json()
            content["payload"] = base64.b64encode(b"{}").decode()
            return httpx.Response(200, json=content)
        if request.url.path.endswith(".exe"):
            if scenario == "redirect":
                return httpx.Response(302, headers={"Location": "https://evil.invalid/setup.exe"})
            if scenario == "truncated":
                return httpx.Response(200, content=b"bad")
        return response

    updater.transport = httpx.MockTransport(broken)
    if scenario == "disk":
        monkeypatch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(0, 0, 0))

    async def run():
        with pytest.raises((ValueError, httpx.HTTPError, OSError)):
            await updater.check("1.2.9")
            await updater.download()
        assert not updater.path.exists()
        assert not updater.path.with_suffix(".part").exists()
    asyncio.run(run())


def test_interrupted_download_can_retry_and_keeps_separate_user_data(release, tmp_path):
    updater, transport, _, _ = release
    user_file = tmp_path / "conversations.sqlite"
    user_file.write_bytes(b"existing profile")

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"test"
            raise httpx.ReadError("connection dropped")

    async def example():
        await updater.check("1.2.9")
        updater.transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Interrupted()))
        with pytest.raises(httpx.ReadError):
            await updater.download()
        assert not updater.path.with_suffix(".part").exists()
        updater.transport = httpx.MockTransport(transport)
        await updater.download()
        assert updater.installer().is_file()
        assert user_file.read_bytes() == b"existing profile"

    asyncio.run(example())


def test_signed_release_over_loopback_tls(release, tmp_path):
    from datetime import datetime, timedelta, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ssl
    import threading

    from cryptography import x509
    from cryptography.x509.oid import NameOID

    updater, catalog, requests, _ = release
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(minutes=10))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert_path, key_path)
    client_tls = ssl.create_default_context(cafile=str(cert_path))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # The test transport maps only the network address to loopback. The
            # production updater still validates the original release host/path.
            response = catalog(httpx.Request("GET", self.headers["X-Fixture-URL"], headers=dict(self.headers)))
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = server_tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        async def proxy(request):
            async with httpx.AsyncClient(verify=client_tls, trust_env=False) as client:
                return await client.get(f"https://localhost:{server.server_port}/release",
                                        headers={"X-Fixture-URL": str(request.url)})

        updater.transport = httpx.MockTransport(proxy)

        async def scenario():
            await updater.check("1.2.9")
            await updater.download()
            assert updater.installer().read_bytes() == b"test-only installer"
            assert len(requests) == 3
        try:
            asyncio.run(scenario())
        finally:
            server.shutdown()
            thread.join(timeout=2)
