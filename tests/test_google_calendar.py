import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import httpx
import pytest

from core.api import create_app
from core.backups import Backups
from core.calendar import Calendar, EventBody
from core.chatspaces import Spaces
from core.google_calendar import GoogleCalendar, GoogleChoice, digest, event_body, google_body
from core.google_calendar_auth import GoogleAuth, SCOPES, TOKEN_URL
from core.storage import Store

RANGE = ("2026-10-19T00:00Z", "2026-10-26T00:00Z")
CLIENT = {"installed": {"client_id": "1234567890-desktopfixture.apps.googleusercontent.com", "client_secret": "fixture-client-secret",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URL}}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def vault(monkeypatch):
    values = {}
    monkeypatch.setattr("core.google_calendar_auth.keyring.get_password", lambda service, key: values.get((service,key)))
    monkeypatch.setattr("core.google_calendar_auth.keyring.set_password", lambda service,key,value: values.__setitem__((service,key),value))
    return values


def local_body(**changes):
    return EventBody(**{**dict(title="План", starts_at="2026-10-20T10:00Z", ends_at="2026-10-20T11:00Z", timezone="UTC"), **changes})


def remote_event(event_id="google-event", **changes):
    return {**dict(id=event_id, etag='"v1"', status="confirmed", **google_body(local_body())), **changes}


class FakeGoogle:
    def __init__(self):
        self.events = {}
        self.calls = []
        self.insert_timeout = False
        self.bad_confirmation = False
        self.patch_precondition = False
        self.expired = False
        self.role = "owner"
        self.fail_before_insert = False
        self.tokens = {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600,
                       "token_type": "Bearer", "scope": " ".join(sorted(SCOPES))}

    def handle(self, request):
        self.calls.append(request)
        path = request.url.path
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json=self.tokens)
        assert request.headers["authorization"] == "Bearer fixture-access"
        if self.expired:
            return httpx.Response(401, json={"access_token": "should-not-be-exposed"})
        if path.endswith("/calendarList"):
            return httpx.Response(200, json={"items": [{"id": "primary@example.test", "summary": "Личный", "timeZone": "UTC", "accessRole": self.role}]})
        if path.endswith("/events"):
            if request.method == "GET":
                return httpx.Response(200, json={"items": list(self.events.values())})
            assert request.method == "POST"
            if self.fail_before_insert:
                return httpx.Response(503, json={})
            assert request.url.params["sendUpdates"] == "none"
            body = json.loads(request.content)
            event_id = body["id"]
            if event_id in self.events:
                return httpx.Response(409, json={})
            self.events[event_id] = {**body,"etag": '"inserted"',"status": "confirmed"}
            if self.bad_confirmation:
                self.events[event_id]["summary"] = "Не сохранилось"
            if self.insert_timeout:
                raise httpx.ReadTimeout("fixture unknown-result", request=request)
            return httpx.Response(200, json=self.events[event_id])
        event_id = path.rsplit("/",1)[1]
        if event_id not in self.events:
            return httpx.Response(404, json={})
        if request.method == "PATCH":
            assert request.headers["if-match"] == self.events[event_id]["etag"]
            if self.patch_precondition:
                return httpx.Response(412, json={})
            self.events[event_id] = {**self.events[event_id], **json.loads(request.content), "etag": '"changed"'}
        return httpx.Response(200, json=self.events[event_id])


async def configured(store, fake):
    auth = GoogleAuth(store.root, httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)))
    await auth.configure(json.dumps(CLIENT))
    auth.write({**auth.read(), **auth.token_values(fake.tokens)})
    manager = GoogleCalendar(store, auth)
    await manager.bind(store,"primary@example.test")
    return manager


