"""Private Android gateway. The desktop API and its session key stay on loopback."""
import asyncio
from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import psutil
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(item) for item in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"))
MAX_REQUEST = 10 * 1024 * 1024 + 128 * 1024
MOBILE_PORT = 48443
ROUTES = {
    "GET": (r"/conversations", r"/messages", r"/tasks", r"/notes"),
    "POST": (r"/conversations", r"/chat", r"/chat/stop", r"/voice/transcribe", r"/voice/synthesize", r"/voice/stop", r"/tasks", r"/notes"),
    "PUT": (r"/tasks/[A-Za-z0-9_-]{1,64}", r"/notes/[A-Za-z0-9_-]{1,64}"),
    "DELETE": (r"/tasks/[A-Za-z0-9_-]{1,64}", r"/notes/[A-Za-z0-9_-]{1,64}"),
}


def allowed_ip(value):
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and any(address in network for network in PRIVATE_NETWORKS)
    except ValueError:
        return False


def local_addresses():
    found = set()
    for items in psutil.net_if_addrs().values():
        for item in items:
            if item.family == socket.AF_INET and item.address != "127.0.0.1" and allowed_ip(item.address):
                found.add(item.address)
    return sorted(found, key=lambda value: (not ipaddress.ip_address(value) in PRIVATE_NETWORKS[-1], value))[:12]


def allow_route(method, path):
    return any(re.fullmatch(pattern, path) for pattern in ROUTES.get(method, ()))


class PairBody(BaseModel):
    code: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(default="Android", min_length=1, max_length=80)


class MobileServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The main WileyAI server owns process signals.
        yield


