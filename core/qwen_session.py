"""A framed pipe protocol reuses one owned Qwen model for an answer's sentences."""
import asyncio
import json


class WorkerExited(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Qwen3-TTS завершился с кодом {code}. Подробности: logs/qwen-error.json в папке данных WileyAI")


class Session:
    def __init__(self, device):
        self.device = device
        self.process = None
        self.closed = False
        self.active_id = None
        self.lock = asyncio.Lock()
        self.idle = None
        self.drain = None
        self.errors = bytearray()
        self.texts = []

    async def diagnostics(self):
        while chunk := await self.process.stderr.read(4096):
            self.errors.extend(chunk)
            del self.errors[:-16000]

    async def exchange(self, payload):
        process = self.process
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        await process.stdin.drain()
        line = await process.stdout.readline()
        if not line:
            await process.wait()
            if self.drain:
                await self.drain
            for message in reversed(self.errors.decode("utf-8", errors="replace").splitlines()):
                if message.startswith("WILEY_ERROR:"):
                    raise ValueError(message.removeprefix("WILEY_ERROR:")[:300])
            raise WorkerExited(process.returncode)
        try:
            header = json.loads(line)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Qwen3-TTS не вернул корректный WAV") from error
        if not isinstance(header, dict):
            raise ValueError("Qwen3-TTS не вернул корректный WAV")
        if header.get("error"):
            raise ValueError(str(header["error"])[:300])
        size = header.get("size")
        if not isinstance(size, int) or not 44 <= size <= 64 * 1024 * 1024:
            raise ValueError("Qwen3-TTS не вернул корректный WAV")
        audio = await process.stdout.readexactly(size)
        if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
            raise ValueError("Qwen3-TTS не вернул корректный WAV")
        return audio, header.get("device", "")

    async def close(self):
        self.closed = True
        if self.idle and self.idle is not asyncio.current_task():
            self.idle.cancel()
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
            await self.process.wait()
        if self.drain:
            await self.drain
