from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS

import pytest
from telethon import errors, functions, types

from core.backups import Backups
from core.chatspaces import Spaces
from core.contacts import Contacts
from core.storage import Store
from core.telegram_client import Telegram, TelegramConfig, TelegramPreview
from core.api import create_app
import httpx


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.fixture
def vault(monkeypatch):
    values={}
    monkeypatch.setattr("core.telegram_client.keyring.get_password",lambda service,key:values.get((service,key)))
    monkeypatch.setattr("core.telegram_client.keyring.set_password",lambda service,key,value:values.__setitem__((service,key),value))
    return values


class Client:
    def __init__(self):
        self.session=NS(save=lambda:"fixture-session")
        self.authorized=False
        self.connected=False
        self.twofa=False
        self.lose=False
        self.rpc=False
        self.requests=[]
        self.sent={}
    async def connect(self): self.connected=True
    def is_connected(self): return self.connected
    async def disconnect(self): self.connected=False
    async def is_user_authorized(self): return self.authorized
    async def send_code_request(self,phone): return NS(phone_code_hash="private-hash")
    async def sign_in(self,**kwargs):
        if self.twofa and "password" not in kwargs: raise errors.SessionPasswordNeededError(None)
        self.authorized=True
    async def get_me(self): return NS(id=42,username="fixture",first_name="Name")
    async def log_out(self): self.authorized=False
    async def get_dialogs(self,limit): return [NS(input_entity=types.InputPeerUser(7,123),name="Получатель",unread_count=1)]
    async def get_messages(self,peer,**kwargs):
        if "ids" in kwargs: return self.sent.get(kwargs["ids"])
        return [NS(id=10,message="<script>инертный текст</script>",date=datetime.now(timezone.utc),out=False,media=None)]
    async def __call__(self,request):
        self.requests.append(request)
        if isinstance(request,functions.contacts.GetContactsRequest):
            return NS(users=[NS(id=7,username="friend",first_name="Друг",last_name="",phone="79990000000")])
        assert isinstance(request,functions.messages.SendMessageRequest)
        if self.rpc: raise errors.ChatWriteForbiddenError(request)
        message_id=77
        self.sent[message_id]=NS(id=message_id,out=True,message=request.message)
        if self.lose: raise TimeoutError()
        return NS(id=message_id)


async def setup(tmp_path):
    store=Store(tmp_path)
    client=Client()
    manager=Telegram(store,factory=lambda *args,**kwargs:client)
    await manager.configure(TelegramConfig(api_id=12345,api_hash="a"*32))
    return store,client,manager


async def login(manager):
    await manager.login("+79990000000")
    await manager.code("12345")


@pytest.mark.anyio
async def test_login_two_factor_credentials_isolation_and_disconnect(tmp_path,vault):
    store,client,manager=await setup(tmp_path)
    client.twofa=True
    await manager.login("+79990000000")
    assert (await manager.code("12345"))["password_required"]
    assert not manager.status()["connected"]
    await manager.password("private-password")
    assert manager.status()["connected"] and not manager.pending
    saved=json.dumps(list(vault.values()))
    assert "fixture-session" in saved and "private-password" not in saved and "+79990000000" not in saved
    assert "session" not in json.dumps(manager.status()) and "api_hash" not in json.dumps(manager.status())
    assert not Telegram(Store(tmp_path/"other")).status()["configured"]
    await manager.disconnect()
    assert not manager.status()["connected"] and not client.authorized
    assert manager.status()["configured"]


@pytest.mark.anyio
async def test_expired_login_and_scope_epoch_tickets(tmp_path,vault):
    store,client,manager=await setup(tmp_path)
    await manager.login("+79990000000")
    manager.pending["expires"]=0
    with pytest.raises(ValueError,match="истёк"): await manager.code("12345")
    await login(manager)
    dialog=(await manager.dialogs(store))[0]
    project=Spaces(store).create_project("Другой проект")
    chat=Spaces(store).create_chat(project["id"])
    with pytest.raises(ValueError): await manager.messages(store.for_chat(chat["id"]),dialog["ticket"])
    manager.write({**manager.read(),"epoch":"changed"})
    with pytest.raises(ValueError): manager.preview(store,TelegramPreview(dialog=dialog["ticket"],text="Привет"))
    await manager.close()


