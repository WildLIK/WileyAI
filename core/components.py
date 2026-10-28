"""Optional runtimes, installed on demand outside the read-only application."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile

import httpx

PROJECT = Path(__file__).resolve().parents[1]
CATALOG = {
    "ollama": ("Ollama", "Мозг · запуск локальных языковых моделей", None, "около 1,5 ГБ загрузки; до 5 ГБ на диске"),
    "whisper": ("Whisper", "Распознавание голоса", "faster_whisper", "около 500 МБ на диске, без весов модели"),
    "gigaam": ("GigaAM ONNX", "Локальное распознавание русской речи на CPU; без Torch", "onnx_asr", "около 200 МБ на диске; веса около 854 МиБ отдельно"),
    "piper": ("Piper", "Быстрая локальная озвучка", "piper", "около 300 МБ на диске, без голосов"),
    "silero": ("Silero / Torch CPU", "Локальная озвучка и основа OpenVoice", "torch", "около 1,5 ГБ на диске, без голосов"),
    "qwen": ("Qwen3-TTS CPU", "Изолированный движок качественной озвучки; требует много ОЗУ", None, "несколько ГБ; веса скачиваются отдельно"),
}
OLLAMA_VERSION = "v0.40.4"


async def blocking(function, *args):
    """Runs file work off the event loop; a cancel stops it at the next block before cleanup starts."""
    stop = threading.Event()
    task = asyncio.ensure_future(asyncio.to_thread(function, *args, stop))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
        raise


def write_block(digest, output, block, stop):
    if not stop.is_set():
        digest.update(block)
        output.write(block)


def extract_ollama(archive, staging, stop):
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 20000 or sum(item.file_size for item in source.infolist()) > 32 * 1024**3:
            raise ValueError("Некорректный размер архива Ollama")
        for item in source.infolist():
            path = staging / item.filename
            if "\\" in item.filename or ":" in item.filename or not path.resolve().is_relative_to(staging.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Недопустимый путь в архиве Ollama")
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as stream, path.open("wb") as output:
                    while block := stream.read(1024 * 1024):
                        if stop.is_set():
                            return
                        output.write(block)
    archive.unlink()


def component_directory(root, key):
    base = Path(root) / "components" / key
    try:
        marker = json.loads((base / "ready.json").read_text(encoding="utf-8"))
        directory = marker["directory"]
        if re.fullmatch(r"[a-f0-9]{16}", directory) and (base / directory).is_dir():
            return base / directory
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class Components:
    def __init__(self, root, *, transport=None):
        self.root = Path(root)
        self.loaded = {key for key in CATALOG if component_directory(root, key)}
        self.job = None
        self.task = None
        self.process = None
        self.transport = transport

    def status(self):
        items = []
        for key, (name, description, module, size) in CATALOG.items():
            directory = component_directory(self.root, key)
            available = bool(importlib.util.find_spec(module)) if module else False
            if key == "ollama":
                available = bool(directory and (directory / "ollama.exe").is_file()) or (PROJECT / "local/ollama/ollama.exe").is_file()
            elif key == "qwen":
                environment = directory / "venv" if directory else PROJECT / "local/qwen-tts/.venv"
                available = (environment / "Scripts/python.exe").is_file() and (environment / "Lib/site-packages/qwen_tts/__init__.py").is_file()
            items.append({"id": key, "name": name, "description": description, "size": size,
                          "installed": bool(directory or available), "available": available,
                          "restart": bool(directory and key not in self.loaded and module)})
        return {"items": items, "job": self.job}

    def start(self, key):
        if key not in CATALOG:
            raise ValueError("Неизвестный компонент")
        if self.task and not self.task.done():
            raise ValueError("Дождитесь установки текущего компонента или отмените её")
        if next(item for item in self.status()["items"] if item["id"] == key)["installed"]:
            raise ValueError("Компонент уже установлен")
        self.job = {"component": key, "state": "running", "stage": "Подготовка установки", "progress": None}
        self.task = asyncio.create_task(self.install(key))
        return self.status()

    async def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            if self.job and self.job["state"] == "running":
                self.job.update(state="cancelled", stage="Установка отменена", progress=None)
        return self.status()

    async def command(self, *args):
        self.process = await asyncio.create_subprocess_exec(*map(str, args),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env={**os.environ, "UV_NO_PROGRESS": "1", "UV_NO_CONFIG": "1"})
        try:
            # Drain a bounded tail so uv never blocks on a full pipe.
            tail = bytearray()
            while block := await self.process.stderr.read(4096):
                tail.extend(block)
                tail = tail[-16000:]
            if await self.process.wait() != 0:
                raise ValueError("Установка не завершена. Проверьте интернет и свободное место, затем повторите. Диагностика сохранена в журнале компонентов.")
        finally:
            if self.process.returncode is None:
                if os.name == "nt":
                    killer = await asyncio.create_subprocess_exec("taskkill.exe", "/PID", str(self.process.pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    await killer.wait()
                else:
                    self.process.kill()
                await self.process.wait()
            # Only package-manager output; environment and service credentials are never logged.
            if tail:
                log = self.root / "logs/components.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_bytes(tail)
            self.process = None

    async def install(self, key):
        base = self.root / "components" / key
        directory = uuid.uuid4().hex[:16]
        staging = base / (directory + ".partial")
        target = base / directory
        staging.mkdir(parents=True, exist_ok=True)
        try:
            if key == "ollama":
                await self.ollama(staging)
            else:
                uv = os.environ.get("WILEYAI_UV") or shutil.which("uv")
                if not uv:
                    raise ValueError("Не найден встроенный установщик компонентов. Переустановите WileyAI из готового установщика.")
                self.job["stage"] = "Загрузка и установка пакетов; это может занять несколько минут"
                if key == "qwen":
                    environment = staging / "venv"
                    await self.command(uv, "venv", environment, "--python", sys.executable, "--no-project")
                    await self.command(uv, "pip", "install", "--python", environment / "Scripts/python.exe", "--torch-backend", "cpu",
                                       "torch==2.9.1", "torchaudio==2.9.1", "qwen-tts==0.1.1", "huggingface-hub<1")
                    await self.command(environment / "Scripts/python.exe", "-c", "import qwen_tts, torch")
                else:
                    requirements = PROJECT / "requirements" / (key + ".txt")
                    if not requirements.is_file():
                        requirements = PROJECT / "local/packaging/requirements" / (key + ".txt")
                    if not requirements.is_file():
                        raise ValueError("Отсутствует список зависимостей. Для сборки из исходников выполните npm run prepare:runtime.")
                    await self.command(uv, "pip", "install", "--python", sys.executable, "--target", staging / "lib", "-r", requirements,
                                       *(["--torch-backend", "cpu"] if key == "silero" else []))
                    self.job["stage"] = "Проверка установленного компонента"
                    # Probe in an isolated child; the running core remains unchanged.
                    module = CATALOG[key][2]
                    await self.command(sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); __import__(sys.argv[2])", staging / "lib", module)
            staging.replace(target)
            temporary = base / "ready.part"
            temporary.write_text(json.dumps({"directory": directory}), encoding="utf-8")
            temporary.replace(base / "ready.json")
            self.job.update(state="done", stage="Установлено", progress=100)
        except asyncio.CancelledError:
            self.job.update(state="cancelled", stage="Установка отменена", progress=None)
            raise
        except Exception as error:
            self.job.update(state="error", stage=str(error) if isinstance(error, ValueError) else "Не удалось установить компонент. Проверьте интернет и свободное место.", progress=None)
        finally:
            # Only remove this job's own, verified child path, never existing runtimes.
            if staging.parent == base and staging.name == directory + ".partial":
                await asyncio.to_thread(shutil.rmtree, staging, True)

    async def ollama(self, staging):
        url = f"https://github.com/ollama/ollama/releases/download/{OLLAMA_VERSION}/"
        archive = staging / "runtime.zip"
        async with httpx.AsyncClient(transport=self.transport, timeout=90, follow_redirects=True) as client:
            sums = await client.get(url + "sha256sum.txt")
            sums.raise_for_status()
            match = re.search(r"(?m)^([a-fA-F0-9]{64})\s+\*?(?:\./)?ollama-windows-amd64\.zip\s*$", sums.text)
            if not match:
                raise ValueError("Не найдена официальная контрольная сумма Ollama")
            digest = hashlib.sha256()
            received = 0
            self.job["stage"] = "Загрузка Ollama " + OLLAMA_VERSION
            async with client.stream("GET", url + "ollama-windows-amd64.zip") as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", "0"))
                with archive.open("wb") as output:
                    async for block in response.aiter_bytes(1024 * 1024):
                        received += len(block)
                        if received > 8 * 1024**3:
                            raise ValueError("Архив Ollama превышает допустимый размер")
                        await blocking(write_block, digest, output, block)
                        self.job["progress"] = min(90, received / total * 90) if total else None
            if digest.hexdigest().lower() != match[1].lower():
                raise ValueError("Контрольная сумма Ollama не совпала. Повторите загрузку")
        self.job.update(stage="Распаковка Ollama", progress=92)
        await blocking(extract_ollama, archive, staging)
        if not (staging / "ollama.exe").is_file():
            raise ValueError("В архиве нет движка Ollama")
