"""Optional Qwen speech runs in an isolated, owned process, never in the core."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timezone
from .speech_text import speech_chunks
from .qwen_session import Session, WorkerExited

import httpx


MANIFEST = json.loads(Path(__file__).with_name("qwen_manifest.json").read_text(encoding="utf-8"))
VOICES = [
    {"name": "serena", "language": "Serena · мягкий женский"},
    {"name": "vivian", "language": "Vivian · яркий женский"},
    {"name": "ono_anna", "language": "Anna · лёгкий женский"},
    {"name": "sohee", "language": "Sohee · тёплый женский"},
    {"name": "ryan", "language": "Ryan · мужской"},
    {"name": "aiden", "language": "Aiden · мужской"},
    {"name": "uncle_fu", "language": "Uncle Fu · низкий мужской"},
    {"name": "dylan", "language": "Dylan · мужской"},
    {"name": "eric", "language": "Eric · мужской"},
]


class SpeechAudio(bytes):
    """Keep the existing WAV contract while reporting the device actually used."""
    def __new__(cls, data, device):
        result = super().__new__(cls, data)
        result.device = device
        return result


class QwenSpeech:
    def __init__(self, root: Path):
        self.root = root / "models" / "qwen3-tts"
        self.error_log = root / "logs" / "qwen-error.json"
        self.project = Path(__file__).resolve().parents[1]
        environment = self.project / "local" / "qwen-tts" / ".venv"
        self.python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.package = environment / ("Lib/site-packages/qwen_tts" if os.name == "nt" else "lib/python3.12/site-packages/qwen_tts")
        self.download_lock = threading.Lock()
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.sessions: dict[str, Session] = {}

    def available(self):
        return self.python.is_file() and (self.package / "__init__.py").is_file()

    def installed(self):
        marker = self.root / "installed.json"
        try:
            return json.loads(marker.read_text(encoding="utf-8"))["revision"] == MANIFEST["revision"] and all(
                (self.root / item["path"]).stat().st_size == item["size"] for item in MANIFEST["files"])
        except (OSError, ValueError, KeyError):
            return False

    def prepare(self, speaker=""):
        if not self.available():
            raise ValueError("Подготовьте отдельный движок: npm run setup:qwen. Основное окружение WileyAI менять не нужно")
        if not self.installed():
            raise ValueError("Скачайте Qwen3-TTS 0.6B в разделе «Модели → Озвучка»")
        if speaker and speaker not in {voice["name"] for voice in VOICES}:
            raise ValueError("Выберите голос Qwen3-TTS из списка")

    def download(self):
        with self.download_lock:
            if self.installed():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "installed.json").unlink(missing_ok=True)
            for item in MANIFEST["files"]:
                target = self.root / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file() and target.stat().st_size == item["size"]:
                    with target.open("rb") as source:
                        if hashlib.file_digest(source, "sha256").hexdigest() == item["sha256"]:
                            continue
                partial = target.with_suffix(target.suffix + ".part")
                digest = hashlib.sha256()
                received = 0
                url = f"https://huggingface.co/{MANIFEST['repo']}/resolve/{MANIFEST['revision']}/{item['path']}"
                try:
                    with httpx.stream("GET", url, timeout=180, follow_redirects=True) as response:
                        response.raise_for_status()
                        with partial.open("wb") as output:
                            for chunk in response.iter_bytes(1024 * 1024):
                                received += len(chunk)
                                if received > item["size"]:
                                    raise ValueError("Размер файла Qwen3-TTS превышает ожидаемый")
                                digest.update(chunk)
                                output.write(chunk)
                    if received != item["size"] or digest.hexdigest() != item["sha256"]:
                        raise ValueError("Контрольная сумма Qwen3-TTS не совпала. Повторите загрузку")
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
            marker = self.root / "installed.part"
            marker.write_text(json.dumps({"revision": MANIFEST["revision"]}), encoding="utf-8")
            marker.replace(self.root / "installed.json")

    async def close_session(self, session_id):
        session = self.sessions.pop(session_id, None)
        if session:
            await session.close()

    async def stop(self, request_id=None, preserve_session=None):
        for key, session in list(self.sessions.items()):
            if key != preserve_session and (request_id is None or session.active_id == request_id):
                await self.close_session(key)
        for key, process in list(self.processes.items()):
            if request_id is not None and request_id != key:
                continue
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def render_session(self, text, speaker, device, request_id, cancelled, session_id):
        try:
            return await self._render_session(text, speaker, device, request_id, cancelled, session_id)
        except WorkerExited as error:
            # Windows native libraries can fail once during loading. No audio was
            # returned for this segment, so one restart cannot duplicate speech.
            if error.code not in {3221225477, -1073741819} or cancelled.is_set():
                raise
            return await self._render_session(text, speaker, device, request_id, cancelled, session_id)

    async def _render_session(self, text, speaker, device, request_id, cancelled, session_id):
        self.prepare(speaker)
        session = self.sessions.get(session_id)
        if session and (session.device != device or session.closed or (session.process and session.process.returncode is not None)):
            await self.close_session(session_id)
            session = None
        if session is None:
            session = Session(device)
            self.sessions[session_id] = session
        if session.idle:
            session.idle.cancel()
        async with session.lock:
            success = False
            session.active_id = request_id
            session.texts.append(text)
            try:
                if cancelled.is_set() or session.closed:
                    raise ValueError("Озвучка остановлена")
                if session.process is None:
                    session.process = await asyncio.create_subprocess_exec(
                        str(self.python), "-m", "core.qwen_worker", "--model", str(self.root), "--device", device, "--session",
                        cwd=str(self.project), env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8", "TOKENIZERS_PARALLELISM": "false"},
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    session.drain = asyncio.create_task(session.diagnostics())
                self.processes[request_id] = session.process
                if cancelled.is_set() or session.closed:
                    raise ValueError("Озвучка остановлена")
                try:
                    audio, actual_device = await asyncio.wait_for(session.exchange({"text": text, "speaker": speaker or "serena"}), timeout=300)
                except TimeoutError as error:
                    raise ValueError("Qwen3-TTS не завершил озвучку за 5 минут. Сократите текст или выберите другой движок") from error
                if cancelled.is_set():
                    raise ValueError("Озвучка остановлена")
                success = True
                return SpeechAudio(audio, actual_device)
            except Exception:
                await session.close()
                errors = bytes(session.errors).decode("utf-8", errors="replace")
                for spoken in session.texts:
                    for fragment in [spoken, *speech_chunks(spoken)]:
                        errors = errors.replace(fragment, "[текст скрыт]")
                self.write_diagnostic(errors.encode("utf-8"), text, device, session.process.returncode if session.process else None)
                raise
            finally:
                self.processes.pop(request_id, None)
                session.active_id = None
                if not success:
                    await session.close()
                    if self.sessions.get(session_id) is session:
                        self.sessions.pop(session_id, None)
                else:
                    async def expire():
                        await asyncio.sleep(30)
                        if self.sessions.get(session_id) is session and session.active_id is None:
                            await self.close_session(session_id)
                    session.idle = asyncio.create_task(expire())

    def write_diagnostic(self, errors, text, device, code):
        diagnostic = errors.decode("utf-8", errors="replace").replace(text, "[текст скрыт]")
        for fragment in speech_chunks(text):
            diagnostic = diagnostic.replace(fragment, "[текст скрыт]")
        try:
            self.error_log.parent.mkdir(parents=True, exist_ok=True)
            self.error_log.write_text(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "exit_code": code,
                "device": device, "stderr": diagnostic[-16000:]}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    async def render(self, text, speaker, device, request_id, cancelled):
        self.prepare(speaker)
        if cancelled.is_set():
            raise ValueError("Озвучка остановлена")
        environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8", "TOKENIZERS_PARALLELISM": "false"}
        process = await asyncio.create_subprocess_exec(
            str(self.python), "-m", "core.qwen_worker", "--model", str(self.root), "--device", device,
            cwd=str(self.project), env=environment, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.processes[request_id] = process
        try:
            if cancelled.is_set():
                raise ValueError("Озвучка остановлена")
            payload = json.dumps({"text": text, "speaker": speaker or "serena"}, ensure_ascii=False).encode("utf-8")
            try:
                audio, errors = await asyncio.wait_for(process.communicate(payload), timeout=300)
            except TimeoutError as error:
                raise ValueError("Qwen3-TTS не завершил озвучку за 5 минут. Сократите текст или выберите другой движок") from error
            if cancelled.is_set():
                raise ValueError("Озвучка остановлена")
            if process.returncode:
                message = errors.decode("utf-8", errors="replace")
                diagnostic = message.replace(text, "[текст скрыт]")
                for fragment in speech_chunks(text):
                    diagnostic = diagnostic.replace(fragment, "[текст скрыт]")
                try:
                    self.error_log.parent.mkdir(parents=True, exist_ok=True)
                    self.error_log.write_text(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "exit_code": process.returncode,
                        "device": device, "stderr": diagnostic[-16000:]}, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    pass
                # Extract the marked user-facing error, excluding dependency diagnostics.
                for line in reversed(message.splitlines()):
                    if line.startswith("WILEY_ERROR:"):
                        raise ValueError(line.removeprefix("WILEY_ERROR:")[:300])
                raise ValueError(f"Qwen3-TTS завершился с кодом {process.returncode}. Подробности: logs/qwen-error.json в папке данных WileyAI")
            if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE" or len(audio) > 64 * 1024 * 1024:
                raise ValueError("Qwen3-TTS не вернул корректный WAV")
            actual_device = ""
            for line in errors.decode("utf-8", errors="replace").splitlines():
                if line in {"WILEY_DEVICE:cpu", "WILEY_DEVICE:cuda"}:
                    actual_device = line.removeprefix("WILEY_DEVICE:")
            return SpeechAudio(audio, actual_device)
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            self.processes.pop(request_id, None)