@pytest.mark.anyio
async def test_review_no_send_before_confirmation_verified_receipt_and_no_duplicate(tmp_path,vault):
    store,client,manager=await setup(tmp_path)
    await login(manager)
    dialog=(await manager.dialogs(store))[0]
    messages=await manager.messages(store,dialog["ticket"])
    assert "<script>" in messages["messages"][0]["text"]
    preview=manager.preview(store,TelegramPreview(dialog=dialog["ticket"],text="Проверенный текст"))
    assert not client.requests and not manager.outbox(store)
    with pytest.raises(ValueError): await manager.send(store,preview["ticket"],False)
    result=await manager.send(store,preview["ticket"],True)
    assert result["state"]=="sent" and result["message_id"]==77
    await manager.retry(store,result["id"],True)
    with pytest.raises(ValueError): await manager.send(store,preview["ticket"],True)
    assert len(client.requests)==1
    # Tokens, session, dialog cache and outbox are not in user backups.
    backup=Backups(store).export().decode()
    assert "Проверенный текст" not in backup and "fixture-session" not in backup
    await manager.close()


@pytest.mark.anyio
async def test_lost_response_retry_uses_same_persistent_random_id_and_blocks_new_send(tmp_path,vault):
    store,client,manager=await setup(tmp_path)
    await login(manager)
    dialog=(await manager.dialogs(store))[0]
    preview=manager.preview(store,TelegramPreview(dialog=dialog["ticket"],text="Одна отправка"))
    client.lose=True
    receipt=await manager.send(store,preview["ticket"],True)
    assert receipt["state"]=="unknown"
    other=manager.preview(store,TelegramPreview(dialog=dialog["ticket"],text="Другая"))
    with pytest.raises(ValueError,match="неподтверждённая"): await manager.send(store,other["ticket"],True)
    random_id=client.requests[0].random_id
    await manager.close()
    restarted=Telegram(store,factory=lambda *args,**kwargs:client)
    # Fixture uses an opaque saved-session string; reuse an already connected fake.
    restarted.client=client
    client.lose=False
    result=await restarted.retry(store,receipt["id"],True)
    assert result["state"]=="sent" and client.requests[-1].random_id==random_id
    assert len(client.sent)==1
    await restarted.close()


@pytest.mark.anyio
async def test_rejected_send_and_explicit_contacts_import(tmp_path,vault):
    store,client,manager=await setup(tmp_path)
    await login(manager)
    dialog=(await manager.dialogs(store))[0]
    preview=manager.preview(store,TelegramPreview(dialog=dialog["ticket"],text="Текст"))
    client.rpc=True
    assert (await manager.send(store,preview["ticket"],True))["state"]=="failed"
    assert not Contacts(store).list()
    assert (await manager.import_contacts(store))["added"]==1
    assert (await manager.import_contacts(store))["skipped"]==1
    assert Contacts(store).list()[0]["telegram"]=="@friend"
    await manager.close()


@pytest.mark.anyio
async def test_http_telegram_auth_review_and_stale_ticket(tmp_path,vault):
    token="telegram-fixture-local-token"
    app=create_app(tmp_path,token)
    manager=app.state.telegram
    fake=Client()
    manager.factory=lambda *args,**kwargs:fake
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://localhost") as client:
        assert (await client.get("/telegram/status")).status_code==401
        client.headers["Authorization"]="Bearer "+token
        await client.put("/telegram/client",json={"api_id":12345,"api_hash":"a"*32})
        await client.post("/telegram/login",json={"phone":"+79990000000"})
        response=await client.post("/telegram/code",json={"code":"12345"})
        assert response.json()["connected"] and response.headers["cache-control"]=="no-store"
        dialog=(await client.get("/telegram/dialogs")).json()[0]
        preview=(await client.post("/telegram/preview",json={"dialog":dialog["ticket"],"text":"Текст"})).json()
        assert not fake.requests
        assert (await client.post("/telegram/send",json={"ticket":preview["ticket"],"confirmed":False})).status_code==400
        result=await client.post("/telegram/send",json={"ticket":preview["ticket"],"confirmed":True})
        assert result.json()["state"]=="sent"
        assert (await client.post("/telegram/send",json={"ticket":preview["ticket"],"confirmed":True})).status_code==400
        assert len(fake.requests)==1
    await manager.close()
    await app.state.mail.close()
    await app.state.google_calendar.close()