@pytest.mark.anyio
async def test_oauth_loopback_pkce_state_replay_and_no_secret_leak(tmp_path, vault):
    fake = FakeGoogle()
    auth = GoogleAuth(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)))
    await auth.configure(json.dumps(CLIENT))
    login = await auth.start()
    query = parse_qs(urlsplit(login["url"]).query)
    assert query["code_challenge_method"] == ["S256"] and "code_verifier" not in query and "client_secret" not in query
    assert set(query["scope"][0].split()) == SCOPES
    redirect = query["redirect_uri"][0]
    async with httpx.AsyncClient(trust_env=False) as browser:
        response = await browser.get(redirect, params={"state":"wrong", "code":"private-code"})
        assert response.status_code == 400 and auth.pending
        response = await browser.get(redirect, params={"state":query["state"][0], "code":"private-code"})
        assert response.status_code == 200 and "private-code" not in response.text
    assert auth.status()["connected"] and not auth.pending
    assert "fixture" not in json.dumps(auth.status())
    token_request = fake.calls[-1]
    assert "code_verifier=" in token_request.content.decode()
    with pytest.raises(httpx.ConnectError):
        async with httpx.AsyncClient(trust_env=False) as browser:
            await browser.get(redirect,params={"state":query["state"][0],"code":"private-code"})
    await auth.close()


@pytest.mark.anyio
async def test_partial_permissions_refresh_cancel_and_root_isolation(tmp_path, vault):
    fake = FakeGoogle()
    fake.tokens["scope"] = next(iter(SCOPES))
    auth = GoogleAuth(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)))
    await auth.configure(json.dumps(CLIENT))
    query = parse_qs(urlsplit((await auth.start())["url"]).query)
    async with httpx.AsyncClient(trust_env=False) as browser:
        response = await browser.get(query["redirect_uri"][0],params={"state":query["state"][0],"code":"code"})
    assert response.status_code == 400 and not auth.status()["connected"] and "Разрешите" in auth.error
    auth.write({**auth.read(),"refresh_token":"old-refresh","expires_at":0})
    fake.tokens.pop("refresh_token")
    token, _ = await auth.access()
    assert token == "fixture-access" and auth.read()["refresh_token"] == "old-refresh"
    other = GoogleAuth(tmp_path / "other")
    assert not other.status()["configured"]
    await auth.start()
    await auth.close()
    assert not auth.pending
    await auth.disconnect()
    assert not auth.status()["connected"]


@pytest.mark.parametrize("document", ["{}", '{"web":{}}', '{"installed":{"client_id":"x"}}', json.dumps({"installed":{**CLIENT["installed"],"token_uri":"https://example.test/token"}}), "x"*17000], ids=["empty", "web", "invalid-id", "wrong-server", "oversized"])
@pytest.mark.anyio
async def test_untrusted_oauth_client_documents_rejected(tmp_path, vault, document):
    auth = GoogleAuth(tmp_path)
    with pytest.raises(ValueError): await auth.configure(document)
    assert not vault


@pytest.mark.parametrize("changes", [{}, {"all_day":True,"starts_at":"2026-10-20","ends_at":"2026-10-21"}, {"recurrence":{"rule":"weekdays","until":"2026-11-20"}}, {"recurrence":{"rule":"weekly","weekdays":[1,4]}}])
def test_google_format_roundtrip(changes):
    body = local_body(**changes)
    assert digest(event_body(google_body(body),"UTC")) == digest(body)


@pytest.mark.anyio
async def test_preview_has_no_external_writes_selected_import_export_restart(tmp_path,vault):
    store, fake = Store(tmp_path), FakeGoogle()
    fake.events["remote"] = remote_event("remote",summary="Из Google")
    local = Calendar(store).save(local_body())
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    assert {row["action"] for row in preview["rows"]} == {"import","export"}
    assert all(call.method == "GET" for call in fake.calls)
    choices = [GoogleChoice(id=row["id"],direction="google" if row["action"] == "import" else "local") for row in preview["rows"]]
    result = await manager.apply(store,preview["ticket"],choices)
    assert all(item["ok"] for item in result["results"])
    assert len(fake.events) == 2
    assert Calendar(store).list(*RANGE)["total"] == 2
    restarted = GoogleCalendar(Store(tmp_path),manager.auth)
    assert (await restarted.preview(store,*RANGE))["rows"] == []
    with pytest.raises(ValueError): await manager.apply(store,preview["ticket"],choices)


