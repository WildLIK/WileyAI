import asyncio
import base64
from email import policy
from email.parser import BytesParser
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from core.chatspaces import Spaces
from core.api import create_app
from core.google_calendar_auth import GoogleAuth, TOKEN_URL
from core.mail import Mail, GMAIL_SCOPE, GMAIL_SEND_SCOPE
from core.mail_drafts import DraftBody, DraftSource, Drafts
from core.mail_send import ConfirmBody
from core.storage import Store


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.fixture
def vault(monkeypatch):
    values = {}
    monkeypatch.setattr("core.google_calendar_auth.keyring.get_password", lambda service, key: values.get((service, key)))
    monkeypatch.setattr("core.google_calendar_auth.keyring.set_password", lambda service, key, value: values.__setitem__((service, key), value))


CLIENT = {"installed": {"client_id": "1234567890-sendfixture.apps.googleusercontent.com", "client_secret": "fixture-secret", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URL}}


class Gmail:
    def __init__(self):
        self.posts = []
        self.messages = {}
        self.fail = None
        self.lose = False
        self.mismatch = False
        self.account = "owner@example.test"
        self.scope = GMAIL_SCOPE + " " + GMAIL_SEND_SCOPE

    def handle(self, request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "fresh-access", "refresh_token": "refresh", "expires_in": 3600, "token_type": "Bearer", "scope": self.scope})
        path = request.url.path
        if path.endswith("/messages/send"):
            assert request.method == "POST"
            data = json.loads(request.content)
            self.posts.append(data)
            if self.fail:
                return httpx.Response(self.fail, json={"private": "must-not-leak"})
            parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(data["raw"]))
            self.messages["feed123"] = {"id": "feed123", "labelIds": ["SENT"], "payload": {"headers": [{"name": "Message-ID", "value": "<wrong@example.test>" if self.mismatch else str(parsed["Message-ID"])}]}}
            if self.lose:
                raise httpx.ReadTimeout("private network details", request=request)
            return httpx.Response(200, json={"id": "feed123"})
        assert request.method == "GET"
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": self.account})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": key} for key in self.messages]})
        if path.endswith("/abc123"):
            return httpx.Response(200, json={"id": "abc123", "threadId": "aaa111"})
        message = self.messages.get(path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=message) if message else httpx.Response(404, json={})


async def setup(tmp_path, *, send=True):
    store, fake = Store(tmp_path), Gmail()
    auth = GoogleAuth(store.root, httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)), scopes={GMAIL_SCOPE}, service="WileyAI.Gmail")
    await auth.configure(json.dumps(CLIENT))
    auth.write({**auth.read(), "access_token": "fixture-access", "refresh_token": "refresh", "expires_at": time.time() + 3600, "granted_scopes": [GMAIL_SCOPE, *([GMAIL_SEND_SCOPE] if send else [])]})
    mail = Mail(store, auth)
    await mail.bind(store)
    draft = Drafts(store).save(DraftBody(to_addresses=["reader@example.test"], cc_addresses=["copy@example.test"], bcc_addresses=["hidden@example.test"], subject="Проверенное письмо", body="Русский текст письма"))
    return store, fake, mail, draft


@pytest.mark.anyio
async def test_review_consent_mime_verification_and_duplicate_restart(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path)
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    assert not fake.posts
    assert preview["bcc_addresses"] == ["hidden@example.test"]
    with pytest.raises(ValueError, match="Подтвердите"):
        await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=False))
    result = await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert result["state"] == "sent" and result["google_id"] == "feed123"
    parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(fake.posts[0]["raw"]))
    assert str(parsed["From"]) == "owner@example.test"
    assert str(parsed["Bcc"]) == "hidden@example.test" and str(parsed["Cc"]) == "copy@example.test"
    assert "Русский текст письма" in parsed.get_content() and str(parsed["Subject"]) == draft["subject"]
    assert parsed["X-Unsent"] is None
    with pytest.raises(ValueError):
        await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    restarted = Mail(Store(tmp_path), mail.auth)
    with pytest.raises(ValueError, match="уже отправлялась"):
        await restarted.sender.preview(store, draft["id"], draft["updated"])
    assert len(fake.posts) == 1
    await mail.close()


