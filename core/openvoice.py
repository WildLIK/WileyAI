"""Optional CPU tone conversion, isolated from the core's TTS/ASR dependencies."""
import asyncio
import base64
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import uuid
import wave

from .qwen_session import Session

PROJECT = Path(__file__).resolve().parents[1]
CACHE = PROJECT / "local/openvoice-probe"
FILES = {
    "config.json": "9dfff60350b8c63f2c664efd92a61b2516efb22671466960f0e5dfebd881fa47",
    "checkpoint.pth": "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e",
}
LOCAL_ENGINES = {"piper", "silero", "silero_v5_6"}


class OpenVoice:
    def __init__(self, root: Path):
        self.root = root / "voices/openvoice"
        self.cache = CACHE
        self.sessions = {}
        self.install_lock = asyncio.Lock()
        self.installer = None
        self.verified = None

    def reference(self, key):
        paths = {"mita": PROJECT / "local/voice-samples/fish-mita.mp3",
                 "kind-mita": PROJECT / "local/voice-samples/fish-kind-mita.mp3",
                 "serena": PROJECT / "local/voice-samples/qwen3-serena.wav",
                 "custom": self.root / "reference.wav"}
        if key not in paths:
            raise ValueError("Неизвестный тембр OpenVoice")
        return paths[key]

    def installed(self):
        return bool(importlib.util.find_spec("torch")) and all(path.exists() for path in (
            self.cache / "source/openvoice/api.py", self.cache / "deps/librosa",
            *(self.cache / "weights" / name for name in FILES)))

    def info(self):
        return {"installed": self.installed(), "references": [
            {"id": key, "name": name, "available": self.reference(key).is_file()}
            for key, name in [("mita", "Мита Кепочка"), ("kind-mita", "Добрая Мита (Miside)"),
                              ("serena", "Serena"), ("custom", "Свой WAV-образец")]]}

    def validate(self, key):
        if not self.installed():
            raise ValueError("Установите OpenVoice в настройках голоса. Нужен также локальный модуль Torch: uv sync --extra dev --extra voice --extra tts --extra piper")
        path = self.reference(key)
        if not path.is_file():
            raise ValueError("Образец этого тембра OpenVoice отсутствует. Загрузите свой WAV-образец")
        return path

    def verify(self):
        fingerprint = tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in
                            (self.cache / "weights" / name for name in FILES))
        if fingerprint != self.verified:
            for name, digest in FILES.items():
                if hashlib.sha256((self.cache / "weights" / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("Контрольная сумма OpenVoice не совпала. Переустановите преобразователь")
            self.verified = fingerprint

    def save_reference(self, data):
        if len(data) > 5 * 1024**2:
            raise ValueError("Образец должен быть WAV до 5 МБ")
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                size = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                if audio.getsampwidth() != 2 or audio.getnchannels() not in {1, 2} or not 8000 <= audio.getframerate() <= 48000 or not 1 <= duration <= 30 or len(audio.readframes(audio.getnframes())) != size:
                    raise ValueError("invalid sample")
        except (wave.Error, EOFError, ValueError, ZeroDivisionError):
            raise ValueError("Нужен корректный WAV PCM16: 1–30 секунд, один или два канала, 8–48 кГц") from None
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / "reference.part"
        temporary.write_bytes(data)
        temporary.replace(self.reference("custom"))

    async def install(self):
        async with self.install_lock:
            try:
                self.installer = await asyncio.create_subprocess_exec(
                    sys.executable, str(PROJECT / "scripts/probe-voice-conversion.py"), "--prepare-only",
                    cwd=str(PROJECT), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                code = await asyncio.wait_for(self.installer.wait(), 600)
                if code or not self.installed():
                    raise ValueError("Не удалось установить OpenVoice. Проверьте интернет, наличие uv и модуля Torch")
                await asyncio.to_thread(self.verify)
                return self.info()
            except TimeoutError:
                raise ValueError("Установка OpenVoice превысила 10 минут. Повторите позже") from None
            finally:
                if self.installer and self.installer.returncode is None:
                    self.installer.kill()
                    await self.installer.wait()
                self.installer = None

    async def close_session(self, key):
        session = self.sessions.pop(key, None)
        if session:
            await session.close()

    async def stop(self, request_id=None, preserve_session=None):
        for key, session in list(self.sessions.items()):
            if key != preserve_session and (request_id is None or session.active_id == request_id):
                await self.close_session(key)

    async def close(self):
        await self.stop()
        if self.installer and self.installer.returncode is None:
            self.installer.kill()
            await self.installer.wait()

    async def render(self, audio, key, request_id, cancelled, session_id=None):
        reference = self.validate(key)
        await asyncio.to_thread(self.verify)
        identity = session_id or uuid.uuid4().hex
        session = self.sessions.get(identity)
        if session and (session.closed or (session.process and session.process.returncode is not None)):
            await self.close_session(identity)
            session = None
        if session is None:
            session = Session("cpu", name="OpenVoice")
            self.sessions[identity] = session
        if session.idle:
            session.idle.cancel()
        async with session.lock:
            success = False
            session.active_id = request_id
            try:
                if cancelled.is_set() or session.closed:
                    raise ValueError("Озвучка остановлена")
                if session.process is None:
                    session.process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "core.openvoice_worker", "--cache", str(self.cache),
                        cwd=str(PROJECT), env={**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1"},
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    session.drain = asyncio.create_task(session.diagnostics())
                if cancelled.is_set() or session.closed:
                    raise ValueError("Озвучка остановлена")
                try:
                    result, _ = await asyncio.wait_for(session.exchange({"audio": base64.b64encode(audio).decode("ascii"), "reference": str(reference)}), 90)
                except TimeoutError:
                    raise ValueError("OpenVoice не завершил фразу за 90 секунд. Сократите текст или выберите обычный Piper/Silero") from None
                if cancelled.is_set():
                    raise ValueError("Озвучка остановлена")
                success = True
                return result
            finally:
                session.active_id = None
                if not success or not session_id:
                    await session.close()
                    if self.sessions.get(identity) is session:
                        self.sessions.pop(identity, None)
                else:
                    async def expire():
                        await asyncio.sleep(30)
                        if self.sessions.get(identity) is session and session.active_id is None:
                            await self.close_session(identity)
                    session.idle = asyncio.create_task(expire())
