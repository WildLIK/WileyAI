from pathlib import Path
from contextlib import contextmanager, ExitStack
import asyncio
import importlib.util
import json
import os
import re
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
from .speech_numbers import silero_numbers
from .qwen import QwenSpeech
from .cloud_speech import CloudSpeech
from .openvoice import OpenVoice, LOCAL_ENGINES
from . import gigaam

# Published Silero checkpoints. A changed file is rejected rather than loaded with torch.
SILERO_SHA256 = {
    "v5_ru": "7ba04d42340fe0398042eed2e0d12d62e23096d626b1b9feff4dcb1309197ab4",
    "v5_6_ru": "04cc9b1d08ce38bcaa9d02c488d80d3e6806d17f7eaa7c95982f36a3cbf50b2e",
}
POWERSHELL = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe") if os.name == "nt" else "powershell.exe"


# Whisper's well-known inventions on noise and music (subtitle credits, outros).
# Only a whole transcript made of them is dropped; real speech never matches.
PHANTOMS = re.compile(
    r"(?:продолжение следует|субтитр\w*(?: (?:сделал|создавал|подготовил\w*|делал))?|редактор субтитров|корректор|"
    r"подписывайтесь(?: на канал)?|подпишись(?: на канал)?|ставьте лайк\w*|"
    r"спасибо за (?:просмотр|внимание)|благодарю за (?:просмотр|внимание)|до (?:новых )?встреч\w*|"
    r"музыка|аплодисменты|смех|dimatorzok|[а-яa-z]\. ?[а-яa-z]+(?:ова|ая|ев|ов)|amara\.org|\W)+",
    re.I,
)


def recognized(text: str, prompt: str) -> str:
    """Drop transcripts that are only a known hallucination or a replay of the prompt."""
    value = text.strip()
    if not value or PHANTOMS.fullmatch(value):
        return ""
    words = re.findall(r"\w+", value.casefold())
    # A long exact copy of the vocabulary prompt is not something the user said.
    if len(words) >= 8 and " ".join(words) in " ".join(re.findall(r"\w+", prompt.casefold())):
        return ""
    return value


def speech_prompt(name: str, vocabulary=()) -> str:
    """Style the prompt like the commands themselves: the name, a comma, an imperative."""
    name = name.strip() or "Уайли"
    base = (f"{name}, прибавь громкость на десять. {name}, убавь громкость. {name}, продолжи музыку. "
            f"{name}, поставь на паузу. {name}, следующий трек. {name}, открой Telegram. "
            f"{name}, напомни через час. {name}, создай заметку. "
            "Яндекс Музыка, Яндекс Браузер, AIMP, Chrome, Firefox.")
    # Only short app names supplied by the local catalog/user; never history.
    extra = [v.strip() for v in vocabulary[:8] if isinstance(v, str) and re.fullmatch(r"[\w .-]{1,60}", v.strip())]
    return (base[:600] + (" Приложения: " + ", ".join(extra) if extra else ""))[:800]


