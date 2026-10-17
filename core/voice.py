from pathlib import Path
from contextlib import contextmanager, ExitStack
import asyncio
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import io
import wave
import time
import uuid
import hashlib
import gc

import httpx
from .piper import Piper
from .speech_text import plain_speech, speech_chunks
from .qwen import QwenSpeech
from .cloud_speech import CloudSpeech
from .openvoice import OpenVoice, LOCAL_ENGINES


class SpeechCancelled(ValueError):
    pass


def check_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise SpeechCancelled("Озвучка остановлена")


class Voice:
    def __init__(self, root: Path, *, clock=time.monotonic):
        self.root = root
        self._clock = clock
        self.last_used = dict.fromkeys(("stt", "silero", "piper"), clock())
        self.models: dict = {}
        self.prepare_lock = threading.Lock()
        self.lock = threading.Lock()
        self.speech: asyncio.subprocess.Process | None = None
        self.speak_lock = asyncio.Lock()
        self.tts_lock = threading.Lock()
        self.tts_model = None
        self.tts_version = ""
        self.piper = Piper(root)
        self.qwen = QwenSpeech(root)
        self.cloud = CloudSpeech(root)
        self.openvoice = OpenVoice(root)
        self.synthesis_jobs: dict[str, threading.Event] = {}
        self.stopped: dict[str, float] = {}
        self.speech_id = None
        self.download_lock = threading.Lock()
        self.render_lock = asyncio.Lock()
        self.monitor = None

    def available(self):
        return importlib.util.find_spec("faster_whisper") is not None

    @contextmanager
    def _using(self, resource):
        # Called under the resource lock. Idle time starts after native work,
        # including a slow cold load, has finished or failed.
        try:
            yield
        finally:
            self.last_used[resource] = self._clock()

    def _load_stt(self, model: str):
        if not self.available():
            raise ValueError("Модуль речи не установлен. Выполните uv sync --extra dev --extra voice и перезапустите WileyAI.")
        from faster_whisper import WhisperModel
        folder = self.root / "models" / "whisper" / model
        if not folder.is_dir() or not (folder / "model.bin").is_file():
            raise ValueError("Сначала скачайте выбранную модель Whisper в разделе «Модели».")
        if model not in self.models:
            self.models.clear()
            self.models[model] = WhisperModel(str(folder), device="cpu", compute_type="int8")

    def transcribe(self, data: bytes, model: str, hint: str = "") -> str:
        with self.lock, self._using("stt"):
            self._load_stt(model)
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as file:
                file.write(data)
                path = file.name
            try:
                segments, _ = self.models[model].transcribe(path, language="ru", vad_filter=True, beam_size=1, initial_prompt=hint[:200] or None)
                return " ".join(segment.text.strip() for segment in segments).strip()
            finally:
                Path(path).unlink(missing_ok=True)

    def download(self, model: str):
        if not self.available():
            raise ValueError("Для Whisper сначала установите модуль: uv sync --extra dev --extra voice")
        from faster_whisper.utils import download_model
        folder = self.root / "models" / "whisper" / model
        download_model(model, output_dir=str(folder))

    def tts_available(self):
        return importlib.util.find_spec("torch") is not None

    def tts_installed(self, version="v5_ru"):
        return (self.root / "models" / "silero" / f"{version}.pt").is_file()

    def _load_tts(self, version="v5_ru"):
        if not self.tts_available() or not self.tts_installed(version):
            raise ValueError("Сначала установите Silero в категории «Озвучка»")
        import torch
        if self.tts_model is None or self.tts_version != version:
            torch.set_num_threads(min(4, os.cpu_count() or 2))
            self.tts_model = torch.package.PackageImporter(str(self.root / "models" / "silero" / f"{version}.pt")).load_pickle("tts_models", "model")
            self.tts_model.to(torch.device("cpu"))
            self.tts_version = version

    def prepare(self, model: str, tts_engine: str, speaker: str = ""):
        with self.prepare_lock:
            self._prepare(model, tts_engine, speaker)
            with self.lock, self.tts_lock:
                ready = self._clock()
                self.last_used["stt"] = ready
                if tts_engine in {"piper", "silero", "silero_v5_6"}:
                    self.last_used["piper" if tts_engine == "piper" else "silero"] = ready

    def _prepare(self, model: str, tts_engine: str, speaker: str):
        # Load without speaking, recording, downloading weights, or generating a message.
        version = "v5_6_ru" if tts_engine == "silero_v5_6" else "v5_ru"
        if tts_engine.startswith("silero") and (not self.tts_available() or not self.tts_installed(version)):
            raise ValueError("Сначала установите Silero в категории «Озвучка»")
        if tts_engine == "qwen3":
            self.qwen.prepare(speaker)
        with self.lock, self._using("stt"):
            self._load_stt(model)
        if tts_engine.startswith("silero"):
            with self.tts_lock, self._using("silero"):
                self._load_tts(version)
        elif tts_engine == "piper":
            with self.tts_lock, self._using("piper"):
                self.piper.load(speaker)

    def download_tts(self, version="v5_ru"):
        if version not in {"v5_ru", "v5_6_ru"}:
            raise ValueError("Неизвестная версия Silero")
        if not self.tts_available():
            raise ValueError("Сначала установите модуль озвучки: uv sync --extra dev --extra voice --extra tts")
        with self.download_lock:
            self._download_tts(version)

    def _download_tts(self, version):
        target = self.root / "models" / "silero" / f"{version}.pt"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return
        partial = target.with_suffix(".part")
        try:
            digest = hashlib.sha256()
            size = 0
            with httpx.stream("GET", f"https://models.silero.ai/models/tts/ru/{version}.pt", timeout=180, follow_redirects=True) as response:
                response.raise_for_status()
                with partial.open("wb") as file:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 200_000_000:
                            raise ValueError("Файл Silero превышает ожидаемый размер")
                        digest.update(chunk)
                        file.write(chunk)
            if version == "v5_6_ru" and digest.hexdigest() != "04cc9b1d08ce38bcaa9d02c488d80d3e6806d17f7eaa7c95982f36a3cbf50b2e":
                raise ValueError("Контрольная сумма Silero не совпала. Повторите загрузку")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)

    def synthesize(self, text: str, speaker: str, cancel=None, engine="silero") -> bytes:
        text = plain_speech(text)
        version = "v5_6_ru" if engine == "silero_v5_6" else "v5_ru"
        if engine != "piper" and (not self.tts_available() or not self.tts_installed(version)):
            raise ValueError("Сначала установите Silero в категории «Озвучка»")
        if engine != "piper" and speaker not in {"aidar", "baya", "kseniya", "xenia", "eugene", ""}:
            raise ValueError("Неизвестный голос Silero")
        # A cancelled request must not wait behind a long synthesis or generate more chunks.
        while not self.tts_lock.acquire(timeout=0.05):
            check_cancelled(cancel)
        try:
            check_cancelled(cancel)
            if engine == "piper":
                model = self.piper.load(speaker)
            else:
                self._load_tts(version)
            parts = speech_chunks(text)
            if not parts:
                raise ValueError("Нет текста для озвучки")
            pcm_parts = []
            rate = 48000
            for part in parts:
                check_cancelled(cancel)
                if engine == "piper":
                    for chunk in model.synthesize(part):
                        check_cancelled(cancel)
                        rate = chunk.sample_rate
                        pcm_parts.append(chunk.audio_int16_bytes)
                else:
                    import numpy as np
                    audio = self.tts_model.apply_tts(text=part, speaker=speaker or "xenia", sample_rate=48000)
                    pcm_parts.append((np.clip(audio.numpy(), -1, 1) * 32767).astype("<i2").tobytes())
            check_cancelled(cancel)
            result = io.BytesIO()
            with wave.open(result, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(b"".join(pcm_parts))
            return result.getvalue()
        finally:
            self.last_used["piper" if engine == "piper" else "silero"] = self._clock()
            self.tts_lock.release()

    async def voices(self) -> list[dict]:
        if os.name != "nt":
            return []
        process = await asyncio.create_subprocess_exec("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; @($s.GetInstalledVoices() | ForEach-Object { @{name=$_.VoiceInfo.Name; language=$_.VoiceInfo.Culture.Name} }) | ConvertTo-Json -Compress", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        out, _ = await process.communicate()
        if process.returncode:
            return []
        data = json.loads(out.decode("utf-8-sig") or "[]")
        return data if isinstance(data, list) else [data]

    async def stop(self, request_id: str | None = None, preserve_session: str | None = None):
        await self.cloud.stop(request_id)
        await self.openvoice.stop(request_id, preserve_session)
        self.stopped = {key: when for key, when in self.stopped.items() if time.monotonic() - when < 30}
        if request_id:
            self.stopped[request_id] = time.monotonic()
            if len(self.stopped) > 128:
                self.stopped.pop(next(iter(self.stopped)))
        for key, event in list(self.synthesis_jobs.items()):
            if request_id is None or request_id == key:
                event.set()
        if preserve_session:
            await self.qwen.stop(request_id, preserve_session=preserve_session)
        else:
            await self.qwen.stop(request_id)
        if request_id is not None and self.speech_id != request_id:
            return
        process = self.speech
        self.speech = None
        if process and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    def _release_local_models(self, idle_seconds=None):
        # Native preparation spans several locks. Do not release the first
        # model while a second one is still loading for the same conversation.
        with ExitStack() as held:
            for lock in (self.prepare_lock, self.lock, self.tts_lock):
                if not lock.acquire(blocking=False):
                    return None
                held.callback(lock.release)
            now = self._clock()
            expired = lambda key: idle_seconds is None or now - self.last_used[key] >= idle_seconds
            released = []
            if expired("stt"):
                released.extend("Whisper " + name for name in self.models)
                self.models.clear()
            if self.tts_model is not None and expired("silero"):
                released.append("Silero 5.6" if self.tts_version == "v5_6_ru" else "Silero 5")
                self.tts_model = None
                self.tts_version = ""
            if self.piper.model is not None and expired("piper"):
                released.append("Piper")
                self.piper.model = None
                self.piper.selected = ""
            return released

    async def unload(self, *, idle_seconds=None):
        async with self.render_lock:
            if self.synthesis_jobs or (self.speech and self.speech.returncode is None):
                return None
            if self.qwen.processes or any(session.active_id for session in [*self.qwen.sessions.values(), *self.openvoice.sessions.values()]):
                return None
            released = await asyncio.to_thread(self._release_local_models, idle_seconds)
            if released is None:
                return None
            # Qwen/OpenVoice have their own answer-session lifecycle. The idle
            # preference controls resident CPU models; explicit unload covers all.
            if idle_seconds is None:
                if self.qwen.sessions:
                    released.append("Qwen3-TTS")
                if self.openvoice.sessions:
                    released.append("OpenVoice")
                await self.qwen.stop()
                await self.openvoice.stop()
            if released:
                await asyncio.to_thread(gc.collect)
            return released

    async def render(self, text: str, voice: str, engine: str, request_id: str | None = None, device: str = "auto", session_id: str | None = None, cloud_config=None, openvoice_voice=None) -> bytes:
        request_id = request_id or uuid.uuid4().hex
        if request_id in self.synthesis_jobs:
            raise ValueError("Озвучка с таким идентификатором уже выполняется")
        if time.monotonic() - self.stopped.get(request_id, -100) < 30:
            raise SpeechCancelled("Озвучка остановлена")
        async with self.render_lock:
            if request_id in self.synthesis_jobs:
                raise ValueError("Озвучка с таким идентификатором уже выполняется")
            if time.monotonic() - self.stopped.get(request_id, -100) < 30:
                raise SpeechCancelled("Озвучка остановлена")
            if session_id:
                await self.stop(preserve_session=session_id)
            else:
                await self.stop()
            if time.monotonic() - self.stopped.get(request_id, -100) < 30:
                raise SpeechCancelled("Озвучка остановлена")
            cancel = threading.Event()
            self.synthesis_jobs[request_id] = cancel
        try:
            if engine == "cloud":
                if cloud_config is None:
                    raise ValueError("Не указаны настройки облачной озвучки")
                return await self.cloud.render(text, cloud_config, request_id)
            if engine == "qwen3":
                if session_id:
                    return await self.qwen.render_session(plain_speech(text), voice, device, request_id, cancel, session_id)
                return await self.qwen.render(plain_speech(text), voice, device, request_id, cancel)
            if engine == "sapi":
                return await self._sapi(text, voice, render=True, request_id=request_id, cancel=cancel)
            if openvoice_voice is not None:
                if engine not in LOCAL_ENGINES:
                    raise ValueError("OpenVoice поддерживает основу Piper и Silero")
                self.openvoice.validate(openvoice_voice)
            if self.monitor:
                audio = await asyncio.to_thread(self.monitor.call, "tts:" + engine, self.synthesize, text, voice, cancel, engine)
            else:
                audio = await asyncio.to_thread(self.synthesize, text, voice, cancel, engine)
            check_cancelled(cancel)
            if openvoice_voice is not None:
                if self.monitor:
                    with self.monitor.activity("tts:openvoice"):
                        return await self.openvoice.render(audio, openvoice_voice, request_id, cancel, session_id)
                return await self.openvoice.render(audio, openvoice_voice, request_id, cancel, session_id)
            return audio
        finally:
            cancel.set()
            self.synthesis_jobs.pop(request_id, None)

    async def speak(self, text: str, voice: str):
        await self.stop()
        await self._sapi(text, voice, render=False)

    async def _sapi(self, text: str, voice: str, render: bool, request_id=None, cancel=None) -> bytes:
        text = plain_speech(text)
        if os.name != "nt":
            raise ValueError("Системная озвучка доступна в Windows")
        async with self.speak_lock:
            check_cancelled(cancel)
            # Script is fixed. Text and voice travel as JSON on stdin, never as shell source.
            script = """
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Speech
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ms = $null
try {
    if ($p.voice) { $s.SelectVoice([string]$p.voice) }
    if ($p.render) {
        $ms = New-Object System.IO.MemoryStream
        $s.SetOutputToWaveStream($ms)
    }
    $s.Speak([string]$p.text)
    if ($p.render) {
        $s.SetOutputToNull()
        $buffer = $ms.ToArray()
        [Console]::OpenStandardOutput().Write($buffer, 0, $buffer.Length)
    }
} finally {
    $s.Dispose()
    if ($ms) { $ms.Dispose() }
}
"""
            self.speech = await asyncio.create_subprocess_exec("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            process = self.speech
            self.speech_id = request_id
        try:
            check_cancelled(cancel)
            audio, _ = await process.communicate(json.dumps({"text": text, "voice": voice, "render": render}, ensure_ascii=False).encode("utf-8"))
            if self.speech is not process:
                raise ValueError("Озвучка остановлена")
            if process.returncode:
                raise ValueError("Не удалось озвучить ответ выбранным голосом")
            if render and not audio.startswith(b"RIFF"):
                raise ValueError("Системный голос не вернул аудиозапись")
            return audio
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            if self.speech is process:
                self.speech = None
