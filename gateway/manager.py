"""Account ownership, fresh model discovery and durable, idempotent generation jobs."""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import time
from urllib.parse import urlsplit

from .catalog import catalog
from .protocol import GatewayError, Model, ProviderEvent
from .store import Store, new_id
from .adapters.chatgpt import ChatGPTAdapter
from .adapters.compatible import CompatibleAdapter
from .adapters.testing import TestAdapter

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class ProviderManager:
    def __init__(self, store: Store, *, api_profiles=(), test_mode=False, adapters=None):
        self.store, self.test_mode = store, test_mode
        self.profiles = list(api_profiles)
        self.catalog = catalog(api_profiles, test_mode)
        self.adapters = {"chatgpt": ChatGPTAdapter(store)}
        for profile in api_profiles:
            parsed = urlsplit(profile["endpoint"])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or profile["id"] in self.adapters:
                raise ValueError("Invalid administrator API profile")
            self.adapters[profile["id"]] = CompatibleAdapter(profile["endpoint"])
        if test_mode:
            self.adapters["test-provider"] = TestAdapter()
        if adapters:
            if not test_mode:
                raise ValueError("Injected adapters require test mode")
            self.adapters.update(adapters)
        self.cache = {}
        self.jobs = {}
        self.lock = asyncio.Lock()

    def account(self, owner, identifier):
        account = self.store.get(owner, identifier, "connection")
        return {**account, "owner": owner, "id": identifier}

    def adapter(self, account):
        adapter = self.adapters.get(account["provider_id"])
        if adapter is None:
            raise GatewayError("provider_unsupported", "Этот провайдер пока не имеет разрешённого адаптера.", 422)
        return adapter

    async def connect(self, owner, body):
        service = next((row for row in self.catalog if row["id"] == body.provider_id), None)
        if service is None or not service["available"]:
            raise GatewayError("provider_unsupported", service["description"] if service else "Провайдер не установлен.", 422)
        if not body.consent:
            raise GatewayError("consent_required", "Подтвердите передачу сообщений выбранному провайдеру.", 403)
        if len(self.store.list(owner, "connection")) >= 20:
            raise GatewayError("gateway_limit", "Достигнут предел подключений Gateway.", 429)
        if body.credential and service["category"] != "official_api":
            raise GatewayError("invalid_credential", "Для этого подключения не нужно передавать cookies, пароль или токен вручную.")
        identifier = new_id()
        value = {"provider_id": body.provider_id, "label": body.label.strip() or service["name"],
                 "consent_at": time.time(), "created_at": time.time()}
        self.store.put(owner, identifier, "connection", value)
        if body.credential:
            self.store.put(owner, "api-credential-" + identifier, "api_credential", {"credential": body.credential})
        return {"id": identifier, **value}

    def secret_account(self, account):
        if account["provider_id"] not in {profile["id"] for profile in self.profiles}:
            return account
        try:
            credential = self.store.get(account["owner"], "api-credential-" + account["id"], "api_credential")
        except GatewayError as error:
            if error.status != 404:
                raise
            credential = {}
        return {**account, **credential}

    async def connections(self, owner, probe=False):
        result = []
        for identifier, value in self.store.list(owner, "connection"):
            account = self.secret_account(self.account(owner, identifier))
            try:
                # OAuth status is passive. Optional APIs are probed only on explicit refresh.
                state = await self.adapter(account).status(account) if probe or account["provider_id"] == "chatgpt" or self.test_mode else {"status": "configured"}
            except GatewayError as error:
                state = {"status": error.code}
            result.append({"id": identifier, **value, **state})
        return result

    async def models(self, owner, identifier, refresh=False):
        account = self.secret_account(self.account(owner, identifier))
        key = owner, identifier
        cached = self.cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < 300:
            return cached[1]
        async with asyncio.timeout(40):
            models = await self.adapter(account).models(account)
        self.cache[key] = time.monotonic(), models
        return models

    async def model(self, owner, identifier, model_id):
        model = next((model for model in await self.models(owner, identifier) if model.id == model_id), None)
        if model is None:
            raise GatewayError("model_unavailable", "Выбранная модель не найдена в текущем каталоге аккаунта.", 422)
        return model

    async def disconnect(self, owner, identifier):
        account = self.secret_account(self.account(owner, identifier))
        for (job_owner, run_id), task in list(self.jobs.items()):
            if job_owner == owner and self.store.get(owner, run_id, "run")["connection_id"] == identifier:
                await self.cancel(owner, run_id)
        result = await self.adapter(account).disconnect(account)
        for key, flow in self.store.list(owner, "auth_flow"):
            if flow.get("connection_id") == identifier:
                self.store.delete(owner, key)
        self.store.delete(owner, identifier)
        self.store.delete(owner, "credential-" + identifier)
        self.store.delete(owner, "api-credential-" + identifier)
        self.cache.pop((owner, identifier), None)
        return result

    async def conversation(self, owner, body):
        await self.model(owner, body.connection_id, body.model_id)
        if len(self.store.list(owner, "conversation")) >= 1000:
            raise GatewayError("gateway_limit", "Достигнут предел диалогов Gateway.", 429)
        identifier = new_id()
        value = {"connection_id": body.connection_id, "model_id": body.model_id, "messages": [], "created_at": time.time()}
        self.store.put(owner, identifier, "conversation", value)
        return {"id": identifier, **value}

    async def start(self, owner, conversation_id, body):
        async with self.lock:
            conversation = self.store.get(owner, conversation_id, "conversation")
            model = await self.model(owner, conversation["connection_id"], conversation["model_id"])
            for key in body.options:
                if key not in {"web_search", "reasoning_mode"}:
                    raise GatewayError("capability_unavailable", "Неизвестная или неподдерживаемая настройка запроса.", 422)
            if body.options.get("web_search") and not model.supports("web_search"):
                raise GatewayError("capability_unavailable", "Поиск для этой модели не подтверждён.", 422)
            if body.options.get("reasoning_mode") and body.options["reasoning_mode"] not in model.reasoning_modes:
                raise GatewayError("capability_unavailable", "Этот режим размышления не объявлен моделью.", 422)
            if not body.text.strip() and not body.attachments:
                raise GatewayError("empty_message", "Введите сообщение или выберите вложение.")
            attachments = []
            for identifier in body.attachments:
                value = self.store.get(owner, identifier, "attachment")
                if value["mime"].startswith("image/") and not model.supports("vision"):
                    raise GatewayError("capability_unavailable", "Анализ изображений этой моделью не подтверждён.", 422)
                if not value["mime"].startswith("image/") and not model.supports("file_upload"):
                    raise GatewayError("capability_unavailable", "Загрузка файлов этой моделью не подтверждена.", 422)
                attachments.append(value)
            digest = hashlib.sha256(json.dumps({"conversation": conversation_id, **body.model_dump()}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            identifier = new_id()
            run = {"id": identifier, "conversation_id": conversation_id, "connection_id": conversation["connection_id"], "model_id": model.id,
                   "state": "queued", "text": "", "summary": "", "citations": [], "created_at": time.time(), "error": None}
            identifier, fresh = self.store.reserve(owner, body.request_id, digest, identifier, run)
            if not fresh:
                return self.store.get(owner, identifier, "run")
            if any(key[0] == owner and self.store.get(owner, key[1], "run")["conversation_id"] == conversation_id for key in self.jobs):
                self.store.delete_request(owner, body.request_id, identifier)
                raise GatewayError("conversation_busy", "Предыдущий ответ в этом диалоге ещё не завершён.", 409)
            if sum(key[0] == owner for key in self.jobs) >= 2 or len(self.jobs) >= 8:
                self.store.delete_request(owner, body.request_id, identifier)
                raise GatewayError("gateway_busy", "Gateway уже обрабатывает запросы. Повторите позже.", 429, True)
            if not conversation["messages"]:
                conversation["messages"] = [message.model_dump() for message in body.context]
            conversation["messages"].append({"role": "user", "content": body.text, "attachments": body.attachments})
            self.store.put(owner, conversation_id, "conversation", conversation)
            self.store.event(owner, identifier, {"type": "run.started", "data": {"run_id": identifier}})
            task = asyncio.create_task(self.generate(owner, run, conversation, model, body.options))
            self.jobs[owner, identifier] = task
            return run

    async def generate(self, owner, run, conversation, model, options):
        identifier, conversation_id = run["id"], run["conversation_id"]
        try:
            run["state"] = "running"
            self.store.put(owner, identifier, "run", run)
            account = self.secret_account(self.account(owner, run["connection_id"]))
            messages = []
            for message in conversation["messages"][-32:]:
                content = message["content"]
                if message.get("attachments"):
                    content = [{"type": "input_text", "text": content}]
                    for attachment_id in message["attachments"]:
                        attachment = self.store.get(owner, attachment_id, "attachment")
                        import base64
                        data = attachment["data"]
                        if attachment["mime"].startswith("image/"):
                            content.append({"type": "input_image", "image_url": "data:" + attachment["mime"] + ";base64," + data})
                        else:
                            content.append({"type": "input_file", "filename": attachment["name"], "file_data": "data:" + attachment["mime"] + ";base64," + data})
                messages.append({"role": message["role"], "content": content})
            async with asyncio.timeout(660):
                async for event in self.adapter(account).stream(account, model, messages, options):
                    if event.type not in {"message.delta", "reasoning.summary", "citation.added", "artifact.added", "status"}:
                        raise GatewayError("provider_changed", "Неизвестное событие адаптера. Исполнение остановлено.", 502)
                    if event.type in {"message.delta", "reasoning.summary"}:
                        text = event.data.get("text")
                        if not isinstance(text, str) or len(text) > 128000:
                            raise GatewayError("provider_changed", "Некорректный текст события провайдера.", 502)
                        field = "text" if event.type == "message.delta" else "summary"
                        run[field] += text
                        if len(run["text"]) + len(run["summary"]) > 2 * 1024 * 1024:
                            raise GatewayError("response_limit", "Ответ слишком длинный. Частичный текст сохранён.", 413)
                    elif event.type == "citation.added":
                        parsed = urlsplit(event.data.get("url", ""))
                        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                            continue
                        if len(run["citations"]) < 100:
                            run["citations"].append(event.data)
                    elif event.type == "artifact.added":
                        raise GatewayError("capability_unavailable", "Этот адаптер ещё не подтвердил выдачу медиа. Успех не объявлен.", 422)
                    self.store.event(owner, identifier, {"type": event.type, "data": event.data})
                    self.store.put(owner, identifier, "run", run)
            run["state"] = "completed"
        except asyncio.CancelledError:
            run["state"] = "cancelled"
        except GatewayError as error:
            run["state"] = "failed"
            run["error"] = {"code": error.code, "message": error.message, "retryable": error.retryable}
        except Exception:
            run["state"] = "interrupted"
            run["error"] = {"code": "stream_interrupted", "message": "Ответ прервался. Частичный текст сохранён.", "retryable": False}
        finally:
            if run["text"]:
                conversation["messages"].append({"role": "assistant", "content": run["text"], "citations": run["citations"], "run_id": identifier, "state": run["state"]})
            self.store.put(owner, conversation_id, "conversation", conversation)
            run["finished_at"] = time.time()
            self.store.put(owner, identifier, "run", run)
            self.store.event(owner, identifier, {"type": "run." + run["state"], "data": {"run_id": identifier, "error": run["error"], "citations": run["citations"]}})
            self.jobs.pop((owner, identifier), None)

    async def cancel(self, owner, identifier):
        run = self.store.get(owner, identifier, "run")
        task = self.jobs.get((owner, identifier))
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its first scheduling turn never enters its finally block.
        run = self.store.get(owner, identifier, "run")
        if run["state"] not in TERMINAL:
            run["state"] = "cancelled"
            run["finished_at"] = time.time()
            self.store.put(owner, identifier, "run", run)
            self.store.event(owner, identifier, {"type": "run.cancelled", "data": {"run_id": identifier, "error": None}})
        self.jobs.pop((owner, identifier), None)
        return self.store.get(owner, identifier, "run")

    async def cancel_request(self, owner, request_id):
        async with self.lock:
            identifier = self.store.cancel_request(owner, request_id)
            if identifier:
                return await self.cancel(owner, identifier)
            return {"state": "cancelled", "request_id": request_id}

    def recover(self):
        for owner in self.store.owners():
            for identifier, run in self.store.list(owner, "run"):
                if run["state"] not in TERMINAL:
                    run["state"] = "interrupted"
                    run["error"] = {"code": "server_restarted", "message": "Gateway был перезапущен. Автоматической повторной отправки провайдеру нет.", "retryable": False}
                    self.store.put(owner, identifier, "run", run)
                    if run.get("text") and run.get("conversation_id"):
                        conversation = self.store.get(owner, run["conversation_id"], "conversation")
                        if not any(message.get("run_id") == identifier for message in conversation["messages"]):
                            conversation["messages"].append({"role": "assistant", "content": run["text"], "run_id": identifier,
                                                             "state": "interrupted", "citations": run.get("citations", [])})
                            self.store.put(owner, run["conversation_id"], "conversation", conversation)
                    self.store.event(owner, identifier, {"type": "run.interrupted", "data": {"run_id": identifier, "error": run["error"]}})

    async def close(self):
        for task in tuple(self.jobs.values()):
            task.cancel()
        await asyncio.gather(*tuple(self.jobs.values()), return_exceptions=True)
        for adapter in self.adapters.values():
            await adapter.close()
