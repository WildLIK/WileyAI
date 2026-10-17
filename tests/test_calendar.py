from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.backups import Backups, encode, parse
from core.calendar import Calendar, EventBody
from core.calendar_workflows import CalendarWorkflows
from core.chatspaces import Spaces
from core.storage import Store
from core import providers
from core import calendar as calendar_module
from core.workflows import Workflows

ZONE = "Asia/Yekaterinburg"
NOW = datetime(2026, 10, 16, 9, tzinfo=ZoneInfo(ZONE))
TOKEN = "calendar-tests-token-0123456789"
RANGE = ("2026-10-16T00:00:00+05:00", "2026-10-23T00:00:00+05:00")


def body(**changes):
    return EventBody(**{**dict(title="Обсуждение проекта", starts_at="2026-10-17T10:00", ends_at="2026-10-17T11:00", timezone=ZONE), **changes})


def test_crud_persistence_range_edges_conflicts_and_stale_edit(tmp_path):
    calendar = Calendar(Store(tmp_path))
    first = calendar.save(body())
    assert first["starts_at"] == "2026-10-17T05:00:00.000000+00:00"
    # Adjacent intervals do not overlap; an event spanning the view boundary is included.
    calendar.save(body(title="Следующая", starts_at="2026-10-17T11:00", ends_at="2026-10-17T12:00"))
    assert not any(row["conflict"] for row in calendar.list(*RANGE)["events"])
    other = calendar.save(body(title="Пересечение", starts_at="2026-10-17T10:30", ends_at="2026-10-17T11:30"))
    assert all(row["conflict"] for row in calendar.list(*RANGE)["events"])
    assert calendar.list(first["ends_at"], "2026-10-18T00:00:00Z")["total"] == 2
    limited = calendar.list(*RANGE, limit=1)
    assert len(limited["events"]) == 1 and limited["total"] == 3
    revised = calendar.save(body(title="Изменено"), first["id"], first["updated"])
    with pytest.raises(ValueError, match="изменилось"):
        calendar.save(body(), first["id"], first["updated"])
    with pytest.raises(ValueError, match="изменилось"):
        calendar.remove(first["id"], first["updated"])
    calendar.remove(first["id"], revised["updated"])
    with pytest.raises(ValueError, match="удалено"):
        calendar.save(body(), first["id"])
    assert Calendar(Store(tmp_path)).get(other["id"]) == other


@pytest.mark.parametrize("changes", [
    {"title": "   "}, {"timezone": "Europe/Unknown"}, {"starts_at": "2026-10-17"},
    {"ends_at": "2026-10-17T10:00"}, {"ends_at": "2026-10-17T09:00"},
    {"ends_at": "2026-12-17T11:00"},
    {"timezone": "Europe/Berlin", "starts_at": "2026-03-29T02:30", "ends_at": "2026-03-29T04:00"},
    {"timezone": "Europe/Berlin", "starts_at": "2026-10-25T02:30", "ends_at": "2026-10-25T04:00"},
])
def test_invalid_wall_time_and_intervals(changes):
    with pytest.raises(ValueError):
        body(**changes)


def test_explicit_dst_offset_and_real_duration():
    event = body(timezone="Europe/Berlin", starts_at="2026-10-25T02:30+02:00", ends_at="2026-10-25T02:30+01:00")
    assert datetime.fromisoformat(event.ends_at) - datetime.fromisoformat(event.starts_at) == timedelta(hours=1)


def test_revision_guard_with_frozen_windows_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_module, "now", lambda: NOW.isoformat())
    calendar = Calendar(Store(tmp_path))
    first = calendar.save(body())
    second = calendar.save(body(title="Правка"), first["id"], first["updated"])
    assert datetime.fromisoformat(second["updated"]) > datetime.fromisoformat(first["updated"])
    with pytest.raises(ValueError, match="изменилось"):
        calendar.save(body(title="Устаревшая"), first["id"], first["updated"])


@pytest.mark.parametrize("start,end", [(RANGE[1], RANGE[0]), ("2026-10-16T00:00", RANGE[1]), (RANGE[0], "2029-10-16T00:00Z")])
def test_invalid_view_range(tmp_path, start, end):
    with pytest.raises(ValueError):
        Calendar(Store(tmp_path)).list(start, end)


