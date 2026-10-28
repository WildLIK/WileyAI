import asyncio
import copy
import json

import httpx
import pytest

from core.api import create_app
from core.backups import Backups
from core.chatspaces import Spaces
from core.home_assistant import HomeAssistant, ConnectionBody, AccessBody, HomeAction, server_url
from core import home_assistant_chat as chat
from core.storage import Store


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.fixture
def vault(monkeypatch):
    values = {}
    monkeypatch.setattr("core.home_assistant.keyring.get_password", lambda service, key: values.get((service, key)))
    monkeypatch.setattr("core.home_assistant.keyring.set_password", lambda service, key, value: values.__setitem__((service, key), value))
    return values


class House:
    def __init__(self):
        self.rows = {
            "light.kitchen": {"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Кухня", "supported_color_modes": ["brightness"], "private": "not-exposed"}},
            "fan.study": {"entity_id": "fan.study", "state": "off", "attributes": {"friendly_name": "Вентилятор", "percentage": 0}},
            "sensor.room": {"entity_id": "sensor.room", "state": "22.5", "attributes": {"friendly_name": "Температура", "unit_of_measurement": "°C"}},
        }
        self.posts, self.requests = [], []
        self.fail, self.lose, self.ignore = None, False, False
        self.started, self.release = asyncio.Event(), None

    async def handle(self, request):
        assert request.headers["authorization"] == "Bearer fixture-token-value"
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "POST":
            body = json.loads(request.content)
            self.posts.append((path, body))
            self.started.set()
            if self.release: await self.release.wait()
            if self.fail: return httpx.Response(self.fail, json={"private": "not-exposed"})
            if not self.ignore:
                state = self.rows[body["entity_id"]]
                state["state"] = "off" if path.endswith("/turn_off") or body.get("percentage") == 0 else "on"
                for key in ("brightness", "percentage"):
                    if key in body: state["attributes"][key] = body[key]
            if self.lose: raise httpx.ReadTimeout("not-exposed", request=request)
            return httpx.Response(200, json=[])
        if path == "/api/": return httpx.Response(200, json={"message": "API running."})
        if path == "/api/config": return httpx.Response(200, json={"version": "2026.10.fixture", "location_name": "Тестовый дом"})
        if path == "/api/services": return httpx.Response(200, json=[{"domain": domain, "services": {name: {} for name in names}} for domain, names in {"light": ["turn_on", "turn_off"], "fan": ["turn_on", "turn_off", "set_percentage"]}.items()])
        if path == "/api/states": return httpx.Response(200, json=list(self.rows.values()))
        if path.startswith("/api/states/"):
            row = self.rows.get(path.removeprefix("/api/states/"))
            return httpx.Response(200 if row else 404, json=row)
        raise AssertionError(path)


async def setup(tmp_path, *, access=True):
    store = Store(tmp_path)
    house = House()
    home = HomeAssistant(store, httpx.AsyncClient(transport=httpx.MockTransport(house.handle)))
    home.poll_delays = (0, 0, 0)
    await home.configure(store, ConnectionBody(url="http://house.local:8123/", token="fixture-token-value"))
    if access: await home.access(store, AccessBody(enabled=True, entities=list(house.rows), expected_revision=""))
    return store, house, home


@pytest.mark.parametrize("value", ["file:///test", "http://user:pass@home:8123", "http://home/api", "http://home/lovelace/0", "http://home/a/../b", "http://home?token=secret", "http://home/#page", "http://home/%2e%2e", "http://home:99999", "http://home\n", "http://home\\evil"])
def test_invalid_server_address(value):
    with pytest.raises(ValueError): server_url(value)


@pytest.mark.anyio
async def test_connection_verified_before_save_and_secret_not_exposed(tmp_path, vault):
    store, house, home = await setup(tmp_path, access=False)
    status = home.status(store)
    assert status["configured"] and status["url"] == "http://house.local:8123" and status["checked_at"]
    assert status["binding"] == {"enabled": False, "entities": [], "revision": ""}
    assert "fixture-token" not in json.dumps(status)
    assert not HomeAssistant(Store(tmp_path / "other")).status(Store(tmp_path / "other"))["configured"]
    saved = copy.deepcopy(vault)
    async def reject(request): return httpx.Response(401, json={"secret": "not-exposed"})
    await home.client.aclose()
    home.client = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    with pytest.raises(ValueError, match="токен"): await home.configure(store, ConnectionBody(url="http://other.local", token="fixture-token-value"))
    assert vault == saved
    home.disconnect(store)
    assert not home.status(store)["configured"]
    await home.close()


