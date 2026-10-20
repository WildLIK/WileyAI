import asyncio
from anyio import CancelScope
from telethon import errors
from .mail_send import ConfirmBody
from .telegram_client import TelegramConfig, PhoneBody, CodeBody, PasswordBody, TelegramPreview


def install_telegram(app,telegram,store):
    async def call(action):
        async with telegram.lock:
            try:
                async with asyncio.timeout(45): return await action()
            except errors.FloodWaitError as error: raise ValueError(f"Telegram просит подождать {error.seconds} секунд") from error
            except (errors.PhoneCodeInvalidError,errors.PhoneCodeExpiredError) as error: raise ValueError("Код Telegram неверный или истёк. Проверьте код или запросите новый") from error
            except errors.PasswordHashInvalidError as error: raise ValueError("Неверный пароль двухэтапной проверки Telegram") from error
            except errors.RPCError as error: raise ValueError("Telegram отклонил запрос. Проверьте данные входа и доступ к диалогу") from error
            except (TimeoutError,OSError) as error: raise ValueError("Не удалось связаться с Telegram. Проверьте подключение; отправленное сообщение проверяется в очереди") from error

    @app.get("/telegram/status")
    def status(): return telegram.status()

    @app.put("/telegram/client")
    async def configure(body:TelegramConfig): return await call(lambda:telegram.configure(body))

    @app.post("/telegram/login")
    async def login(body:PhoneBody): return await call(lambda:telegram.login(body.phone))

    @app.post("/telegram/code")
    async def code(body:CodeBody): return await call(lambda:telegram.code(body.code))

    @app.post("/telegram/password")
    async def password(body:PasswordBody): return await call(lambda:telegram.password(body.password))

    @app.post("/telegram/disconnect")
    async def disconnect(): return await call(telegram.disconnect)

    @app.get("/telegram/dialogs")
    async def dialogs(conversation_id:str|None=None): return await call(lambda:telegram.dialogs(store.for_chat(conversation_id)))

    @app.get("/telegram/messages/{ticket}")
    async def messages(ticket:str,before:int=0,conversation_id:str|None=None):
        if before<0: raise ValueError("Некорректная страница Telegram")
        return await call(lambda:telegram.messages(store.for_chat(conversation_id),ticket,before))

    @app.post("/telegram/preview")
    def preview(body:TelegramPreview,conversation_id:str|None=None): return telegram.preview(store.for_chat(conversation_id),body)

    @app.post("/telegram/send")
    async def send(body:ConfirmBody,conversation_id:str|None=None):
        with CancelScope(shield=True): return await call(lambda:telegram.send(store.for_chat(conversation_id),body.ticket,body.confirmed))

    @app.get("/telegram/outbox")
    def outbox(conversation_id:str|None=None): return telegram.outbox(store.for_chat(conversation_id))

    @app.post("/telegram/import-contacts")
    async def import_contacts(conversation_id:str|None=None): return await call(lambda:telegram.import_contacts(store.for_chat(conversation_id)))

    @app.post("/telegram/outbox/{item_id}/retry")
    async def retry(item_id:str,body:ConfirmBody,conversation_id:str|None=None):
        if body.ticket!=item_id: raise ValueError("Подтверждение относится к другой отправке")
        with CancelScope(shield=True): return await call(lambda:telegram.retry(store.for_chat(conversation_id),item_id,body.confirmed))