@pytest.mark.anyio
async def test_both_changed_conflict_requires_choice_and_etag(tmp_path,vault):
    store, fake = Store(tmp_path), FakeGoogle()
    local = Calendar(store).save(local_body())
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    event_id = next(iter(fake.events))
    fake.events[event_id].update(summary="Google-версия",etag='"v2"')
    Calendar(store).save(local_body(title="Локальная версия"),local["id"])
    preview = await manager.preview(store,*RANGE)
    row, = preview["rows"]
    assert row["action"] == "conflict"
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=row["id"],direction="google")])
    assert result["results"][0]["ok"]
    assert Calendar(store).get(local["id"])["title"] == "Google-версия"
    Calendar(store).save(local_body(title="Другая"),local["id"])
    preview = await manager.preview(store,*RANGE)
    fake.patch_precondition = True
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert not result["results"][0]["ok"] and "изменилось" in result["results"][0]["message"]


@pytest.mark.parametrize("change", ["local","remote","binding","restore"])
@pytest.mark.anyio
async def test_stale_previews_do_not_overwrite(tmp_path,vault,change):
    store, fake = Store(tmp_path), FakeGoogle()
    local = Calendar(store).save(local_body())
    fake.events["remote"] = remote_event("remote")
    manager = await configured(store,fake)
    if change in {"remote","local"}:
        preview = await manager.preview(store,*RANGE)
        export = next(row for row in preview["rows"] if row["action"] == "export")
        await manager.apply(store,preview["ticket"],[GoogleChoice(id=export["id"],direction="local")])
        Calendar(store).save(local_body(title="Изменено"),local["id"])
    preview = await manager.preview(store,*RANGE)
    row = next(row for row in preview["rows"] if row["action"] == "export") if change in {"local","remote"} else preview["rows"][0]
    if change == "local":
        original_remote = manager.remote
        async def edited_during_check(binding, event_id):
            result = await original_remote(binding, event_id)
            Calendar(store).save(local_body(title="Ещё правка"),local["id"])
            return result
        manager.remote = edited_during_check
    if change == "remote":
        for event in fake.events.values(): event["etag"] = '"v3"'
    if change == "binding": await manager.auth.disconnect()
    if change == "restore":
        backups = Backups(store)
        backups.restore(backups.preview(backups.export())["ticket"])
    if change in {"binding","restore"}:
        with pytest.raises(ValueError): await manager.apply(store,preview["ticket"],[GoogleChoice(id=row["id"],direction="local")])
    else:
        result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=row["id"],direction="local")])
        assert not result["results"][0]["ok"]