@pytest.mark.anyio
async def test_review_consent_state_verification_and_duplicate(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    rows = (await home.entities(store))["entities"]
    assert "not-exposed" not in json.dumps(rows)
    assert rows[0]["actions"] == ["on", "off", "brightness"]
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="brightness", value=30))
    assert not house.posts
    with pytest.raises(ValueError, match="Подтвердите"): await home.confirm(store, preview["ticket"], False)
    receipt = await home.confirm(store, preview["ticket"], True)
    assert receipt["state"] == "verified" and "яркость 30%" in receipt["text"]
    assert house.posts == [("/api/services/light/turn_on", {"entity_id": "light.kitchen", "brightness": 76})]
    with pytest.raises(ValueError): await home.confirm(store, preview["ticket"], True)
    repeated = await home.preview(store, HomeAction(entity_id="light.kitchen", action="brightness", value=30))
    assert repeated["already"]
    assert (await home.confirm(store, repeated["ticket"], True))["state"] == "verified"
    assert len(house.posts) == 1
    assert len(HomeAssistant(store).history(store)) == 2
    await home.close()


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["state", "access", "epoch", "expired", "chat", "project"])
async def test_review_invalidated_by_change_or_wrong_scope(tmp_path, vault, change):
    store, house, home = await setup(tmp_path)
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    target = store
    if change == "state": house.rows["light.kitchen"]["state"] = "on"
    if change == "access": await home.access(store, AccessBody(enabled=False, entities=list(house.rows), expected_revision=home.binding(store)["revision"]))
    if change == "epoch": home.write({**home.read(), "epoch": "different"})
    if change == "expired": home.tickets[preview["ticket"]]["expires"] = 0
    if change in {"chat", "project"}:
        spaces = Spaces(store)
        project_id = spaces.create_project("Другой")["id"] if change == "project" else None
        target = store.for_chat(spaces.create_chat(project_id)["id"])
    with pytest.raises(ValueError): await home.confirm(target, preview["ticket"], True)
    assert not house.posts
    await home.close()