class MobileGateway:
    def __init__(self, root, secret):
        self.root, self.secret = Path(root), secret
        self.directory = self.root / "mobile"
        self.server = None
        self.task = None
        self.socket = None
        self.client = None
        self.port = 0
        self.fingerprint = ""
        self.pair_code = None
        self.pair_expires = 0
        self.failures = []
        self.storage_error = ""
        self.start_error = ""
        try:
            self.enabled = json.loads((self.directory / "settings.json").read_text(encoding="utf-8")).get("enabled") is True
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            self.enabled = False
        try:
            self.devices = self._read_devices()
        except ValueError as error:
            self.devices = []
            self.storage_error = str(error)
        self.lock = asyncio.Lock()
        self.app = self._application()

    def _save_enabled(self, enabled):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "settings.part"
        temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
        temporary.replace(self.directory / "settings.json")
        self.enabled = enabled

    def _read_devices(self):
        try:
            raw = (self.directory / "devices.json").read_text(encoding="utf-8")
            if len(raw) > 64_000:
                raise ValueError()
            records = json.loads(raw)
            if not isinstance(records, list) or len(records) > 20:
                raise ValueError()
            if not all(isinstance(d, dict) and re.fullmatch(r"[a-f0-9]{32}", d.get("id", ""))
                       and re.fullmatch(r"[a-f0-9]{64}", d.get("hash", ""))
                       and isinstance(d.get("name"), str) and len(d["name"]) <= 80 for d in records):
                raise ValueError()
            return records
        except FileNotFoundError:
            return []
        except (ValueError, OSError, TypeError):
            raise ValueError("Список подключённых телефонов повреждён. Проверьте файл mobile/devices.json.")

    def _save_devices(self, records):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "devices.part"
        temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.directory / "devices.json")
        self.devices = records

    def _certificate(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        cert_file, key_file = self.directory / "server.crt", self.directory / "server.key"
        if cert_file.is_file() and key_file.is_file():
            cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
            key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
            if cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
                raise ValueError("Ключ телефона и сертификат не совпадают. Подключите телефоны заново после исправления файлов mobile.")
        elif cert_file.exists() or key_file.exists():
            raise ValueError("Не найден файл сертификата телефона. Проверьте каталог mobile.")
        else:
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WileyAI mobile")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                    .not_valid_after(now + timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            key_tmp, cert_tmp = self.directory / "server.key.part", self.directory / "server.crt.part"
            key_tmp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            try:
                os.chmod(key_tmp, 0o600)
            except OSError:
                pass
            cert_tmp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_tmp.replace(key_file)
            cert_tmp.replace(cert_file)
        self.fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        return cert_file, key_file

    def status(self):
        running = bool(self.task and not self.task.done() and self.server and self.server.started)
        return {"running": running, "enabled": self.enabled, "port": self.port if running else 0, "addresses": local_addresses(),
                "fingerprint": self.fingerprint if running else "", "pairing": bool(running and self.pair_code and time.monotonic() < self.pair_expires),
                "devices": [{"id": d["id"], "name": d["name"]} for d in self.devices], "error": self.storage_error or self.start_error}

    async def start(self, upstream_port):
        async with self.lock:
            if self.task and not self.task.done():
                return self.status()
            if self.task and self.task.done():
                await self._stop()
            if self.storage_error:
                raise ValueError(self.storage_error)
            if not 1 <= upstream_port <= 65535:
                raise ValueError("Не удалось определить локальный порт WileyAI")
            cert, key = await asyncio.to_thread(self._certificate)
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.socket.bind(("0.0.0.0", MOBILE_PORT))
            except OSError as error:
                self.socket.close()
                self.socket = None
                raise ValueError("Порт 48443 занят. Закройте программу, использующую его, и повторите.") from error
            self.socket.listen(128)
            self.port = self.socket.getsockname()[1]
            self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{upstream_port}", trust_env=False,
                                            follow_redirects=False, timeout=httpx.Timeout(180, connect=10))
            config = uvicorn.Config(self.app, log_level="warning", access_log=False, server_header=False,
                                    ssl_certfile=str(cert), ssl_keyfile=str(key), lifespan="off")
            self.server = MobileServer(config)
            self.task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
            for _ in range(100):
                if self.server.started:
                    try:
                        self._save_enabled(True)
                    except OSError as error:
                        await self._stop()
                        raise ValueError("Не удалось сохранить настройку подключения телефона") from error
                    self.start_error = ""
                    return self.status()
                if self.task.done():
                    await self.task
                    break
                await asyncio.sleep(0.05)
            await self._stop()
            raise ValueError("Не удалось запустить подключение телефона")

    async def _stop(self):
        self.pair_code = None
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(self.task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.client:
            await self.client.aclose()
        if self.socket:
            self.socket.close()
        self.server = self.task = self.socket = self.client = None
        self.port = 0

    async def stop(self):
        async with self.lock:
            try:
                self._save_enabled(False)
            except OSError as error:
                await self._stop()
                raise ValueError("Не удалось сохранить отключение телефона; проверьте доступ к папке данных") from error
            await self._stop()
            self.start_error = ""
            return self.status()

    async def shutdown(self):
        async with self.lock:
            await self._stop()

    def pairing(self, address):
        if not self.status()["running"]:
            raise ValueError("Сначала включите подключение телефона")
        if address not in local_addresses():
            raise ValueError("Выберите адрес этого компьютера")
        self.pair_code = secrets.token_urlsafe(24)
        self.pair_expires = time.monotonic() + 300
        self.failures.clear()
        alternatives = [item for item in local_addresses() if item != address]
        return {"uri": "wileyai://pair?" + urlencode({"host": address, "addresses": ",".join(alternatives), "port": self.port, "fingerprint": self.fingerprint, "code": self.pair_code}),
                "expires_seconds": 300}

    def revoke(self, device_id):
        remaining = [item for item in self.devices if item["id"] != device_id]
        if len(remaining) == len(self.devices):
            raise ValueError("Телефон уже удалён")
        self._save_devices(remaining)
        return self.status()

    def _application(self):
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.middleware("http")
        async def protect(request, call_next):
            peer = request.client.host if request.client else ""
            if not allowed_ip(peer):
                return JSONResponse({"detail": "Подключение доступно только в локальной сети или VPN"}, status_code=403)
            if request.headers.get("origin") or request.method == "OPTIONS":
                return JSONResponse({"detail": "Браузерные запросы недоступны"}, status_code=403)
            if request.method in {"POST", "PUT"}:
                try:
                    length = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_REQUEST:
                    return JSONResponse({"detail": "Недопустимый размер запроса"}, status_code=413)
            if request.url.path != "/pair":
                header = request.headers.get("authorization", "")
                token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
                digest = hashlib.sha256(token.encode()).hexdigest()
                if not token or not any(hmac.compare_digest(digest, d["hash"]) for d in self.devices):
                    return JSONResponse({"detail": "Телефон не подключён или его доступ отозван"}, status_code=401)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.post("/pair")
        async def pair(body: PairBody):
            now = time.monotonic()
            self.failures = [stamp for stamp in self.failures if now - stamp < 300]
            if len(self.failures) >= 10:
                return JSONResponse({"detail": "Слишком много попыток. Создайте новый код на компьютере."}, status_code=429)
            if not self.pair_code or now >= self.pair_expires or not hmac.compare_digest(body.code, self.pair_code):
                self.failures.append(now)
                return JSONResponse({"detail": "Код недействителен или истёк"}, status_code=403)
            if len(self.devices) >= 20:
                return JSONResponse({"detail": "Удалите неиспользуемый телефон на компьютере"}, status_code=409)
            self.pair_code = None
            token = secrets.token_urlsafe(32)
            entry = {"id": uuid.uuid4().hex, "name": body.name.strip() or "Android", "hash": hashlib.sha256(token.encode()).hexdigest()}
            self._save_devices([*self.devices, entry])
            return {"token": token, "device_id": entry["id"]}

        @app.get("/ping")
        async def ping():
            return {"ok": True}

        @app.api_route("/api/{target:path}", methods=["GET", "POST", "PUT", "DELETE"])
        async def proxy(target: str, request: Request):
            path = "/" + target
            if not allow_route(request.method, path) or not self.client:
                return JSONResponse({"detail": "Эта функция недоступна с телефона"}, status_code=403)
            headers = {"Authorization": "Bearer " + self.secret}
            if content_type := request.headers.get("content-type"):
                if not content_type.startswith(("application/json", "multipart/form-data;")):
                    return JSONResponse({"detail": "Недопустимый формат запроса"}, status_code=415)
                headers["Content-Type"] = content_type
            try:
                outbound = self.client.build_request(request.method, path, params=request.query_params, headers=headers,
                                                     content=await request.body())
                response = await self.client.send(outbound, stream=True)
            except httpx.HTTPError:
                return JSONResponse({"detail": "Ядро WileyAI недоступно на компьютере"}, status_code=503)
            result_headers = {key: value for key, value in response.headers.items() if key.lower() in {"content-type", "retry-after"}}
            return StreamingResponse(response.aiter_raw(), status_code=response.status_code, headers=result_headers,
                                     background=BackgroundTask(response.aclose))

        return app
