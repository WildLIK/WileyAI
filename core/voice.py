from pathlib import Path
import asyncio
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import io
import wave
import textwrap

import httpx


class Voice:
    def __init__(self, root: Path):
        self.root = root
        self.models: dict = {}
        self.lock = threading.Lock()
        self.speech: asyncio.subprocess.Process | None = None
        self.speak_lock = asyncio.Lock()
        self.tts_lock = threading.Lock()
        self.tts_model = None

    def available(self):
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, data: bytes, model: str) -> str:
        if not self.available():
            raise ValueError("Модуль речи не установлен. Выполните uv sync --extra dev --extra voice и перезапустите WileyAI.")
        from faster_whisper import WhisperModel
        folder = self.root / "models" / "whisper" / model
        if not folder.is_dir() or not (folder / "model.bin").is_file():
            raise ValueError("Сначала скачайте выбранную модель Whisper в разделе «Модели».")
        with self.lock:
            if model not in self.models:
                self.models.clear()
                self.models[model] = WhisperModel(str(folder), device="cpu", compute_type="int8")
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as file:
                file.write(data)
                path = file.name
            try:
                segments, _ = self.models[model].transcribe(path, language="ru", vad_filter=True, beam_size=1)
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

    def tts_installed(self):
        return (self.root / "models" / "silero" / "v5_ru.pt").is_file()

    def download_tts(self):
        if not self.tts_available():
            raise ValueError("Сначала установите модуль озвучки: uv sync --extra dev --extra voice --extra tts")
        target = self.root / "models" / "silero" / "v5_ru.pt"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return
        partial = target.with_suffix(".part")
        with httpx.stream("GET", "https://models.silero.ai/models/tts/ru/v5_ru.pt", timeout=180, follow_redirects=True) as response:
            response.raise_for_status()
            with partial.open("wb") as file:
                for chunk in response.iter_bytes():
                    file.write(chunk)
        partial.replace(target)

    def synthesize(self, text: str, speaker: str) -> bytes:
        if not self.tts_available() or not self.tts_installed():
            raise ValueError("Сначала установите Silero в категории «Озвучка»")
        if speaker not in {"aidar", "baya", "kseniya", "xenia", "eugene", ""}:
            raise ValueError("Неизвестный голос Silero")
        with self.tts_lock:
            import torch
            import numpy as np
            torch.set_num_threads(min(4, os.cpu_count() or 2))
            if self.tts_model is None:
                self.tts_model = torch.package.PackageImporter(str(self.root / "models" / "silero" / "v5_ru.pt")).load_pickle("tts_models", "model")
                self.tts_model.to(torch.device("cpu"))
            parts = textwrap.wrap(text, width=700, break_long_words=False, replace_whitespace=False)
            if not parts:
                raise ValueError("Нет текста для озвучки")
            audio = torch.cat([self.tts_model.apply_tts(text=part, speaker=speaker or "xenia", sample_rate=48000) for part in parts])
            pcm = (np.clip(audio.numpy(), -1, 1) * 32767).astype("<i2").tobytes()
            result = io.BytesIO()
            with wave.open(result, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(48000)
                output.writeframes(pcm)
            return result.getvalue()

    async def voices(self) -> list[dict]:
        if os.name != "nt":
            return []
        process = await asyncio.create_subprocess_exec("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; @($s.GetInstalledVoices() | ForEach-Object { @{name=$_.VoiceInfo.Name; language=$_.VoiceInfo.Culture.Name} }) | ConvertTo-Json -Compress", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        out, _ = await process.communicate()
        if process.returncode:
            return []
        data = json.loads(out.decode("utf-8-sig") or "[]")
        return data if isinstance(data, list) else [data]

    async def stop(self):
        process = self.speech
        self.speech = None
        if process and process.returncode is None:
            process.kill()
            await process.wait()

    async def speak(self, text: str, voice: str):
        if os.name != "nt":
            raise ValueError("Системная озвучка доступна в Windows")
        async with self.speak_lock:
            await self.stop()
            # Script is fixed. Text and voice travel as JSON on stdin, never as shell source.
            script = "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); Add-Type -AssemblyName System.Speech; $p = [Console]::In.ReadToEnd() | ConvertFrom-Json; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; if ($p.voice) { $s.SelectVoice($p.voice) }; $s.Speak([string]$p.text)"
            self.speech = await asyncio.create_subprocess_exec("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            process = self.speech
        _, errors = await process.communicate(json.dumps({"text": text[:5000], "voice": voice}, ensure_ascii=False).encode("utf-8"))
        if process.returncode not in {0, None} and self.speech is process:
            raise ValueError("Не удалось озвучить ответ выбранным голосом")
        if self.speech is process:
            self.speech = None