def test_project_isolation_move_delete_and_stale_scope(tmp_path):
    store = Store(tmp_path)
    spaces = Spaces(store)
    project = spaces.create_project("Работа")
    chat = spaces.create_chat(project["id"])
    second = spaces.create_chat(project["id"])
    scoped = store.for_chat(chat["id"])
    event = Calendar(scoped).save(body())
    assert Calendar(store).list(*RANGE)["total"] == 0
    assert Calendar(store.for_chat(second["id"])).get(event["id"])
    with pytest.raises(ValueError): Calendar(store).remove(event["id"])
    spaces.update_chat(chat["id"], "Общий", None)
    assert Calendar(store.for_chat(chat["id"])).list(*RANGE)["total"] == 0
    with pytest.raises(ValueError, match="перемещён"): Calendar(scoped).save(body())
    with pytest.raises(ValueError, match="перемещён"): Calendar(scoped).list(*RANGE)
    spaces.delete_chat(second["id"])
    remaining = spaces.create_chat(project["id"])
    assert Calendar(store.for_chat(remaining["id"])).get(event["id"])
    spaces.delete_project(project["id"])
    with store.db() as db: assert db.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 0
    with pytest.raises(ValueError): Calendar(scoped).save(body())


@pytest.mark.parametrize("text,minutes", [
    ("Создай встречу Обзор завтра в 10 на 30 минут", 30),
    ("Уайли, пожалуйста, запланируй встречу Обзор завтра в десять на полчаса", 30),
    ("Добавь в календарь Обзор завтра в 10 на один час тридцать минут", 90),
    ("Добавь событие Обзор завтра в 10", 60),
])
def test_create_and_move_chat_without_llm(tmp_path, text, minutes):
    store = Store(tmp_path)
    handle = lambda value: CalendarWorkflows(store).handle(value, ZONE, NOW)
    result = handle(text)
    assert result.changed == ["calendar"] and "уведомление не установлено" in result.text
    event, = Calendar(store).list(*RANGE)["events"]
    assert event["title"] == "Обзор"
    duration = lambda item: datetime.fromisoformat(item["ends_at"]) - datetime.fromisoformat(item["starts_at"])
    assert duration(event) == timedelta(minutes=minutes)
    assert handle("перенеси встречу на 11").changed == ["calendar"]
    revised = Calendar(store).get(event["id"])
    assert revised["starts_at"] == "2026-10-17T06:00:00.000000+00:00" and duration(revised) == duration(event)
    assert "Обзор" in handle("что у меня в календаре завтра?").text
    assert handle("отмени встречу").changed == ["calendar"]
    assert Calendar(store).list(*RANGE)["total"] == 0 and store.list("tasks") == []


def test_clarification_expiry_and_task_interoperation(tmp_path):
    store = Store(tmp_path)
    Workflows(store).handle("напомни купить хлеб", ZONE, NOW)
    assert store.dialogue().get("pending")
    result = CalendarWorkflows(store).handle("создай встречу Обзор завтра", ZONE, NOW)
    assert "Когда" in result.text and not store.dialogue().get("pending")
    result = CalendarWorkflows(Store(tmp_path)).handle("в 10", ZONE, NOW)
    assert result.changed == ["calendar"]
    assert "Нет" not in CalendarWorkflows(store).handle("покажи расписание на неделю", ZONE, NOW).text
    assert CalendarWorkflows(store).handle("перенеси встречу на 12", ZONE, NOW + timedelta(minutes=16)).changed == []
    # A new task remains a task, and cannot fill an abandoned calendar draft.
    CalendarWorkflows(store).handle("создай встречу Еще одна", ZONE, NOW)
    assert CalendarWorkflows(store).handle("напомни завтра в 12 хлеб", ZONE, NOW) is None
    assert Workflows(store).handle("напомни завтра в 12 хлеб", ZONE, NOW).changed == ["tasks"]
    assert CalendarWorkflows(store).handle("в 13", ZONE, NOW) is None


@pytest.mark.parametrize("text", [
    "Не создавай встречу Обзор завтра в 10", '«создай встречу Обзор завтра в 10»',
    "Как создать встречу завтра в 10?", "создай встречу Обзор завтра в 25",
    "создай встречу Обзор завтра в 10 или в 11", "создай встречу Обзор каждый день в 10",
    "создай встречу Обзор завтра в 10 на 0 минут", "создай встречу Обзор завтра в 10 на 25 часов",
    "создай встречу Обзор на 10 секунд", "создай встречу Обзор на полторы минуты",
])
def test_unclear_or_quoted_commands_do_not_create_events(tmp_path, text):
    store = Store(tmp_path)
    CalendarWorkflows(store).handle(text, ZONE, NOW)
    assert Calendar(store).list(*RANGE)["total"] == 0


