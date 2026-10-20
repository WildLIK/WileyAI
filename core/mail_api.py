"""Authenticated Gmail API with local drafts and explicitly reviewed sends."""
import asyncio

from anyio import CancelScope
from fastapi import HTTPException, Request
from fastapi.responses import Response

from .google_calendar import GoogleClientBody
from .mail import InboxQuery, ReplyBody, SuggestBody, local_model, GMAIL_SCOPE, GMAIL_SEND_SCOPE
from .mail_drafts import DraftBody, Drafts
from .mail_send import PreviewBody, ConfirmBody


def install_mail(app, mail, store, chat_lock, monitor):
    @app.get("/mail/status")
    def status(conversation_id: str | None = None):
        return mail.status(store.for_chat(conversation_id))

    @app.put("/mail/gmail/client")
    async def client(body: GoogleClientBody):
        async with mail.lock:
            result = await mail.auth.configure(body.document)
            mail.tickets.clear()
            return result

    @app.post("/mail/gmail/login")
    async def login():
        async with mail.lock:
            return await mail.auth.start()

    @app.post("/mail/gmail/send-login")
    async def send_login():
        async with mail.lock:
            return await mail.auth.start(scopes={GMAIL_SCOPE, GMAIL_SEND_SCOPE})

    @app.post("/mail/gmail/drafts-login")
    async def drafts_login():
        async with mail.lock:
            return await mail.auth.start(scopes={GMAIL_SCOPE,"https://www.googleapis.com/auth/gmail.compose"})

    @app.get("/mail/drafts/{item_id}/remote")
    async def remote_status(item_id: str, conversation_id: str | None = None):
        async with mail.lock:
            return mail.remote_drafts.link(store.for_chat(conversation_id),item_id)

    @app.post("/mail/drafts/{item_id}/remote-preview")
    async def remote_preview(item_id: str, body: PreviewBody, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.remote_drafts.preview(store.for_chat(conversation_id),item_id,body.expected_updated)

    @app.post("/mail/remote-save")
    async def remote_save(body: ConfirmBody, conversation_id: str | None = None):
        with CancelScope(shield=True):
            async with mail.lock:
                return await mail.remote_drafts.save(store.for_chat(conversation_id),body.ticket,body.confirmed)

    @app.post("/mail/drafts/{item_id}/remote-check")
    async def remote_check(item_id: str, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.remote_drafts.check(store.for_chat(conversation_id),item_id)

    @app.post("/mail/drafts/{item_id}/send-preview")
    async def send_preview(item_id: str, body: PreviewBody, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.sender.preview(store.for_chat(conversation_id), item_id, body.expected_updated)

    @app.post("/mail/send")
    async def send(body: ConfirmBody, conversation_id: str | None = None):
        with CancelScope(shield=True):
            async with mail.lock:
                return await mail.sender.confirm(store.for_chat(conversation_id), body)

    @app.get("/mail/drafts/{item_id}/delivery")
    async def delivery(item_id: str, conversation_id: str | None = None):
        async with mail.lock:
            return mail.sender.delivery(store.for_chat(conversation_id), item_id)

    @app.post("/mail/drafts/{item_id}/check-delivery")
    async def check_delivery(item_id: str, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.sender.check(store.for_chat(conversation_id), item_id)

    @app.post("/mail/gmail/cancel")
    async def cancel():
        async with mail.lock, mail.auth.lock:
            await mail.auth.cancel()
            return mail.auth.status()

    @app.post("/mail/gmail/disconnect")
    async def disconnect():
        async with mail.lock:
            result = await mail.auth.disconnect()
            mail.tickets.clear()
            return result

    @app.put("/mail/gmail/binding")
    async def bind(conversation_id: str | None = None):
        async with mail.lock:
            return await mail.bind(store.for_chat(conversation_id))

    @app.delete("/mail/gmail/binding")
    async def unbind(conversation_id: str | None = None):
        async with mail.lock:
            mail.unbind(store.for_chat(conversation_id))
            return {"ok": True}

    @app.post("/mail/inbox")
    async def inbox(body: InboxQuery, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.inbox(store.for_chat(conversation_id),body)

    @app.get("/mail/messages/{ticket}")
    async def message(ticket: str, conversation_id: str | None = None):
        async with mail.lock:
            return await mail.open(store.for_chat(conversation_id),ticket)

    @app.get("/mail/attachments/{ticket}")
    async def attachment(ticket: str, conversation_id: str | None = None):
        async with mail.lock:
            raw,name = await mail.attachment(store.for_chat(conversation_id),ticket)
            from urllib.parse import quote
            return Response(raw,media_type="application/octet-stream",headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(name,safe=""),"X-Content-Type-Options":"nosniff"})

    @app.post("/mail/reply")
    async def reply(body: ReplyBody, conversation_id: str | None = None):
        async with mail.lock:
            return mail.reply(store.for_chat(conversation_id),body.ticket)

    @app.get("/mail/drafts")
    def drafts(conversation_id: str | None = None):
        return Drafts(store.for_chat(conversation_id)).list()

    @app.post("/mail/drafts")
    def create_draft(body: DraftBody, conversation_id: str | None = None):
        return Drafts(store.for_chat(conversation_id)).save(body)

    @app.get("/mail/drafts/{item_id}")
    def get_draft(item_id: str, conversation_id: str | None = None):
        return Drafts(store.for_chat(conversation_id)).get(item_id)

    @app.put("/mail/drafts/{item_id}")
    def save_draft(item_id: str, body: DraftBody, expected_updated: str, conversation_id: str | None = None):
        return Drafts(store.for_chat(conversation_id)).save(body,item_id,expected_updated)

    @app.delete("/mail/drafts/{item_id}")
    def delete_draft(item_id: str, expected_updated: str, conversation_id: str | None = None):
        Drafts(store.for_chat(conversation_id)).remove(item_id,expected_updated)
        return {"ok":True}

    @app.get("/mail/drafts/{item_id}/eml")
    def eml(item_id: str, expected_updated: str, conversation_id: str | None = None):
        data = Drafts(store.for_chat(conversation_id)).eml(item_id,expected_updated)
        return Response(data,media_type="message/rfc822",headers={"Cache-Control":"no-store","Content-Disposition":f'attachment; filename="WileyAI-draft-{item_id}.eml"'})

    @app.post("/mail/drafts/{item_id}/suggest")
    async def suggest(item_id: str, body: SuggestBody, request: Request, conversation_id: str | None = None):
        if chat_lock.locked(): raise HTTPException(409,"Дождитесь ответа модели или остановите разговор")
        scoped = store.for_chat(conversation_id)
        async def generate():
            async with chat_lock,mail.lock:
                current = store.settings()
                with monitor.activity("mail:"+current.model,{"name":current.model,"category":"Черновик письма","location":"local" if local_model(current) else "cloud"}):
                    return await mail.suggest(scoped,item_id,body)
        task = asyncio.create_task(generate())
        try:
            while not task.done():
                if await request.is_disconnected(): raise HTTPException(499,"Подготовка текста отменена")
                await asyncio.wait({task},timeout=0.1)
            return await task
        finally:
            if not task.done():
                with CancelScope(shield=True):
                    task.cancel()
                    await asyncio.gather(task,return_exceptions=True)