@pytest.mark.anyio
async def test_readonly_unsupported_offline_and_access_cas(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    with pytest.raises(ValueError, match="чтения"): await home.preview(store, HomeAction(entity_id="sensor.room", action="on"))
    with pytest.raises(ValueError): await home.access(store, AccessBody(enabled=True, entities=[], expected_revision="old"))
    house.rows["light.kitchen"]["state"] = "unavailable"
    with pytest.raises(ValueError, match="недоступно"): await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    house.rows["light.kitchen"]["state"] = "off"
    house.rows["light.kitchen"]["attributes"]["supported_color_modes"] = ["onoff"]
    with pytest.raises(ValueError, match="яркости"): await home.preview(store, HomeAction(entity_id="light.kitchen", action="brightness", value=30))
    preview = await home.preview(store, HomeAction(entity_id="fan.study", action="speed", value=50))
    assert (await home.confirm(store, preview["ticket"], True))["state"] == "verified"
    assert house.posts[0][1] == {"entity_id": "fan.study", "percentage": 50}
    await home.close()


@pytest.mark.anyio
@pytest.mark.parametrize("mode,expected", [("lost", "unknown"), ("ignored", "unknown"), ("denied", "failed"), ("server_error", "unknown")])
async def test_failure_is_not_success_and_check_never_resends(tmp_path, vault, mode, expected):
    store, house, home = await setup(tmp_path)
    house.lose, house.ignore = mode == "lost", mode == "ignored"
    house.fail = 403 if mode == "denied" else 500 if mode == "server_error" else None
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    result = await home.confirm(store, preview["ticket"], True)
    assert result["state"] == expected and "подтвердил состояние" not in result["text"]
    assert "not-exposed" not in json.dumps(result)
    checked = await home.check(store, result["id"])
    assert checked["state"] == ("verified" if mode == "lost" else expected)
    assert len(house.posts) == 1
    await home.close()


@pytest.mark.anyio
async def test_cancelled_http_or_chat_wait_finishes_once_and_journals_result(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    house.release = asyncio.Event()
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    progress = []
    operation = asyncio.create_task(home.dispatch(store, preview["ticket"], True, progress))
    await house.started.wait()
    operation.cancel()
    house.release.set()
    with pytest.raises(asyncio.CancelledError): await operation
    assert len(house.posts) == 1 and "подтвердил состояние" in progress[0]
    assert home.history(store)[0]["state"] == "verified"
    await home.close()


@pytest.mark.anyio
async def test_redirects_and_large_or_invalid_responses_are_not_trusted(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    for response in [httpx.Response(302, headers={"Location": "http://other.local"}), httpx.Response(200, content=b"bad json"), httpx.Response(200, content=b"x" * (8 * 1024 * 1024 + 1))]:
        calls = []
        async def handle(request): calls.append(request); return response
        await home.client.aclose()
        home.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with pytest.raises(ValueError): await home.check_connection()
        assert len(calls) == 1 and calls[0].url.host == "house.local"
    with pytest.raises(ValueError): await home.call(home.credentials(), "POST", "states/light.kitchen", json={"state": "on"})
    await home.close()


@pytest.mark.parametrize("text", ['«умный дом, включи Кухня»', "Расскажи про умный дом", "включи Кухня", "В документе написано: умный дом, включи Кухня"])
def test_prose_and_quotes_are_not_commands(text): assert chat.request(text) is None


@pytest.mark.anyio
async def test_chat_selection_exact_confirmation_and_real_state(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    house.rows["light.dining"] = {"entity_id": "light.dining", "state": "off", "attributes": {"friendly_name": "Кухня стол"}}
    house.rows["light.kitchen"]["attributes"]["friendly_name"] = "Кухня потолок"
    await home.access(store, AccessBody(enabled=True, entities=list(house.rows), expected_revision=home.binding(store)["revision"]))
    result = await chat.handle(home, store, chat.request("Уайли, умный дом, включи Кухня"), [])
    assert "несколько" in result and not house.posts
    result = await chat.handle(home, store, chat.request("умный дом, выбери 1"), [])
    assert "подтверждаю умный дом" in result and not house.posts
    other = store.for_chat(Spaces(store).create_chat(None)["id"])
    assert "Нет подготовленного" in await chat.handle(home, other, chat.request("подтверждаю умный дом"), [])
    result = await chat.handle(home, store, chat.request("подтверждаю умный дом"), [])
    assert "подтвердил состояние" in result and len(house.posts) == 1
    await chat.handle(home, store, chat.request("умный дом, выключи Кухня потолок"), [])
    await chat.handle(home, store, chat.request("отмена умный дом"), [])
    assert "Нет подготовленного" in await chat.handle(home, store, chat.request("подтверждаю умный дом"), [])
    await home.close()


@pytest.mark.anyio
async def test_api_auth_redacted_validation_scopes_and_chat_never_calls_model(tmp_path, vault):
    token = "a" * 32
    app = create_app(tmp_path, token)
    home = app.state.home_assistant
    house = House()
    home.client = httpx.AsyncClient(transport=httpx.MockTransport(house.handle))
    home.poll_delays = (0, 0, 0)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/home-assistant/status")).status_code == 401
        client.headers["Authorization"] = "Bearer " + token
        secret = "sensitive-token pasted with spaces"
        bad = await client.put("/home-assistant/connection", json={"url": "http://house.local", "token": secret})
        assert bad.status_code == 400 and secret not in bad.text and "input" not in bad.text
        response = await client.put("/home-assistant/connection", json={"url": "http://house.local", "token": "fixture-token-value"})
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert "fixture-token" not in response.text
        access = await client.put("/home-assistant/access", json={"enabled": True, "entities": ["light.kitchen"], "expected_revision": ""})
        assert access.status_code == 200
        for phrase in ["умный дом, включи Кухня", "подтверждаю умный дом"]:
            response = await client.post("/chat", json={"text": phrase})
            assert response.status_code == 200 and '"type": "done"' in response.text
            assert "Модель не" not in response.text
        assert len(house.posts) == 1
        assert (await client.get("/home-assistant/actions")).json()[0]["state"] == "verified"
        project = Spaces(app.state.store).create_project("Другой")
        conversation = Spaces(app.state.store).create_chat(project["id"])
        assert (await client.get("/home-assistant/status", params={"conversation_id": conversation["id"]})).json()["binding"]["entities"] == []
    await home.close()


@pytest.mark.anyio
async def test_restore_revokes_old_review_and_never_transports_credentials(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    manager = Backups(store)
    archive = manager.export()
    assert b"fixture-token" not in archive and b"home_bindings" not in archive and b"home_actions" not in archive
    manager.restore(manager.preview(archive)["ticket"])
    assert not home.binding(store)["enabled"]
    with pytest.raises(ValueError): await home.confirm(store, preview["ticket"], True)
    assert not house.posts and home.status(store)["configured"]
    await home.close()


@pytest.mark.anyio
async def test_project_removal_discards_access_and_journal(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    spaces = Spaces(store)
    project = spaces.create_project("Дом")
    target = store.for_chat(spaces.create_chat(project["id"])["id"])
    await home.access(target, AccessBody(enabled=True, entities=["light.kitchen"], expected_revision=""))
    preview = await home.preview(target, HomeAction(entity_id="light.kitchen", action="on"))
    await home.confirm(target, preview["ticket"], True)
    spaces.delete_project(project["id"])
    with store.db() as db:
        assert not db.execute("SELECT 1 FROM home_bindings WHERE scope_id=?", (project["id"],)).fetchone()
        assert not db.execute("SELECT 1 FROM home_actions WHERE scope_id=?", (project["id"],)).fetchone()
    assert home.binding(store)["enabled"]
    await home.close()


@pytest.mark.anyio
async def test_bad_entity_row_long_object_id_out_of_range_percent_and_history(tmp_path, vault):
    store, house, home = await setup(tmp_path)
    long_id = "light." + "a" * 200
    house.rows[long_id] = {"entity_id": long_id, "state": "off", "attributes": {"friendly_name": "Длинная лампа"}}
    house.rows["broken"] = {"entity_id": "Not An Entity", "state": "on", "attributes": {}}
    visible = {row["entity_id"] for row in (await home.entities(store))["entities"]}
    assert long_id in visible and "light.kitchen" in visible and "Not An Entity" not in visible
    result = await chat.handle(home, store, chat.request("умный дом, яркость Кухня на 150"), [])
    assert "от 0 до 100" in result and not house.posts
    preview = await home.preview(store, HomeAction(entity_id="light.kitchen", action="on"))
    await home.confirm(store, preview["ticket"], True)
    history = home.history(store)
    assert len(history) == 1 and history[0]["state"] == "verified" and "Кухня" in history[0]["text"]
    await home.close()
