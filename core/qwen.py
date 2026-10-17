"""Optional Qwen speech runs in an isolated, owned process, never in the core."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

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


class QwenSpeech:
    def __init__(self, root: Path):
        self.root = root / "models" / "qwen3-tts"
        self.project = Path(__file__).resolve().parents[1]
        environment = self.project / "local" / "qwen-tts" / ".venv"
        self.python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.package = environment / ("Lib/site-packages/qwen_tts" if os.name == "nt" else "lib/python3.12/site-packages/qwen_tts")
        self.download_lock = threading.Lock()
        self.processes: dict[str, asyncio.subprocess.Process] = {}

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

    async def stop(self, request_id=None):
        for key, process in list(self.processes.items()):
            if request_id is not None and request_id != key:
                continue
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

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
                # Extract the marked user-facing error, excluding dependency diagnostics.
                for line in reversed(message.splitlines()):
                    if line.startswith("WILEY_ERROR:"):
                        raise ValueError(line.removeprefix("WILEY_ERROR:")[:300])
                raise ValueError("Движок Qwen3-TTS завершился с ошибкой. Проверьте установку и свободную память")
            if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE" or len(audio) > 64 * 1024 * 1024:
                raise ValueError("Qwen3-TTS не вернул корректный WAV")
            return audio
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            self.processes.pop(request_id, None)
