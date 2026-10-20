"""Authenticated endpoints for a fixed Home Assistant action set."""
from anyio import CancelScope
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from .home_assistant import ConnectionBody, AccessBody, HomeAction
from .mail_send import ConfirmBody


def install_home_assistant(app, home, store):
    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        # Validation responses must never echo a pasted credential (including
        # a malformed SecretStr or an unexpected field containing that token).
        if request.url.path.startswith("/home-assistant/"):
            return JSONResponse(status_code=400, content={"detail": "Проверьте поля Home Assistant: адрес, токен, устройство и параметры действия"})
        return await request_validation_exception_handler(request, error)

    @app.get("/home-assistant/status")
    def status(conversation_id: str | None = None): return home.status(store.for_chat(conversation_id))

    @app.put("/home-assistant/connection")
    async def connection(body: ConnectionBody, conversation_id: str | None = None):
        async with home.lock: return await home.configure(store.for_chat(conversation_id), body)

    @app.post("/home-assistant/check")
    async def check_connection(conversation_id: str | None = None):
        async with home.lock: return {**home.status(store.for_chat(conversation_id)), **await home.check_connection()}

    @app.delete("/home-assistant/connection")
    async def disconnect(conversation_id: str | None = None):
        async with home.lock: return home.disconnect(store.for_chat(conversation_id))

    @app.get("/home-assistant/entities")
    async def entities(conversation_id: str | None = None):
        async with home.lock: return await home.entities(store.for_chat(conversation_id))

    @app.put("/home-assistant/access")
    async def access(body: AccessBody, conversation_id: str | None = None):
        async with home.lock: return await home.access(store.for_chat(conversation_id), body)

    @app.post("/home-assistant/preview")
    async def preview(body: HomeAction, conversation_id: str | None = None):
        async with home.lock: return await home.preview(store.for_chat(conversation_id), body)

    @app.post("/home-assistant/confirm")
    async def confirm(body: ConfirmBody, conversation_id: str | None = None):
        with CancelScope(shield=True):
            async with home.lock: return await home.dispatch(store.for_chat(conversation_id), body.ticket, body.confirmed)

    @app.get("/home-assistant/actions")
    async def actions(conversation_id: str | None = None):
        async with home.lock: return home.history(store.for_chat(conversation_id))

    @app.post("/home-assistant/actions/{item_id}/check")
    async def check(item_id: str, conversation_id: str | None = None):
        async with home.lock: return await home.check(store.for_chat(conversation_id), item_id)
