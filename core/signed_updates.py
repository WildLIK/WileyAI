"""Verify a public GitHub release against the WileyAI build's pinned update key."""

import base64
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
from datetime import date

import httpx

REPOSITORY = "WildLIK/WileyAI"
CATALOG = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSETS = f"https://github.com/{REPOSITORY}/releases/download"
MANIFEST = "wiley-update-v2.json"
HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
SEMVER = re.compile(r"v?(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")
MAX_ARTIFACT = 2 * 1024**3


def version(value):
    match = SEMVER.fullmatch(value) if isinstance(value, str) and len(value) <= 120 else None
    if not match:
        raise ValueError("Неверный формат версии.")
    major, minor, patch, pre = match.groups()
    identifiers = pre.split(".") if pre else []
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in identifiers):
        raise ValueError("Неверный формат предварительной версии.")
    return (int(major), int(minor), int(patch), not pre,
            tuple((0, int(part)) if part.isdigit() else (1, part) for part in identifiers))


def public_key():
    try:
        return Path(__file__).resolve().parents[1].joinpath("update-key.spki").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def verify_manifest(envelope, key_data, tag):
    # Lazy import: even published builds do not initialize crypto during first paint.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        key = serialization.load_der_public_key(base64.b64decode(key_data, validate=True))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        raw = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        key.verify(signature, raw, ec.ECDSA(hashes.SHA256()))
        manifest = json.loads(raw.decode("utf-8"))
        if (manifest["schema"] != 2 or manifest["tag"] != tag
                or not isinstance(manifest["notes"], str) or len(manifest["notes"]) > 8000
                or not isinstance(manifest["artifacts"], list) or len(manifest["artifacts"]) > 8):
            raise ValueError()
        if manifest.get("date"):
            date.fromisoformat(manifest["date"])
        return manifest
    except (InvalidSignature, KeyError, TypeError, ValueError) as error:
        raise ValueError("Подпись или формат манифеста выпуска не прошли проверку.") from error


class SignedUpdates:
    def __init__(self, root, key=None, *, transport=None):
        self.path = Path(root) / "updates-cache" / "WileyAI-Update.exe"
        self.key = public_key() if key is None else key
        self.transport = transport
        self.offer = None
        self.ready = False

    def client(self):
        return httpx.AsyncClient(transport=self.transport, follow_redirects=False, timeout=20,
                                 headers={"User-Agent": "WileyAI-Updater", "Accept-Encoding": "identity"})

    @staticmethod
    @asynccontextmanager
    async def response(client, url, *, api=False):
        url = httpx.URL(url)
        hosts = {"api.github.com"} if api else HOSTS
        for _ in range(5):
            if (url.scheme != "https" or url.host not in hosts or url.port not in {443, None}
                    or url.username or url.password):
                raise ValueError("Недопустимый адрес загрузки выпуска.")
            async with client.stream("GET", url) as response:
                if response.status_code in (301, 302, 303, 307, 308) and not api:
                    url = url.join(response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                yield response
                return
        raise ValueError("Слишком много перенаправлений при загрузке выпуска.")

    async def read_json(self, client, url, *, api=False):
        data = bytearray()
        async with self.response(client, url, api=api) as response:
            async for block in response.aiter_bytes(32768):
                if len(data) + len(block) > 1024**2:
                    raise ValueError("Метаданные выпуска превышают допустимый размер.")
                data.extend(block)
        return json.loads(data)

    async def check(self, installed):
        previous, ready = self.offer, self.ready
        self.offer = None
        self.ready = False
        if not self.key:
            raise ValueError("В этой сборке нет доверенного ключа обновлений.")
        current = version(installed)
        async with asyncio.timeout(60), self.client() as client:
            release = await self.read_json(client, CATALOG, api=True)
            if not isinstance(release, dict):
                raise ValueError("Некорректный выпуск GitHub.")
            if release.get("draft") or release.get("prerelease"):
                return None
            tag = release.get("tag_name", "")
            if not re.fullmatch(r"v[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", tag):
                raise ValueError("Недопустимая метка выпуска.")
            if version(tag) <= current:
                return None
            names = {asset.get("name") for asset in release.get("assets", [])}
            if MANIFEST not in names:
                raise ValueError("У последнего выпуска нет подписанного манифеста обновления.")
            prefix = f"{ASSETS}/{tag}/"
            manifest = verify_manifest(await self.read_json(client, prefix + MANIFEST), self.key, tag)
            choices = [item for item in manifest["artifacts"] if item.get("platform") == "windows" and item.get("arch") == "x64"]
            if len(choices) != 1:
                raise ValueError("В выпуске должен быть один установщик Windows x64.")
            item = choices[0]
            name = item.get("name", "")
            size = item.get("size")
            if (not NAME.fullmatch(name) or not name.endswith(".exe") or name not in names
                    or item.get("version") != tag[1:] or type(size) is not int or not 0 < size <= MAX_ARTIFACT
                    or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))):
                raise ValueError("Установщик не соответствует манифесту выпуска.")
            self.offer = {**item, "notes": manifest["notes"], "date": manifest.get("date", ""), "url": prefix + name}
            self.ready = ready and self.offer == previous
            return self.offer

    def installer(self):
        self.ready = False
        if not self.offer or not self.path.is_file() or self.path.stat().st_size != self.offer["size"]:
            raise ValueError("Скачайте проверенный установщик.")
        with self.path.open("rb") as data:
            valid = hashlib.file_digest(data, "sha256").hexdigest() == self.offer["sha256"]
        if not valid:
            raise ValueError("Контрольная сумма установщика изменилась.")
        self.ready = True
        return self.path

    async def download(self, progress=None):
        try:
            await asyncio.to_thread(self.installer)
        except ValueError:
            pass
        else:
            self.ready = True
            return
        if not self.offer:
            raise ValueError("Сначала проверьте наличие обновления.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_suffix(".part")
        part.unlink(missing_ok=True)
        if shutil.disk_usage(self.path.parent).free < self.offer["size"] + 16 * 1024**2:
            raise ValueError("Недостаточно места для загрузки обновления.")
        try:
            digest = hashlib.sha256()
            total = 0
            async with asyncio.timeout(1800), self.client() as client, self.response(client, self.offer["url"]) as response:
                with part.open("xb") as file:
                    async for block in response.aiter_bytes(128 * 1024):
                        total += len(block)
                        if total > self.offer["size"]:
                            raise ValueError("Загрузка превышает подписанный размер.")
                        digest.update(block)
                        file.write(block)
                        if progress:
                            progress(total, self.offer["size"])
            if total != self.offer["size"] or digest.hexdigest() != self.offer["sha256"]:
                raise ValueError("Установщик повреждён или загрузка прервана.")
            part.replace(self.path)
            self.ready = True
        finally:
            part.unlink(missing_ok=True)
