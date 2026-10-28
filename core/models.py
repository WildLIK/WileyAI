from pathlib import Path
import asyncio
import hashlib
import json
import re
import uuid

from .config import Settings
from .providers import client, describe_error


MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$")
KEEP_FINISHED = 30


class ModelJobs:
    def __init__(self, root: Path):
        self.root = root
        self.jobs: dict[str, dict] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    def start(self, settings: Settings, model: str, path: str | None = None) -> dict:
        if settings.provider != "ollama":
            raise ValueError("Скачивание и импорт доступны через выбранный сервер Ollama")
        if not MODEL_ID.fullmatch(model) or ".." in model:
            raise ValueError("Некорректный идентификатор модели")
        if path and (not Path(path).is_file() or Path(path).suffix.casefold() != ".gguf"):
            raise ValueError("Выберите существующий файл GGUF")
        if path:
            with Path(path).open("rb") as file:
                if file.read(4) != b"GGUF":
                    raise ValueError("Файл не содержит заголовок GGUF")
        for job in self.jobs.values():
            if job["model"] == model and job["status"] in {"queued", "running"}:
                return job
        item = dict(id=uuid.uuid4().hex, model=model, status="queued", detail="В очереди", completed=0, total=0)
        # Keep active jobs and the latest finished ones; the UI shows at most 30.
        finished = [key for key in self.jobs if key not in self.tasks or self.tasks[key].done()]
        for key in finished[:max(0, len(finished) - KEEP_FINISHED)]:
            self.jobs.pop(key)
            self.tasks.pop(key, None)
        self.jobs[item["id"]] = item
        self.tasks[item["id"]] = asyncio.create_task(self.run(settings.model_copy(deep=True), item, path))
        return item

    async def run(self, settings: Settings, item: dict, path: str | None):
        try:
            async with self.lock:
                item.update(status="running", detail="Подключение к Ollama")
                async with client(settings) as http:
                    body = {"model": item["model"], "stream": True}
                    endpoint = "api/pull"
                    if path:
                        item["detail"] = "Проверка локального файла"
                        def digest_file():
                            with Path(path).open("rb") as source:
                                return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
                        digest = await asyncio.to_thread(digest_file)
                        head = await http.head(f"api/blobs/{digest}")
                        if head.status_code == 404:
                            item["detail"] = "Передача файла движку"
                            async def chunks():
                                with Path(path).open("rb") as source:
                                    while chunk := source.read(1024 * 1024):
                                        yield chunk
                            upload = await http.post(f"api/blobs/{digest}", content=chunks())
                            upload.raise_for_status()
                        else:
                            head.raise_for_status()
                        endpoint = "api/create"
                        body["files"] = {Path(path).name: digest}
                    async with http.stream("POST", endpoint, json=body) as response:
                        if response.is_error:
                            detail = bytearray()
                            async for part in response.aiter_bytes(chunk_size=1024):
                                detail.extend(part)
                                if len(detail) >= 8192:
                                    break
                            if b"resolves to non-public" in detail:
                                raise ValueError("Ollama заблокировал адрес хранилища из DNS/VPN. Для загрузки модели нужен real-IP или исключение домена хранилища в VPN. DNS в настройках чтения страниц WileyAI не меняет загрузчик Ollama. Модель не установлена.")
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            update = json.loads(line)
                            if update.get("error"):
                                raise ValueError(update["error"])
                            item.update(detail=update.get("status", "Загрузка"), completed=update.get("completed", 0), total=update.get("total", 0))
                    item.update(status="done", detail="Установлена в Ollama. Выберите модель для общения.")
        except asyncio.CancelledError:
            item.update(status="cancelled", detail="Загрузка остановлена. Повторный запуск использует кеш Ollama.")
        except Exception as error:
            item.update(status="error", detail=describe_error(error))

    def cancel(self, job_id: str):
        task = self.tasks.get(job_id)
        if task and not task.done():
            task.cancel()

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