@pytest.mark.anyio
async def test_read_permission_never_implies_send_and_upgrade_is_explicit(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path, send=False)
    assert not mail.status(store)["send_enabled"]
    with pytest.raises(ValueError, match="отдельно разрешите"):
        await mail.sender.preview(store, draft["id"], draft["updated"])
    old_epoch = mail.auth.read()["epoch"]
    fake.scope = GMAIL_SCOPE  # User declines the new permission.
    query = parse_qs(urlsplit((await mail.auth.start(scopes={GMAIL_SCOPE, GMAIL_SEND_SCOPE}))["url"]).query)
    assert set(query["scope"][0].split()) == {GMAIL_SCOPE, GMAIL_SEND_SCOPE}
    async with httpx.AsyncClient(trust_env=False) as browser:
        response = await browser.get(query["redirect_uri"][0], params={"state": query["state"][0], "code": "fixture"})
    assert response.status_code == 400
    assert mail.auth.read()["epoch"] == old_epoch and mail.auth.status()["connected"]
    assert not mail.status(store)["send_enabled"] and not fake.posts
    fake.scope += " " + GMAIL_SEND_SCOPE
    query = parse_qs(urlsplit((await mail.auth.start(scopes={GMAIL_SCOPE, GMAIL_SEND_SCOPE}))["url"]).query)
    async with httpx.AsyncClient(trust_env=False) as browser:
        response = await browser.get(query["redirect_uri"][0], params={"state": query["state"][0], "code": "fixture"})
    assert response.status_code == 200 and mail.status(store)["send_enabled"]
    assert mail.status(store)["binding"] is None
    assert not fake.posts
    await mail.close()


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["edit", "delete", "scope", "epoch", "permission", "expired", "refresh"])
async def test_changed_authority_or_draft_rejected_before_post(tmp_path, vault, change):
    store, fake, mail, draft = await setup(tmp_path)
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    target = store
    if change == "edit":
        Drafts(store).save(DraftBody(to_addresses=["another@example.test"]), draft["id"], draft["updated"])
    elif change == "delete": Drafts(store).remove(draft["id"], draft["updated"])
    elif change == "scope":
        spaces = Spaces(store)
        target = store.for_chat(spaces.create_chat(spaces.create_project("Другое")["id"])["id"])
    elif change == "epoch": mail.auth.write({**mail.auth.read(), "epoch": "changed"})
    elif change == "permission": mail.auth.write({**mail.auth.read(), "granted_scopes": [GMAIL_SCOPE]})
    elif change == "expired": mail.tickets[preview["ticket"]]["expires"] = 0
    elif change == "refresh":
        mail.auth.write({**mail.auth.read(), "expires_at": 0})
        fake.scope = GMAIL_SCOPE
    with pytest.raises(ValueError):
        await mail.sender.confirm(target, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert not fake.posts
    await mail.close()


@pytest.mark.anyio
async def test_two_previews_cannot_send_same_revision_twice(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path)
    previews = [await mail.sender.preview(store, draft["id"], draft["updated"]) for _ in range(2)]
    results = await asyncio.gather(*(mail.sender.confirm(store, ConfirmBody(ticket=item["ticket"], confirmed=True)) for item in previews), return_exceptions=True)
    assert sum(isinstance(item, ValueError) for item in results) == 1
    assert len(fake.posts) == 1
    await mail.close()


@pytest.mark.anyio
async def test_lost_response_is_persisted_and_reconciled_without_resend(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path)
    fake.lose = True
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    result = await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert result["state"] == "unknown"
    restarted = Mail(store, mail.auth)
    with pytest.raises(ValueError, match="заблокирована"):
        await restarted.sender.preview(store, draft["id"], draft["updated"])
    assert (await restarted.sender.check(store, draft["id"]))["state"] == "sent"
    assert len(fake.posts) == 1
    await mail.close()


@pytest.mark.anyio
async def test_rejection_can_retry_but_wrong_confirmation_cannot(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path)
    fake.fail = 403
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    result = await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert result["state"] == "failed" and "must-not-leak" not in str(result)
    fake.fail, fake.mismatch = None, True
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    result = await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert result["state"] == "unknown"
    assert (await mail.sender.check(store, draft["id"]))["state"] == "unknown"
    with pytest.raises(ValueError): await mail.sender.preview(store, draft["id"], draft["updated"])
    assert len(fake.posts) == 2
    await mail.close()


@pytest.mark.anyio
async def test_reply_source_account_and_thread_are_checked(tmp_path, vault):
    store, fake, mail, _ = await setup(tmp_path)
    draft = Drafts(store).save(DraftBody(to_addresses=["author@example.test"], subject="Re: Встреча", body="Ответ"), source=DraftSource(source_account="owner@example.test", source_message_id="abc123", in_reply_to="<original@example.test>"))
    preview = await mail.sender.preview(store, draft["id"], draft["updated"])
    await mail.sender.confirm(store, ConfirmBody(ticket=preview["ticket"], confirmed=True))
    assert fake.posts[0]["threadId"] == "aaa111"
    parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(fake.posts[0]["raw"]))
    assert str(parsed["In-Reply-To"]) == "<original@example.test>"
    draft = Drafts(store).save(DraftBody(to_addresses=["author@example.test"]))
    fake.account = "different@example.test"
    with pytest.raises(ValueError, match="отправителя изменился"):
        await mail.sender.preview(store, draft["id"], draft["updated"])
    assert len(fake.posts) == 1
    await mail.close()


@pytest.mark.anyio
async def test_http_send_requires_review_and_explicit_confirmation(tmp_path, vault):
    store, fake, mail, draft = await setup(tmp_path)
    token = "mail-send-api-fixture-0123456789"
    app = create_app(tmp_path, token)
    app.state.mail.auth = mail.auth
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        path = "/mail/drafts/" + draft["id"]
        assert (await client.post("/mail/send", json={"ticket": "invented", "confirmed": True})).status_code == 401
        client.headers["Authorization"] = "Bearer " + token
        response = await client.post(path + "/send-preview", json={"expected_updated": draft["updated"]})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        preview = response.json()
        assert not fake.posts
        assert (await client.post("/mail/send", json={"ticket": preview["ticket"], "confirmed": False})).status_code == 400
        response = await client.post("/mail/send", json={"ticket": preview["ticket"], "confirmed": True})
        assert response.status_code == 200 and response.json()["state"] == "sent"
        assert (await client.get(path + "/delivery")).json()["state"] == "sent"
        assert (await client.post("/mail/send", json={"ticket": preview["ticket"], "confirmed": True})).status_code == 400
        assert len(fake.posts) == 1
    await app.state.mail.close()
