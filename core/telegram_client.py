"""Personal Telegram client. Explicit reads and reviewed, idempotent text sends."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import secrets
import time

import keyring
from pydantic import BaseModel, ConfigDict, Field
from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession

from .mail_drafts import check_scope


class TelegramConfig(BaseModel):
    model_config=ConfigDict(extra="forbid")
    api_id:int=Field(ge=1,le=2147483647,strict=True)
    api_hash:str=Field(pattern=r"^[a-fA-F0-9]{32}$")


class PhoneBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    phone:str=Field(pattern=r"^\+[1-9][0-9]{7,14}$")


class CodeBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    code:str=Field(pattern=r"^[0-9]{4,8}$")


class PasswordBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    password:str=Field(min_length=1,max_length=300)


class TelegramPreview(BaseModel):
    model_config=ConfigDict(extra="forbid")
    dialog:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=4000)


class Telegram:
    service="WileyAI.Telegram"

    def __init__(self,store,factory=TelegramClient):
        self.store,self.factory=store,factory
        self.key=hashlib.sha256(str(store.root.resolve()).casefold().encode()).hexdigest()
        self.lock=asyncio.Lock()
        self.client=None
        self.pending=None
        self.tickets={}
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS telegram_outbox(id TEXT PRIMARY KEY,scope_id TEXT NOT NULL,account_id INTEGER NOT NULL,peer TEXT NOT NULL,text TEXT NOT NULL,random_id INTEGER NOT NULL,state TEXT NOT NULL,message_id INTEGER NOT NULL,created TEXT NOT NULL,title TEXT NOT NULL DEFAULT '')")
            if "title" not in {row["name"] for row in db.execute("PRAGMA table_info(telegram_outbox)")}: db.execute("ALTER TABLE telegram_outbox ADD COLUMN title TEXT NOT NULL DEFAULT ''")

    def read(self):
        try:
            value=keyring.get_password(self.service,self.key)
            return json.loads(value) if value else {}
        except Exception as error: raise ValueError("Не удалось прочитать подключение Telegram из Windows") from error

    def write(self,value):
        try: keyring.set_password(self.service,self.key,json.dumps(value))
        except Exception as error: raise ValueError("Не удалось сохранить подключение Telegram в Windows") from error

    def status(self):
        value=self.read()
        pending=self.pending if self.pending and self.pending["expires"]>time.monotonic() else None
        return {"configured":bool(value.get("api_id")),"connected":bool(value.get("session")),"account":value.get("label", ""),"revision":value.get("epoch",""),"pending":bool(pending),"password_required":bool(pending and pending.get("password"))}

    async def configure(self,body):
        await self.close()
        self.write({**body.model_dump(),"epoch":secrets.token_hex(16)})
        return self.status()

    async def connection(self,require_login=True):
        value=self.read()
        if not value.get("api_id"): raise ValueError("Сначала укажите api_id и api_hash своего приложения Telegram")
        if self.client is None:
            self.client=self.factory(StringSession(value.get("session","")),value["api_id"],value["api_hash"],request_retries=0,connection_retries=1,timeout=15,auto_reconnect=False)
            async with asyncio.timeout(25): await self.client.connect()
        elif not self.client.is_connected():
            async with asyncio.timeout(25): await self.client.connect()
        if require_login and not await self.client.is_user_authorized(): raise ValueError("Войдите в Telegram заново")
        return self.client

    async def login(self,phone):
        client=await self.connection(False)
        async with asyncio.timeout(30): code=await client.send_code_request(phone)
        self.pending={"phone":phone,"hash":code.phone_code_hash,"expires":time.monotonic()+300,"password":False}
        return self.status()

    async def code(self,code):
        if not self.status()["pending"]: raise ValueError("Код входа истёк. Запросите новый")
        client=await self.connection(False)
        try:
            async with asyncio.timeout(30): await client.sign_in(phone=self.pending["phone"],code=code,phone_code_hash=self.pending["hash"])
        except errors.SessionPasswordNeededError:
            self.pending["password"]=True
            return self.status()
        return await self.finish_login()

    async def password(self,password):
        if not self.status()["password_required"]: raise ValueError("Telegram не запрашивал пароль в этом входе")
        client=await self.connection(False)
        async with asyncio.timeout(30): await client.sign_in(password=password)
        return await self.finish_login()

    async def finish_login(self):
        me=await self.client.get_me()
        value=self.read()
        self.write({**value,"session":self.client.session.save(),"account_id":me.id,"label":getattr(me,"username",None) or getattr(me,"first_name","") or str(me.id),"epoch":secrets.token_hex(16)})
        self.pending=None
        self.tickets.clear()
        return self.status()

    def ticket(self,store,kind,**values):
        with store.db() as db: check_scope(db,store)
        self.tickets={key:value for key,value in self.tickets.items() if value["expires"]>time.monotonic()}
        while len(self.tickets)>=300: self.tickets.pop(next(iter(self.tickets)))
        key=secrets.token_hex(24)
        self.tickets[key]={"scope":store.scope_id,"epoch":self.read().get("epoch"),"kind":kind,"expires":time.monotonic()+600,**values}
        return key

    def lookup(self,store,key,kind):
        with store.db() as db: check_scope(db,store)
        item=self.tickets.get(key)
        if not item or item["scope"]!=store.scope_id or item["kind"]!=kind or item["epoch"]!=self.read().get("epoch") or item["expires"]<time.monotonic():
            raise ValueError("Список Telegram устарел или относится к другому пространству")
        return item

    async def dialogs(self,store):
        client=await self.connection()
        async with asyncio.timeout(30): dialogs=await client.get_dialogs(limit=30)
        return [{"ticket":self.ticket(store,"dialog",peer=item.input_entity,title=str(item.name or "Без названия")[:200]),"title":str(item.name or "Без названия")[:200],"unread":item.unread_count} for item in dialogs]

    async def messages(self,store,key,before=0):
        item=self.lookup(store,key,"dialog")
        client=await self.connection()
        async with asyncio.timeout(30): values=await client.get_messages(item["peer"],limit=30,offset_id=before)
        return {"messages":[{"id":row.id,"text":str(row.message or "")[:10000],"date":row.date.isoformat(),"outgoing":bool(row.out),"media":bool(row.media)} for row in reversed(values)],"next_before":min((row.id for row in values),default=0) if len(values)==30 else 0}

    def preview(self,store,body):
        item=self.lookup(store,body.dialog,"dialog")
        if not body.text.strip() or len(body.text.encode('utf-16-le'))//2>4000: raise ValueError("Введите текст сообщения до 4000 символов")
        key=self.ticket(store,"send",peer=item["peer"],title=item["title"],text=body.text)
        return {"ticket":key,"recipient":item["title"],"text":body.text}

    def outbox(self,store):
        account=self.read().get("account_id",0)
        with store.db() as db:
            check_scope(db,store)
            return [dict(row) for row in db.execute("SELECT id,state,message_id,created,title,text FROM telegram_outbox WHERE scope_id=? AND account_id=? ORDER BY created DESC LIMIT 30",(store.scope_id,account))]

    async def import_contacts(self,store):
        from .contacts import Contacts,ContactBody
        client=await self.connection()
        async with asyncio.timeout(30): result=await client(functions.contacts.GetContactsRequest(hash=0))
        book=Contacts(store)
        existing=book.list()
        keys={row["telegram"].casefold() for row in existing if row["telegram"]}
        added,skipped=0,0
        for user in result.users[:1000]:
            handle="@"+user.username if getattr(user,"username",None) else "id:"+str(user.id)
            if handle.casefold() in keys or len(existing)+added>=500:
                skipped+=1;continue
            name=" ".join(value for value in (getattr(user,"first_name",None),getattr(user,"last_name",None)) if value) or handle
            phone=getattr(user,"phone","") or ""
            book.save(ContactBody(name=name[:160],telegram=handle[:100],phone=("+"+phone.lstrip("+"))[:50] if phone else ""))
            keys.add(handle.casefold());added+=1
        return {"added":added,"skipped":skipped+max(0,len(result.users)-1000)}

    async def send(self,store,ticket,confirmed):
        if not confirmed: raise ValueError("Подтвердите получателя и текст сообщения")
        item=self.lookup(store,ticket,"send")
        peer=item["peer"].to_dict()
        account=self.read().get("account_id",0)
        if not account: raise ValueError("Войдите в Telegram")
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db,store)
            if db.execute("SELECT 1 FROM telegram_outbox WHERE scope_id=? AND account_id=? AND peer=? AND state='unknown'",(store.scope_id,account,json.dumps(peer,sort_keys=True))).fetchone():
                raise ValueError("Для этого диалога есть неподтверждённая отправка. Сначала проверьте её результат")
            db.execute("INSERT INTO telegram_outbox VALUES (?,?,?,?,?,?,?,?,?,?)",(ticket,store.scope_id,account,json.dumps(peer,sort_keys=True),item["text"],secrets.randbits(63) or 1,"unknown",0,datetime.now(timezone.utc).isoformat(),item["title"]))
        self.tickets.pop(ticket,None)
        return await self.retry(store,ticket,True)

    async def retry(self,store,item_id,confirmed):
        if not confirmed: raise ValueError("Подтвердите повторную проверку той же отправки")
        account=self.read().get("account_id",0)
        with store.db() as db:
            check_scope(db,store)
            row=db.execute("SELECT * FROM telegram_outbox WHERE id=? AND scope_id=? AND account_id=?",(item_id,store.scope_id,account)).fetchone()
        if not row: raise ValueError("Отправка Telegram не найдена")
        item=dict(row)
        if item["state"]=="sent": return {"id":item_id,"state":"sent","message_id":item["message_id"]}
        data=json.loads(item["peer"])
        kind=data.pop("_","")
        if kind not in {"InputPeerUser","InputPeerChat","InputPeerChannel","InputPeerSelf"}: raise ValueError("Недопустимый получатель Telegram")
        peer=getattr(types,kind)(**data)
        client=await self.connection()
        message_id=item["message_id"]
        state="unknown"
        try:
            async with asyncio.timeout(35):
                response=await client(functions.messages.SendMessageRequest(peer=peer,message=item["text"],random_id=item["random_id"]))
                message_id=getattr(response,"id",0) or next((update.id for update in getattr(response,"updates",[]) if isinstance(update,types.UpdateMessageID) and update.random_id==item["random_id"]),0)
                if message_id:
                    message=await client.get_messages(peer,ids=message_id)
                    if message and message.out and message.message==item["text"]: state="sent"
        except errors.RandomIdDuplicateError:
            if message_id:
                try:
                    async with asyncio.timeout(10): message=await client.get_messages(peer,ids=message_id)
                    if message and message.out and message.message==item["text"]: state="sent"
                except (errors.RPCError,TimeoutError,OSError): pass
        except errors.RPCError as error:
            if error.code<500: state="failed"
        except (TimeoutError,OSError): pass
        with store.db() as db:
            db.execute("UPDATE telegram_outbox SET state=?,message_id=? WHERE id=?",(state,message_id,item_id))
        return {"id":item_id,"state":state,"message_id":message_id}

    async def disconnect(self):
        if self.client:
            try:
                async with asyncio.timeout(15): await self.client.log_out()
            except (errors.RPCError,TimeoutError,OSError): pass
        await self.close()
        value=self.read()
        self.write({key:value[key] for key in ("api_id","api_hash") if key in value})
        return self.status()

    async def close(self):
        self.pending=None
        self.tickets.clear()
        if self.client:
            client,self.client=self.client,None
            await client.disconnect()
