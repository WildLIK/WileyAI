import asyncio
import base64
from email import policy
from email.parser import BytesParser
import json
import time
from urllib.parse import parse_qs,urlsplit

from fastapi.testclient import TestClient
import httpx
import pytest

from core.api import create_app
from core.backups import Backups,encode,parse
from core.chatspaces import Spaces
from core.google_calendar_auth import GoogleAuth,TOKEN_URL
from core.mail import Mail,InboxQuery,SuggestBody,GMAIL_SCOPE
from core.mail_drafts import DraftBody,DraftSource,Drafts,address
from core.mail_mime import content,metadata
from core.storage import Store

CLIENT={"installed":{"client_id":"1234567890-mailfixture.apps.googleusercontent.com","client_secret":"fixture-secret","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":TOKEN_URL}}


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.fixture
def vault(monkeypatch):
    values={}
    monkeypatch.setattr("core.google_calendar_auth.keyring.get_password",lambda service,key:values.get((service,key)))
    monkeypatch.setattr("core.google_calendar_auth.keyring.set_password",lambda service,key,value:values.__setitem__((service,key),value))
    return values


def body(**changes): return DraftBody(**{**dict(to_addresses=["reader@example.test"],subject="Предложение",body="Добрый день!"),**changes})


def message(text="Текст исходного письма",mime="text/plain",**changes):
    payload={"mimeType":mime,"headers":[{"name":"From","value":"Автор <author@example.test>"},{"name":"Subject","value":"Предложение"},{"name":"Date","value":"Mon, 19 Oct 2026 10:00:00 +0500"},{"name":"Message-ID","value":"<original@example.test>"}],"body":{"data":base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")}}
    return {**dict(id="abc123",labelIds=["INBOX","UNREAD"],payload=payload,snippet="Текст письма"),**changes}


class FakeGmail:
    def __init__(self):
        self.calls=[]
        self.messages={"abc123":message()}
        self.next_page=None
        self.fail=False
    def handle(self,request):
        self.calls.append(request)
        assert request.method=="GET"
        assert request.headers["Authorization"]=="Bearer mail-access"
        if self.fail: return httpx.Response(403,json={"private":"SECRET-MUST-NOT-LEAK"})
        if request.url.path.endswith("/profile"): return httpx.Response(200,json={"emailAddress":"owner@example.test"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200,json={"messages":[{"id":key} for key in self.messages],"nextPageToken":self.next_page})
        item=self.messages.get(request.url.path.rsplit("/",1)[-1])
        return httpx.Response(200,json=item) if item else httpx.Response(404,json={})


async def configured(store,fake):
    auth=GoogleAuth(store.root,httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)),scopes={GMAIL_SCOPE},service="WileyAI.Gmail",permission_text="чтению писем Gmail")
    await auth.configure(json.dumps(CLIENT))
    auth.write({**auth.read(),"access_token":"mail-access","refresh_token":"mail-refresh","expires_at":time.time()+3600})
    mail=Mail(store,auth)
    await mail.bind(store)
    return mail


@pytest.mark.parametrize("value",["a\r\nBcc: leak@example.test","a b@example.test","x@example..test",".x@example.test","a..b@example.test","x@-host.test","Name <x@example.test>","x@localhost"])
def test_recipient_and_header_injection_rejected(value):
    with pytest.raises(ValueError): body(to_addresses=[value])


@pytest.mark.parametrize("changes",[{"subject":"Hello\nBcc: x@example.test"},{"body":"text\0"},{"cc_addresses":["reader@example.test"]},{"to_addresses":["same@example.test","SAME@example.test"]},{"to_addresses":["a@example.test"]*21}])
def test_invalid_draft_fields_rejected(changes):
    with pytest.raises(ValueError): body(**changes)


def test_local_drafts_scopes_stale_revisions_and_eml(tmp_path):
    store=Store(tmp_path)
    drafts=Drafts(store)
    item=drafts.save(body(cc_addresses=["copy@example.test"],bcc_addresses=["hidden@example.test"],body="Привет, мир!\nПроверка."))
    assert drafts.list()[0]["preview"]==item["body"]
    email=BytesParser(policy=policy.default).parsebytes(drafts.eml(item["id"],item["updated"]))
    assert str(email["Subject"])=="Предложение" and email["X-Unsent"]=="1"
    assert email["Bcc"]=="hidden@example.test" and "Привет, мир!" in email.get_content()
    revised=drafts.save(body(subject="Изменено"),item["id"],item["updated"])
    assert revised["updated"]>item["updated"]
    with pytest.raises(ValueError): drafts.save(body(),item["id"],item["updated"])
    with pytest.raises(ValueError): drafts.remove(item["id"],item["updated"])
    with pytest.raises(ValueError): drafts.eml(item["id"],item["updated"])
    spaces=Spaces(store)
    project=spaces.create_project("Другое")
    chat=spaces.create_chat(project["id"])
    other=Drafts(store.for_chat(chat["id"]))
    assert not other.list()
    with pytest.raises(ValueError): other.get(item["id"])
    shared=spaces.create_chat(None)
    assert Drafts(store.for_chat(shared["id"])).get(item["id"])["subject"]=="Изменено"
    own=other.save(body())
    spaces.delete_project(project["id"])
    with store.db() as db: assert not db.execute("SELECT 1 FROM mail_drafts WHERE id=?",(own["id"],)).fetchone()
    drafts.remove(item["id"],revised["updated"])
    assert not Store(tmp_path).db is None
    assert not drafts.list()


def test_empty_draft_allowed_export_needs_recipient_and_source_is_immutable(tmp_path):
    drafts=Drafts(Store(tmp_path))
    empty=drafts.save(DraftBody())
    with pytest.raises(ValueError): drafts.eml(empty["id"],empty["updated"])
    original=drafts.save(body(),source=DraftSource(source_account="owner@example.test",source_message_id="abc123",in_reply_to="<original@example.test>"))
    revised=drafts.save(body(subject="Ответ"),original["id"],original["updated"])
    email=BytesParser(policy=policy.default).parsebytes(drafts.eml(revised["id"],revised["updated"]))
    assert email["In-Reply-To"]=="<original@example.test>" and email["From"]=="owner@example.test"
    assert address("x@ПРИМЕР.РФ")=="x@xn--e1afmkfd.xn--p1ai"


def test_backup_v10_drafts_and_no_mail_bindings_or_inbox(tmp_path):
    store=Store(tmp_path)
    item=Drafts(store).save(body())
    with store.db() as db: db.execute("INSERT INTO mail_bindings VALUES ('','binding','owner@example.test','epoch')")
    manager=Backups(store)
    archive=manager.export()
    assert json.loads(archive)["version"]==11 and "mail_bindings" not in archive.decode()
    assert parse(archive).data.mail_drafts[0].subject==item["subject"]
    other=Store(tmp_path/"other")
    backup=Backups(other)
    backup.restore(backup.preview(archive)["ticket"])
    assert Drafts(other).get(item["id"])==item
    manager.restore(manager.preview(archive)["ticket"])
    with store.db() as db: assert not db.execute("SELECT * FROM mail_bindings").fetchall()
    changed=json.loads(archive)
    changed["version"]=9
    with pytest.raises(ValueError): parse(encode(changed))
    changed["data"]["mail_drafts"]=[]
    assert parse(encode(changed)).version==9
    for field,value in [("scope_id","missing"),("to_addresses",["bad\n@example.test"]),("in_reply_to","<x@x>\r\nBcc: x@example.test")]:
        changed=json.loads(archive)
        changed["data"]["mail_drafts"][0][field]=value
        with pytest.raises(ValueError): parse(encode(changed))


def test_mime_html_is_inert_and_alternative_uses_plain_text():
    html=message('<p>Привет</p><img src="https://tracker.test/pixel"><script>steal()</script><style>hidden</style><a href="https://example.test">Текст ссылки</a>',mime="text/html")
    result=content(html)
    assert "Привет" in result["text"] and "Текст ссылки" in result["text"]
    assert "steal" not in result["text"] and "tracker" not in result["text"] and "hidden" not in result["text"]
    plain=message("Обычный текст")["payload"]
    mixed={"payload":{"mimeType":"multipart/alternative","parts":[plain,html["payload"]]}}
    assert content(mixed)["text"]=="Обычный текст"
    attachment={"mimeType":"text/plain","filename":"private.txt","body":{"attachmentId":"attachment-token"}}
    mixed={"payload":{"mimeType":"multipart/mixed","parts":[plain,attachment]}}
    assert content(mixed)["attachments"][0]["name"]=="private.txt"
    assert "attachment-token" not in json.dumps(content(mixed))


def test_large_text_and_bad_charset_are_labelled():
    result=content(message("x"*100010))
    assert result["truncated"] and len(result["text"])==100000 and result["notes"]
    data=message("Текст")
    data["payload"]["headers"].append({"name":"Content-Type","value":"text/plain; charset=not-a-codec"})
    assert content(data)["notes"]
    data["payload"]["body"]["data"]="@@@@"
    with pytest.raises(ValueError): content(data)


def test_ambiguous_sender_does_not_guess_reply_target():
    data=message()
    data["payload"]["headers"].append({"name":"Reply-To","value":"a@example.test, b@example.test"})
    assert not metadata(data)["reply_addresses"]
    data["payload"]["headers"].append({"name":"Message-ID","value":"<second@example.test>"})
    assert metadata(data)["in_reply_to"] is None


@pytest.mark.anyio
async def test_gmail_requests_only_read_and_tokens_separate_from_calendar(tmp_path,vault):
    store,fake=Store(tmp_path),FakeGmail()
    mail=await configured(store,fake)
    calendar=GoogleAuth(tmp_path)
    assert not calendar.status()["configured"]
    login=await mail.auth.start()
    query=parse_qs(urlsplit(login["url"]).query)
    assert query["scope"]==[GMAIL_SCOPE]
    token_values={"access_token":"fixture","token_type":"Bearer","expires_in":3600}
    with pytest.raises(ValueError): mail.auth.validate_tokens({**token_values,"scope":"https://www.googleapis.com/auth/calendar.events"},require_scope=True)
    mail.auth.validate_tokens({**token_values,"scope":GMAIL_SCOPE},require_scope=True)
    await mail.auth.close()
    result=await mail.inbox(store,InboxQuery(folder="unread",query="from:author@example.test"))
    assert "is:unread" in next(call for call in fake.calls if call.url.path.endswith("/messages")).url.params["q"]
    letter=await mail.open(store,result["messages"][0]["ticket"])
    assert letter["text"]=="Текст исходного письма"
    reply=mail.reply(store,letter["ticket"])
    assert reply["to_addresses"]==["author@example.test"] and reply["body"]=="" and reply["source_account"]=="owner@example.test"
    assert all(call.method=="GET" for call in fake.calls)

    assert not any("send" in call.url.path or "modify" in call.url.path for call in fake.calls)
    for path in ("/messages/send","/messages/abc123/trash","https://example.test"):
        with pytest.raises(ValueError): await mail.read(path)
    assert not any("send" in call.url.path or "modify" in call.url.path for call in fake.calls)
    archive=Backups(store).export().decode()
    assert "mail-access" not in archive and "mail-refresh" not in archive and "Текст исходного письма" not in archive


@pytest.mark.anyio
async def test_scope_account_switch_and_restore_invalidate_mail_handles(tmp_path,vault):
    store,fake=Store(tmp_path),FakeGmail()
    mail=await configured(store,fake)
    page=await mail.inbox(store,InboxQuery())
    ticket=page["messages"][0]["ticket"]
    spaces=Spaces(store)
    chat=spaces.create_chat(spaces.create_project("Другой")["id"])
    other=store.for_chat(chat["id"])
    with pytest.raises(ValueError): await mail.open(other,ticket)
    await mail.bind(other)
    with pytest.raises(ValueError): await mail.open(other,ticket)
    page=await mail.inbox(store,InboxQuery())
    ticket=page["messages"][0]["ticket"]
    manager=Backups(store)
    manager.restore(manager.preview(manager.export())["ticket"])
    with pytest.raises(ValueError): await mail.open(store,ticket)


@pytest.mark.anyio
async def test_pagination_expiry_and_failure_not_empty_success(tmp_path,vault):
    store,fake=Store(tmp_path),FakeGmail()
    mail=await configured(store,fake)
    fake.next_page="next"
    page=await mail.inbox(store,InboxQuery())
    with pytest.raises(ValueError): await mail.inbox(store,InboxQuery(cursor=page["next_cursor"],query="changed"))
    with pytest.raises(ValueError): await mail.inbox(store,InboxQuery(cursor=page["next_cursor"]))
    mail.tickets[page["messages"][0]["ticket"]]["expires"]=0
    with pytest.raises(ValueError): await mail.open(store,page["messages"][0]["ticket"])
    fake.fail=True
    with pytest.raises(ValueError) as error: await mail.inbox(store,InboxQuery())
    assert "SECRET-MUST-NOT-LEAK" not in str(error.value)


@pytest.mark.anyio
async def test_model_suggestion_is_review_only_and_uses_selected_source(tmp_path,vault,monkeypatch):
    store,fake=Store(tmp_path),FakeGmail()
    mail=await configured(store,fake)
    page=await mail.inbox(store,InboxQuery())
    letter=await mail.open(store,page["messages"][0]["ticket"])
    draft=mail.reply(store,letter["ticket"])
    prompts=[]
    async def model(settings,messages):
        prompts.extend(messages)
        yield "Спасибо за предложение. Пришлите подробности."
    monkeypatch.setattr("core.mail.providers.chat",model)
    result=await mail.suggest(store,draft["id"],SuggestBody(expected_updated=draft["updated"],instructions="Попроси подробности"))
    assert "Спасибо" in result["text"] and Drafts(store).get(draft["id"])["body"]==""
    payload=json.loads(prompts[1]["content"])
    assert payload["original_message"]["text"]==letter["text"]
    assert "mail-access" not in str(prompts) and "mail-refresh" not in str(prompts)
    assert all(call.method=="GET" for call in fake.calls)
    fake.messages["abc123"]=message("Длинное письмо. "*3000)
    extended=await mail.suggest(store,draft["id"],SuggestBody(expected_updated=draft["updated"],instructions="Короткий ответ"))
    assert extended["source_partial"] and extended["source_chars"]<=24000
    assert len(json.loads(prompts[-1]["content"])["original_message"]["text"])==extended["source_chars"]
    store.save_settings(store.settings().model_copy(update={"provider":"compatible"}))
    count=len(prompts)
    with pytest.raises(ValueError,match="внешний сервер"):
        await mail.suggest(store,draft["id"],SuggestBody(expected_updated=draft["updated"],instructions="Ответ"))
    assert len(prompts)==count
    cloud=await mail.suggest(store,draft["id"],SuggestBody(expected_updated=draft["updated"],instructions="Ответ",allow_cloud=True))
    assert cloud["text"]
    store.save_settings(store.settings().model_copy(update={"provider":"ollama","base_url":"https://remote.example.test"}))
    count=len(prompts)
    assert mail.status(store)["model_location"]=="cloud"
    with pytest.raises(ValueError,match="внешний сервер"):
        await mail.suggest(store,draft["id"],SuggestBody(expected_updated=draft["updated"],instructions="Ответ"))
    assert len(prompts)==count


@pytest.mark.anyio
async def test_model_cancel_and_concurrent_edit_never_replace_draft(tmp_path,vault,monkeypatch):
    store=Store(tmp_path)
    mail=Mail(store)
    drafts=Drafts(store)
    item=drafts.save(body())
    started,closed=asyncio.Event(),asyncio.Event()
    async def slow(settings,messages):
        started.set()
        try:
            yield "Начало"
            await asyncio.sleep(60)
        finally: closed.set()
    monkeypatch.setattr("core.mail.providers.chat",slow)
    task=asyncio.create_task(mail.suggest(store,item["id"],SuggestBody(expected_updated=item["updated"],instructions="Ответ")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert closed.is_set() and drafts.get(item["id"])["body"]==item["body"]
    async def concurrent(settings,messages):
        drafts.save(body(body="Ручная правка"),item["id"],item["updated"])
        yield "Текст модели"
    monkeypatch.setattr("core.mail.providers.chat",concurrent)
    with pytest.raises(ValueError,match="изменился"): await mail.suggest(store,item["id"],SuggestBody(expected_updated=item["updated"],instructions="Ответ"))
    assert drafts.get(item["id"])["body"]=="Ручная правка"


def test_mail_api_auth_scope_and_send_requires_review(tmp_path,vault):
    token="mail-api-test-0123456789012345"
    with TestClient(create_app(tmp_path,token)) as api:
        assert api.get("/mail/drafts").status_code==401
        api.headers["Authorization"]="Bearer "+token
        item=api.post("/mail/drafts",json=body().model_dump()).json()
        assert api.get("/mail/drafts").json()[0]["id"]==item["id"]
        assert api.get("/mail/drafts/"+item["id"]+"/eml",params={"expected_updated":item["updated"]}).status_code==200
        assert api.put("/mail/drafts/"+item["id"],params={"expected_updated":"old"},json=body().model_dump()).status_code==400
        assert api.post("/mail/send",json={"id":item["id"]}).status_code==422
        assert api.post("/mail/send",json={"ticket":"invented","confirmed":True}).status_code==400
        assert api.post("/mail/inbox",json={}).status_code==400
        assert api.put("/mail/gmail/client",json={"document":json.dumps(CLIENT)}).status_code==200
        assert api.get("/mail/status").json()["configured"]
