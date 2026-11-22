"""Explicit model installation; a deadline kills only our inference child."""
import asyncio
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

import httpx
import psutil

REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
FILENAME = "smart-turn-v3.2-cpu.onnx"
SIZE = 8679182
SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"
URL = f"https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/{REVISION}/{FILENAME}"


class SmartTurn:
    def __init__(self, root):
        self.path = Path(root) / "models/smart-turn" / FILENAME
        self.process = None
        self.process_created = None
        self.lock = asyncio.Lock()
        self.installing = False
        self.idle = None

    def status(self):
        available = all(importlib.util.find_spec(name) is not None for name in ("numpy", "onnxruntime"))
        try:
            installed = self.path.is_file() and self.path.stat().st_size == SIZE and self.path.with_suffix(".sha256").is_file() and self.path.with_suffix(".sha256").read_text().strip() == SHA256
        except OSError:
            installed = False
        return {"available": available, "installed": installed, "installing": self.installing, "size": SIZE, "model": "Smart Turn v3.2 CPU", "local": True}

    async def download(self):
        if self.installing: raise ValueError("Загрузка Smart Turn уже идёт")
        self.installing = True
        temporary = self.path.with_suffix(".part")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(); received = 0
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                async with client.stream("GET", URL) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as output:
                        async for block in response.aiter_bytes(65536):
                            received += len(block)
                            if received > SIZE: raise ValueError("Некорректный размер Smart Turn")
                            digest.update(block); output.write(block)
            if received != SIZE or digest.hexdigest() != SHA256: raise ValueError("Контрольная сумма Smart Turn не совпала")
            temporary.replace(self.path)
            self.path.with_suffix(".sha256").write_text(SHA256, encoding="ascii")
        finally:
            self.installing = False
            temporary.unlink(missing_ok=True)
        return self.status()

    async def close(self):
        if self.idle: self.idle.cancel(); self.idle = None
        process, self.process = self.process, None
        created, self.process_created = self.process_created, None
        if process and process.returncode is None:
            # On Windows a venv executable may be a redirector with a Python
            # child. Kill only descendants of the process this manager created.
            try:
                parent = psutil.Process(process.pid)
                if parent.create_time() == created:
                    for child in reversed(parent.children(recursive=True)):
                        try: child.kill()
                        except psutil.NoSuchProcess: pass
            except psutil.Error: pass
            try: process.kill()
            except ProcessLookupError: pass
            await process.wait()

    async def warm(self):
        status = self.status()
        if not status["available"] or not status["installed"]: return False
        if self.process and self.process.returncode is None: return True
        # Check weights before creating an executable inference session.
        if await asyncio.to_thread(lambda: hashlib.sha256(self.path.read_bytes()).hexdigest()) != SHA256: return False
        try:
            environment = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
            self.process = await asyncio.create_subprocess_exec(sys.executable, "-m", "core.smart_turn_worker", str(self.path.resolve()), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=environment, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            process = self.process
            try: self.process_created = psutil.Process(process.pid).create_time()
            except psutil.Error: self.process_created = None
            line = await asyncio.wait_for(process.stdout.readline(), 4)
            if not json.loads(line).get("ready"): raise ValueError("Not ready")
            if self.idle: self.idle.cancel()
            self.idle = asyncio.get_running_loop().call_later(180, lambda: asyncio.create_task(self.close()))
            return True
        except (OSError, ValueError, asyncio.TimeoutError):
            await self.close(); return False

    async def evaluate(self, data):
        # Never queue inference behind another pause or keep an unbounded recording.
        if self.lock.locked(): return {"available": False, "reason": "busy"}
        async with self.lock:
            began = time.perf_counter()
            try:
                with wave.open(io.BytesIO(data)) as source:
                    if source.getframerate() != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getnframes() > 128000: raise ValueError("Ожидается PCM16, 16 кГц, не более 8 секунд")
                    pcm = source.readframes(128000)
                if not await self.warm(): return {"available": False, "reason": "not_installed"}
                process = self.process
                if process is None: return {"available": False, "reason": "released"}
                process.stdin.write(json.dumps({"pcm": base64.b64encode(pcm).decode("ascii")}).encode() + b"\n")
                await process.stdin.drain()
                result = json.loads(await asyncio.wait_for(process.stdout.readline(), .5))
                score = result.get("score")
                if not isinstance(score, (int, float)) or not 0 <= score <= 1: raise ValueError("Некорректный результат Smart Turn")
                if self.idle: self.idle.cancel()
                self.idle = asyncio.get_running_loop().call_later(180, lambda: asyncio.create_task(self.close()))
                return {"available": True, "complete": score > .5, "score": score, "milliseconds": round((time.perf_counter() - began) * 1000, 2)}
            except asyncio.CancelledError:
                await self.close(); raise
            except (OSError, ValueError, asyncio.TimeoutError, EOFError, wave.Error):
                await self.close(); return {"available": False, "reason": "inference_failed"}