def pcm16k(data: bytes):
    """16 kHz mono PCM16 WAV (what the conversation sends) without ffmpeg or a temp file."""
    if data[:4] != b"RIFF":
        return None
    try:
        import numpy
        with wave.open(io.BytesIO(data)) as source:
            if source.getframerate() != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
                return None
            raw = source.readframes(source.getnframes())
        return numpy.frombuffer(raw, "<i2").astype(numpy.float32) / 32768
    except (ImportError, wave.Error, EOFError):
        return None


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
        self.system_voices = None

    def available(self, model="small"):
        if model == gigaam.MODEL_ID:
            return gigaam.available()
        return importlib.util.find_spec("faster_whisper") is not None

    def stt_installed(self, model):
        if model == gigaam.MODEL_ID:
            return gigaam.installed(self.root)
        return model in {"tiny", "base", "small"} and (self.root / "models/whisper" / model / "model.bin").is_file()

    @contextmanager
    def _using(self, resource):
        # Called under the resource lock. Idle time starts after native work,
        # including a slow cold load, has finished or failed.
        try:
            yield
        finally:
            self.last_used[resource] = self._clock()

    def _load_stt(self, model: str):
        if model == gigaam.MODEL_ID:
            if model not in self.models:
                self.models.clear()
                self.models[model] = gigaam.GigaAM(self.root)
            return
        if not self.available():
            raise ValueError("Установите компонент Whisper в разделе «Модели → Компоненты» и перезапустите WileyAI.")
        from faster_whisper import WhisperModel
        folder = self.root / "models" / "whisper" / model
        if not folder.is_dir() or not (folder / "model.bin").is_file():
            raise ValueError("Сначала скачайте выбранную модель Whisper в разделе «Модели».")
        if model not in self.models:
            self.models.clear()
            # CTranslate2 defaults to 4 threads; physical cores (capped) cut a phrase by about a quarter.
            import psutil
            threads = min(16, psutil.cpu_count(logical=False) or 4)
            self.models[model] = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=threads)

    def transcribe(self, data: bytes, model: str, hint: str = "", quality: str = "accurate", environment: str = "normal", vocabulary=()) -> str:
        with self.lock, self._using("stt"):
            self._load_stt(model)
            if model == gigaam.MODEL_ID:
                return self.models[model].transcribe(data, pcm16k(data), environment)
            # A fixed Russian vocabulary helps short device commands. Never use
            # the previous chat/document as a prompt or rewrite the transcript.
            prompt = speech_prompt(hint, vocabulary)
            options = {"vad_parameters": {"threshold": 0.65, "min_speech_duration_ms": 200, "speech_pad_ms": 250}} if environment == "music" else {}
            audio = pcm16k(data)
            path = None
            if audio is None:  # Recorded webm/ogg: decoded by faster-whisper from a file.
                with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as file:
                    file.write(data)
                    path = file.name
            try:
                segments, _ = self.models[model].transcribe(
                    path or audio, language="ru", vad_filter=True,
                    beam_size={"fast": 1, "balanced": 3, "accurate": 5}.get(quality, 5),
                    temperature=0.0, condition_on_previous_text=False,
                    initial_prompt=prompt, **options)
                # Whisper itself rates a segment as non-speech: noise, breath, music.
                text = " ".join(segment.text.strip() for segment in segments
                                if not (getattr(segment, "no_speech_prob", 0) > 0.7 and getattr(segment, "avg_logprob", 0) < -0.5))
                return recognized(text, prompt)
            finally:
                if path:
                    Path(path).unlink(missing_ok=True)

    def download(self, model: str):
        if model == gigaam.MODEL_ID:
            if not self.available(model):
                raise ValueError("Сначала установите компонент GigaAM ONNX в разделе «Модели → Компоненты» и перезапустите WileyAI.")
            with self.download_lock:
                gigaam.download(self.root)
            return
        if not self.available():
            raise ValueError("Для Whisper сначала установите компонент в разделе «Модели → Компоненты»")
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
            raise ValueError("Сначала установите компонент Silero / Torch CPU в разделе «Модели → Компоненты» и перезапустите WileyAI")
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
            if digest.hexdigest() != SILERO_SHA256[version]:
                raise ValueError("Контрольная сумма Silero не совпала. Повторите загрузку")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)

    def synthesize(self, text: str, speaker: str, cancel=None, engine="silero") -> bytes:
        text = plain_speech(text)
        if engine != "piper": text = silero_numbers(text)
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

    async def voices(self, refresh: bool = False) -> list[dict]:
        """Installed SAPI voices, cached for the process; `refresh` re-reads them after an install."""
        if os.name != "nt":
            return []
        if self.system_voices is not None and not refresh:
            return list(self.system_voices)
        process = await asyncio.create_subprocess_exec(POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; @($s.GetInstalledVoices() | ForEach-Object { @{name=$_.VoiceInfo.Name; language=$_.VoiceInfo.Culture.Name} }) | ConvertTo-Json -Compress", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            out, _ = await asyncio.wait_for(process.communicate(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
            return []
        finally:
            if process.returncode is None:
                process.kill()
        if process.returncode:
            return []
        data = json.loads(out.decode("utf-8-sig") or "[]")
        self.system_voices = data if isinstance(data, list) else [data]
        return list(self.system_voices)

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
                released.extend(gigaam.MODEL_NAME if name == gigaam.MODEL_ID else "Whisper " + name for name in self.models)
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
            self.speech = await asyncio.create_subprocess_exec(POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
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