def test_relative_move_uses_previous_start_and_preserves_duration(tmp_path):
    store = Store(tmp_path)
    handle = lambda text: CalendarWorkflows(store).handle(text, ZONE, NOW)
    handle("создай встречу Обзор завтра в 10 на 30 минут")
    assert handle("перенеси встречу на 15 минут позже").changed == ["calendar"]
    event, = Calendar(store).list(*RANGE)["events"]
    assert event["starts_at"] == "2026-10-17T05:15:00.000000+00:00"
    assert handle("перенеси встречу на 15 минут раньше").changed == ["calendar"]
    assert Calendar(store).get(event["id"])["starts_at"] == "2026-10-17T05:00:00.000000+00:00"
    assert handle("перенеси встречу через 15 минут").changed == ["calendar"]
    event = Calendar(store).get(event["id"])
    assert event["starts_at"] == "2026-10-16T04:15:00.000000+00:00"
    assert event["ends_at"] == "2026-10-16T04:45:00.000000+00:00"


def test_backup_v4_roundtrip_validation_legacy_and_staleness(tmp_path):
    source = Store(tmp_path / "source")
    event = Calendar(source).save(body())
    archive = Backups(source).export()
    assert json.loads(archive)["version"] == 8
    target = Store(tmp_path / "target")
    manager = Backups(target)
    preview = manager.preview(archive)
    assert preview["counts"]["calendar_events"] == 1
    manager.restore(preview["ticket"])
    assert Calendar(target).get(event["id"]) == event
    # Exact interval adjacency survives canonicalisation on restore.
    Calendar(target).save(body(starts_at="2026-10-17T11:00", ends_at="2026-10-17T12:00"))
    assert not any(item["conflict"] for item in Calendar(target).list(*RANGE)["events"])
    preview = manager.preview(archive)
    Calendar(target).save(body(title="Новое"))
    with pytest.raises(ValueError, match="изменились"): manager.restore(preview["ticket"])
    for field, invalid in (("scope_id", "missing"), ("ends_at", "2026-10-17T01:00Z"), ("timezone", "Unknown/Zone")):
        value = json.loads(archive)
        value["data"]["calendar_events"][0][field] = invalid
        with pytest.raises(ValueError): parse(encode(value))
    for version in (1, 2, 3):
        value = json.loads(archive)
        value["version"] = version
        with pytest.raises(ValueError): parse(encode(value))
        del value["data"]["calendar_events"]
        if version == 1:
            del value["data"]["conversations"]
        manager.restore(manager.preview(encode(value))["ticket"])
        assert Calendar(target).list(*RANGE)["total"] == 0


def test_api_chat_crud_and_interrupting_a_clarification(tmp_path, monkeypatch):
    async def fake_chat(settings, messages):
        yield "Обычный ответ модели"
    monkeypatch.setattr(providers, "chat", fake_chat)
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as api:
        send = lambda text: api.post("/chat", json={"text": text, "timezone": ZONE}).text
        assert '"changed": ["calendar"]' in send("создай встречу Обзор завтра в 10 на 30 минут")
        assert "Обзор" in send("покажи расписание завтра")
        assert '"changed": ["calendar"]' in send("перенеси встречу на 11")
        assert '"changed": ["calendar"]' in send("отмени встречу")
        assert "Когда" in send("создай встречу Черновик")
        send("создай заметку Тест: содержимое")
        assert '"changed": ["calendar"]' not in send("завтра в 12")
        assert not api.app.state.store.dialogue()["calendar"].get("pending")
        response = api.post("/calendar/events", json=body().model_dump())
        assert response.status_code == 200
        event = response.json()
        assert api.get("/calendar/events", params=dict(zip(("start", "end"), RANGE))).json()["total"] == 1
        assert api.put("/calendar/events/" + event["id"], json=body(title="Правка").model_dump()).status_code == 200
        assert api.delete("/calendar/events/" + event["id"], params={"expected_updated": event["updated"]}).status_code == 400
        assert api.delete("/calendar/events/" + event["id"]).status_code == 200
        assert api.get("/calendar/events", params={"start": "bad", "end": RANGE[1]}).status_code == 400
