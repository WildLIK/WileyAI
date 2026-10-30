"""Standalone public-facing API behind TLS. It never proxies the desktop API."""
import asyncio
import base64
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from . import VERSION
from .manager import ProviderManager, TERMINAL
from .protocol import AuthComplete, AuthStart, ConnectBody, ConversationBody, GatewayError, PROTOCOL_VERSION, RunBody, StrictBody
from .store import Store, new_id


def error_response(code, message, status, retryable=False):
    return JSONResponse({"error": {"code": code, "message": message, "retryable": retryable}}, status_code=status)


class ClientBody(StrictBody):
    label: str = Field(default="Android", min_length=1, max_length=80)


class ForkBody(StrictBody):
    before_message: int = Field(ge=0, le=10000)


def create_app(directory: Path, key: bytes, *, test_mode=False, development=False, api_profiles=(), adapters=None, store=None):
    store = store or Store(Path(directory), key)
    manager = ProviderManager(store, api_profiles=api_profiles, test_mode=test_mode, adapters=adapters)

    @asynccontextmanager
    async def lifespan(app):
        manager.recover()
        yield
        await manager.close()
        store.close()

    app = FastAPI(title="WileyAI Gateway", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.manager = store, manager
    rate = defaultdict(deque)

    @app.middleware("http")
    async def security(request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if not development and request.url.scheme != "https":
            return error_response("https_required", "Gateway принимает клиентские подключения только через HTTPS.", 400)
        if request.headers.get("origin"):
            # No cookie authentication and no cross-origin browser administration.
            return error_response("origin_rejected", "Используйте приложение WileyAI или авторизованный клиент Gateway.", 403)
        authorization = request.headers.get("authorization", "")
        try:
            owner, role = store.authenticate(authorization[7:] if authorization.startswith("Bearer ") else "")
        except GatewayError as error:
            return error_response(error.code, error.message, error.status)
        request.state.owner, request.state.role = owner, role
        now = time.monotonic()
        recent = rate[owner]
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(recent) >= 180:
            return error_response("gateway_rate_limited", "Слишком много запросов к Gateway. Повторите позже.", 429, True)
        recent.append(now)
        limit = 10 * 1024 * 1024 if request.url.path == "/api/v1/attachments" else 256 * 1024
        try:
            length = int(request.headers.get("content-length", "0"))
            if length < 0 or length > limit:
                return error_response("request_too_large", "Размер запроса превышает ограничение Gateway.", 413)
            parts, size = [], 0
            async for part in request.stream():
                size += len(part)
                if size > limit:
                    return error_response("request_too_large", "Размер запроса превышает ограничение Gateway.", 413)
                parts.append(part)
            request._body = b"".join(parts)
        except (ValueError, RuntimeError):
            return error_response("invalid_request", "Некорректный запрос Gateway.", 400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error(request, error):
        return error_response(error.code, error.message, error.status, error.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Default pydantic error bodies may echo credential fields.
        return error_response("invalid_request", "Запрос не соответствует протоколу Gateway.", 422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return error_response("server_error", "Ошибка Gateway. Секреты и текст запроса в диагностический ответ не включены.", 500)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/info")
    async def info(request: Request):
        return {"protocol": PROTOCOL_VERSION, "version": VERSION, "test_mode": test_mode, "owner_id": request.state.owner,
                "transports": ["sse"], "max_attachment_bytes": 10 * 1024 * 1024, "max_attachments": 5,
                "automatic_fallback": False, "provider_credentials_on_server": True}

    @app.post("/api/v1/clients")
    async def client(request: Request, body: ClientBody):
        if request.state.role != "admin":
            raise GatewayError("forbidden", "Для выпуска клиентского токена нужен администратор Gateway.", 403)
        return {"token": store.token(request.state.owner, "client", body.label), "role": "client"}

    @app.delete("/api/v1/client-session")
    async def revoke_client(request: Request):
        store.revoke(request.state.owner, request.headers["authorization"][7:])
        return {"revoked": True}

    @app.get("/api/v1/providers")
    async def providers():
        return {"providers": manager.catalog}

    @app.get("/api/v1/connections")
    async def connections(request: Request, refresh: bool = False):
        return {"connections": await manager.connections(request.state.owner, refresh)}

    @app.post("/api/v1/connections")
    async def connect(request: Request, body: ConnectBody):
        return await manager.connect(request.state.owner, body)

    @app.delete("/api/v1/connections/{identifier}")
    async def disconnect(request: Request, identifier: str):
        return await manager.disconnect(request.state.owner, identifier)

    @app.get("/api/v1/connections/{identifier}/models")
    async def models(request: Request, identifier: str, refresh: bool = False):
        values = await manager.models(request.state.owner, identifier, refresh)
        return {"models": [value.model_dump() for value in values], "observed_at": time.time(), "cache_seconds": 300}

    @app.post("/api/v1/connections/{identifier}/auth/start")
    async def auth_start(request: Request, identifier: str, body: AuthStart):
        account = manager.account(request.state.owner, identifier)
        adapter = manager.adapter(account)
        if not hasattr(adapter, "start_auth"):
            raise GatewayError("auth_unavailable", "Это подключение не поддерживает данный способ входа.", 422)
        return await adapter.start_auth(account, body.redirect_uri)

    @app.post("/api/v1/connections/{identifier}/auth/complete")
    async def auth_complete(request: Request, identifier: str, body: AuthComplete):
        account = manager.account(request.state.owner, identifier)
        adapter = manager.adapter(account)
        if not hasattr(adapter, "complete_auth"):
            raise GatewayError("auth_unavailable", "Этот способ входа недоступен.", 422)
        result = await adapter.complete_auth(account, body)
        manager.cache.pop((request.state.owner, identifier), None)
        return result

    @app.get("/api/v1/conversations")
    async def conversations(request: Request):
        return {"conversations": [{"id": identifier, "connection_id": value["connection_id"], "model_id": value["model_id"],
                                   "created_at": value["created_at"], "message_count": len(value["messages"])}
                                  for identifier, value in store.list(request.state.owner, "conversation")]}

    @app.post("/api/v1/conversations")
    async def conversation(request: Request, body: ConversationBody):
        return await manager.conversation(request.state.owner, body)

    @app.get("/api/v1/conversations/{identifier}")
    async def history(request: Request, identifier: str, limit: int = 50, before: int | None = None):
        value = store.get(request.state.owner, identifier, "conversation")
        total = len(value["messages"])
        end = total if before is None else before
        if not 0 <= limit <= 200 or not 0 <= end <= total:
            raise GatewayError("invalid_cursor", "Некорректная позиция истории.")
        start = max(0, end - limit)
        return {"id": identifier, **value, "messages": value["messages"][start:end], "message_count": total,
                "next_before": start if start else None}

    @app.post("/api/v1/conversations/{identifier}/fork")
    async def fork(request: Request, identifier: str, body: ForkBody):
        old = store.get(request.state.owner, identifier, "conversation")
        if body.before_message > len(old["messages"]):
            raise GatewayError("invalid_request", "Позиция сообщения вне диалога.")
        value = await manager.conversation(request.state.owner, ConversationBody(connection_id=old["connection_id"], model_id=old["model_id"]))
        data = {key: item for key, item in value.items() if key != "id"}
        data["messages"] = old["messages"][:body.before_message]
        data["parent_id"] = identifier
        store.put(request.state.owner, value["id"], "conversation", data)
        return {"id": value["id"], **data}

    @app.delete("/api/v1/conversations/{identifier}")
    async def delete_conversation(request: Request, identifier: str):
        store.get(request.state.owner, identifier, "conversation")
        for run_id, run in store.list(request.state.owner, "run"):
            if run["conversation_id"] == identifier:
                await manager.cancel(request.state.owner, run_id)
                store.delete(request.state.owner, run_id)
        store.delete(request.state.owner, identifier)
        return {"deleted": True}

    @app.post("/api/v1/conversations/{identifier}/runs")
    async def start_run(request: Request, identifier: str, body: RunBody):
        return await manager.start(request.state.owner, identifier, body)

    @app.get("/api/v1/runs/{identifier}")
    async def run_state(request: Request, identifier: str):
        return store.get(request.state.owner, identifier, "run")

    @app.post("/api/v1/runs/{identifier}/cancel")
    async def cancel(request: Request, identifier: str):
        return await manager.cancel(request.state.owner, identifier)

    @app.post("/api/v1/requests/{identifier}/cancel")
    async def cancel_request(request: Request, identifier: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", identifier):
            raise GatewayError("invalid_request", "Некорректный идентификатор запроса.")
        return await manager.cancel_request(request.state.owner, identifier)

    @app.get("/api/v1/runs/{identifier}/events")
    async def events(request: Request, identifier: str, after: int = 0):
        owner = request.state.owner
        store.get(owner, identifier, "run")
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
            if cursor < 0 or cursor > 1000000:
                raise ValueError()
        except ValueError:
            raise GatewayError("invalid_cursor", "Некорректный номер события.") from None

        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                batch = store.events(owner, identifier, cursor)
                for sequence, value in batch:
                    cursor = sequence
                    yield f"id: {sequence}\nevent: {value['type']}\ndata: {json.dumps(value['data'], ensure_ascii=False)}\n\n"
                run = store.get(owner, identifier, "run")
                if run["state"] in TERMINAL and not batch:
                    return
                if time.monotonic() - heartbeat >= 10:
                    yield ": keepalive\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.08)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/attachments")
    async def attachment(request: Request):
        owner = request.state.owner
        existing = store.list(owner, "attachment")
        if len(existing) >= 100:
            raise GatewayError("gateway_limit", "Достигнут предел хранилища вложений.", 429)
        raw = await request.body()
        if sum(value["size"] for _, value in existing) + len(raw) > 100 * 1024 * 1024:
            raise GatewayError("gateway_limit", "Достигнут предел хранилища вложений.", 429)
        mime = request.headers.get("content-type", "").split(";")[0]
        allowed = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain", "text/csv", "application/json",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if mime not in allowed or not raw:
            raise GatewayError("invalid_attachment", "Этот формат файла пока не принимается.", 415)
        if (mime == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n")) or (mime == "image/jpeg" and not raw.startswith(b"\xff\xd8")) or (mime == "application/pdf" and not raw.startswith(b"%PDF-")):
            raise GatewayError("invalid_attachment", "Тип файла не соответствует содержимому.", 415)
        name = request.headers.get("x-file-name", "attachment")
        from urllib.parse import unquote
        name = unquote(name)
        if not 0 < len(name) <= 150 or re.search(r"[\\/\x00-\x1f]", name):
            raise GatewayError("invalid_attachment", "Некорректное имя файла.")
        identifier = new_id()
        value = {"id": identifier, "name": name, "mime": mime, "size": len(raw), "created_at": time.time(), "data": base64.b64encode(raw).decode()}
        store.put(owner, identifier, "attachment", value)
        return {key: item for key, item in value.items() if key != "data"}

    @app.delete("/api/v1/attachments/{identifier}")
    async def delete_attachment(request: Request, identifier: str):
        store.get(request.state.owner, identifier, "attachment")
        store.delete(request.state.owner, identifier)
        return {"deleted": True}

    return app