@pytest.mark.anyio
async def test_unknown_insert_result_reconciles_without_duplicate(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    Calendar(store).save(local_body())
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    fake.insert_timeout = True
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert not result["results"][0]["ok"] and len(fake.events) == 1
    assert (await manager.preview(store,*RANGE))["rows"] == []
    assert len(fake.events) == 1


@pytest.mark.anyio
async def test_wrong_confirmation_is_not_success_and_remote_deletions_not_propagated(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    local = Calendar(store).save(local_body())
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    fake.bad_confirmation = True
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert not result["results"][0]["ok"] and "не подтвердил" in result["results"][0]["message"]
    fake.bad_confirmation = False
    preview = await manager.preview(store,*RANGE)
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert result["results"][0]["ok"]
    fake.events.clear()
    preview = await manager.preview(store,*RANGE)
    assert preview["rows"] == [] and preview["skipped"]
    assert Calendar(store).get(local["id"])


@pytest.mark.anyio
async def test_google_binding_is_project_scoped_backup_never_contains_tokens(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    manager = await configured(store,fake)
    spaces = Spaces(store)
    chat = spaces.create_chat(spaces.create_project("Чужой")["id"])
    other = store.for_chat(chat["id"])
    assert not manager.status(other)["binding"]
    with pytest.raises(ValueError): await manager.bind(other,"primary@example.test")
    with pytest.raises(ValueError): await manager.preview(other,*RANGE)
    archive = Backups(store).export().decode()
    assert all(text not in archive for text in ("fixture-access","fixture-refresh","fixture-client-secret","google_calendar_links"))


def test_authenticated_api_and_scope(tmp_path,vault):
    token = "calendar-google-api-0123456789"
    with TestClient(create_app(tmp_path,token)) as api:
        assert api.get("/calendar/google/status").status_code == 401
        headers = {"Authorization":"Bearer " + token}
        assert api.get("/calendar/google/status",headers=headers).json()["connected"] is False
        assert api.put("/calendar/google/client",headers=headers,json={"document":json.dumps(CLIENT)}).status_code == 200
        assert api.get("/calendar/google/status",headers=headers).json()["configured"] is True
        assert api.post("/calendar/google/preview",headers=headers,json=dict(zip(("start","end"),RANGE))).status_code == 400
        assert api.post("/calendar/google/disconnect",headers=headers).status_code == 200


@pytest.mark.anyio
async def test_failed_insert_can_retry_and_relogin_preserves_links(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    Calendar(store).save(local_body())
    manager = await configured(store,fake)
    original_binding = manager.binding(store)["id"]
    preview = await manager.preview(store,*RANGE)
    fake.fail_before_insert = True
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert not result["results"][0]["ok"] and not fake.events
    preview = await manager.preview(store,*RANGE)
    assert len(preview["rows"]) == 1
    fake.fail_before_insert = False
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert result["results"][0]["ok"] and len(fake.events) == 1
    await manager.auth.disconnect()
    manager.auth.write({**manager.auth.read(), **manager.auth.token_values(fake.tokens)})
    assert not manager.status(store)["binding"]
    await manager.bind(store,"primary@example.test")
    assert manager.binding(store)["id"] == original_binding
    assert not (await manager.preview(store,*RANGE))["rows"]


@pytest.mark.anyio
async def test_two_import_previews_do_not_create_duplicates(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    fake.events["remote"] = remote_event("remote")
    manager = await configured(store,fake)
    previews = [await manager.preview(store,*RANGE),await manager.preview(store,*RANGE)]
    for index,preview in enumerate(previews):
        result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="google")])
        assert result["results"][0]["ok"] == (index == 0)
    assert Calendar(store).list(*RANGE)["total"] == 1


@pytest.mark.anyio
async def test_read_only_calendar_imports_without_upload(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    fake.role = "reader"
    fake.events["remote"] = remote_event("remote")
    Calendar(store).save(local_body(title="Остаётся локально"))
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    assert [row["action"] for row in preview["rows"]] == ["import"]
    assert all(call.method == "GET" for call in fake.calls)


@pytest.mark.parametrize("changes", [
    {"start":"invalid"}, {"summary":"x"*201}, {"recurrence":["RRULE:FREQ=YEARLY"]},
    {"recurrence":["RRULE:FREQ=DAILY;COUNT=5"]}, {"eventType":"birthday"}, {"etag":""},
])
@pytest.mark.anyio
async def test_unsupported_remote_event_is_visible_as_skipped(tmp_path,vault,changes):
    store,fake = Store(tmp_path),FakeGoogle()
    fake.events["remote"] = remote_event("remote",**changes)
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    assert not preview["rows"] and preview["skipped"]
    assert not Calendar(store).list(*RANGE)["events"]


@pytest.mark.anyio
async def test_local_series_exports_master_not_each_occurrence(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    Calendar(store).save(local_body(recurrence={"rule":"daily","until":"2026-11-20"}))
    manager = await configured(store,fake)
    preview = await manager.preview(store,*RANGE)
    assert len(preview["rows"]) == 1
    row = preview["rows"][0]
    assert row["local_version"]["recurrence"]["until"] == "2026-11-20"
    result = await manager.apply(store,preview["ticket"],[GoogleChoice(id=row["id"],direction="local")])
    assert result["results"][0]["ok"] and len(fake.events) == 1
    assert next(iter(fake.events.values()))["recurrence"] == ["RRULE:FREQ=DAILY;UNTIL=20261120T235959Z"]


@pytest.mark.anyio
async def test_pagination_failure_and_provider_errors_are_not_empty_success(tmp_path,vault):
    store,fake = Store(tmp_path),FakeGoogle()
    manager = await configured(store,fake)
    def repeated_page(request):
        return httpx.Response(200,json={"items":[],"nextPageToken":"same"})
    manager.auth.client = httpx.AsyncClient(transport=httpx.MockTransport(repeated_page))
    with pytest.raises(ValueError,match="не получен полностью"): await manager.preview(store,*RANGE)
    manager.auth.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    fake.expired = True
    with pytest.raises(ValueError,match="отклонил доступ") as error: await manager.preview(store,*RANGE)
    assert "should-not-be-exposed" not in str(error.value)
