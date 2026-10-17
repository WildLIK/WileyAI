from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from core import storage, calendar as calendar_module
from core.api import create_app
from core.backups import Backups, encode, parse
from core.calendar import Calendar, EventBody
from core.calendar_workflows import CalendarWorkflows
from core.chatspaces import Spaces
from core.storage import Store

NOW = datetime(2026, 10, 17, 9, tzinfo=timezone.utc)
TOKEN = "calendar-alerts-tests-0123456789"


def body(**changes):
    return EventBody(**{**dict(title="Обзор", starts_at="2026-10-17T10:00Z", ends_at="2026-10-17T11:00Z", timezone="UTC", reminder_minutes=15), **changes})


@pytest.fixture
def clock(monkeypatch):
    current = [NOW]
    monkeypatch.setattr(storage, "now", lambda: current[0].isoformat())
    monkeypatch.setattr(calendar_module, "now", lambda: current[0].isoformat())
    return current


def test_due_once_restart_and_atomic_claim(tmp_path, clock):
    store = Store(tmp_path)
    event = Calendar(store).save(body())
    assert event["reminder_at"] == "2026-10-17T09:45:00.000000+00:00"
    assert store.queue_due_notifications() == []
    clock[0] += timedelta(minutes=45)
    queued, = store.queue_due_notifications()
    restarted = Store(tmp_path)
    assert restarted.queue_due_notifications() == []
    item, = restarted.pending_notifications()
    assert item["kind"] == "calendar" and item["event_id"] == event["id"]
    assert "17.10.2026 10:00" in item["title"] and "Общий календарь" in item["title"]
    assert restarted.claim_notification(queued["id"])["title"] == item["title"]
    assert restarted.claim_notification(queued["id"]) is None
    assert Store(tmp_path).pending_notifications() == []
    assert Store(tmp_path).queue_due_notifications() == []
    assert store.list("tasks") == []


def test_zero_offset_fires_at_start_and_disabled_event_never_queues(tmp_path, clock):
    store = Store(tmp_path)
    Calendar(store).save(body(title="Без напоминания", reminder_minutes=None))
    event = Calendar(store).save(body(reminder_minutes=0))
    clock[0] += timedelta(minutes=59)
    assert store.queue_due_notifications() == []
    clock[0] += timedelta(minutes=1)
    alert, = store.queue_due_notifications()
    assert alert["event_id"] == event["id"]


@pytest.mark.parametrize("minute,expected", [(45, 1), (60, 1), (119, 1), (120, 0), (24 * 60, 0)])
def test_catchup_only_until_event_end(tmp_path, clock, minute, expected):
    store = Store(tmp_path)
    Calendar(store).save(body())
    clock[0] = NOW + timedelta(minutes=minute)
    assert len(store.queue_due_notifications()) == expected
    assert store.queue_due_notifications() == []
    assert len(store.pending_notifications()) == expected


def test_reschedule_offset_change_and_rename_preserve_delivery_cycle(tmp_path, clock):
    store = Store(tmp_path)
    calendar = Calendar(store)
    event = calendar.save(body())
    clock[0] += timedelta(minutes=45)
    stale, = store.queue_due_notifications()
    event = calendar.save(body(starts_at="2026-10-17T11:00Z", ends_at="2026-10-17T12:00Z"), event["id"], event["updated"])
    assert store.claim_notification(stale["id"]) is None
    assert store.pending_notifications() == [] and store.queue_due_notifications() == []
    clock[0] += timedelta(hours=1)
    queued, = store.queue_due_notifications()
    event = calendar.save(body(title="Переименованная", starts_at=event["starts_at"], ends_at=event["ends_at"], location="Зал 3"), event["id"], event["updated"])
    claimed = store.claim_notification(queued["id"])
    assert "Переименованная" in claimed["title"] and "Зал 3" in claimed["title"]
    event = calendar.save(body(title="Только правка", starts_at=event["starts_at"], ends_at=event["ends_at"]), event["id"], event["updated"])
    assert store.queue_due_notifications() == []
    # An explicit offset change creates a new notification cycle.
    calendar.save(body(starts_at=event["starts_at"], ends_at=event["ends_at"], reminder_minutes=30), event["id"], event["updated"])
    assert len(store.queue_due_notifications()) == 1


@pytest.mark.parametrize("action", ["disable", "delete", "project_delete", "expired"])
def test_pending_cancellation_before_claim(tmp_path, clock, action):
    store = Store(tmp_path)
    spaces = Spaces(store)
    project = spaces.create_project("Закрытый проект")
    chat = spaces.create_chat(project["id"])
    calendar = Calendar(store.for_chat(chat["id"]))
    event = calendar.save(body())
    clock[0] += timedelta(minutes=45)
    pending, = store.queue_due_notifications()
    assert "Закрытый проект" in store.pending_notifications()[0]["title"]
    if action == "disable":
        calendar.save(body(reminder_minutes=None), event["id"], event["updated"])
    elif action == "delete":
        calendar.remove(event["id"], event["updated"])
    elif action == "project_delete":
        spaces.delete_project(project["id"])
    else:
        clock[0] += timedelta(hours=2)
    assert store.pending_notifications() == []
    assert store.claim_notification(pending["id"]) is None
    assert store.queue_due_notifications() == []


def test_stale_edit_does_not_cancel_valid_alert_and_move_chat_keeps_it(tmp_path, clock):
    store = Store(tmp_path)
    calendar = Calendar(store)
    event = calendar.save(body())
    clock[0] += timedelta(minutes=45)
    item, = store.queue_due_notifications()
    with pytest.raises(ValueError):
        calendar.save(body(reminder_minutes=None), event["id"], "old-revision")
    project = Spaces(store).create_project("Новое пространство чата")
    Spaces(store).update_chat(store.conversation_id, "Перенесён", project["id"])
    assert "Общий календарь" in store.claim_notification(item["id"])["title"]


def test_concurrent_scheduler_and_claim_are_serialised(tmp_path, clock):
    store = Store(tmp_path)
    Calendar(store).save(body())
    clock[0] += timedelta(minutes=45)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.queue_due_notifications(), range(4)))
    assert sum(map(len, results)) == 1
    item, = store.pending_notifications()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: store.claim_notification(item["id"]), range(4)))
    assert sum(value is not None for value in claimed) == 1


def test_claim_checks_latest_task_state_too(tmp_path, clock):
    store = Store(tmp_path)
    task = store.save_task("Задача", "reminder", (NOW - timedelta(minutes=1)).isoformat())
    alert, = store.queue_due_notifications()
    store.revise_task(task["id"], title="Новое название")
    assert store.claim_notification(alert["id"])["title"] == "Новое название"
    assert store.claim_notification(alert["id"]) is None
    store.revise_task(task["id"], due=(NOW - timedelta(minutes=2)).isoformat())
    alert, = store.queue_due_notifications()
    store.revise_task(task["id"], done=True)
    assert store.claim_notification(alert["id"]) is None
    assert store.pending_notifications() == []


@pytest.mark.parametrize("value", [-1, 10081, True, 1.5, "15"])
def test_offset_requires_bounded_integer(value):
    with pytest.raises(ValueError): body(reminder_minutes=value)


@pytest.mark.parametrize("text,offset", [
    ("создай встречу Обзор завтра в 10 на 30 минут, напомни за 15 минут", 15),
    ("создай встречу Обзор завтра в десять, напомни за полчаса", 30),
    ("создай встречу Обзор завтра в 10, напомни в начале", 0),
])
def test_chat_creates_and_updates_linked_reminder(tmp_path, text, offset):
    store = Store(tmp_path)
    handle = lambda text: CalendarWorkflows(store).handle(text, "UTC", NOW)
    assert handle(text).changed == ["calendar"]
    event, = Calendar(store).list("2026-10-17T00:00Z", "2026-10-20T00:00Z")["events"]
    assert event["reminder_minutes"] == offset and event["title"] == "Обзор"
    assert handle("перенеси встречу на 11").changed == ["calendar"]
    assert Calendar(store).get(event["id"])["reminder_at"] == (datetime(2026, 10, 18, 11, tzinfo=timezone.utc) - timedelta(minutes=offset)).isoformat(timespec="microseconds")
    assert handle("напомни о встрече за десять минут").changed == ["calendar"]
    assert Calendar(store).get(event["id"])["reminder_minutes"] == 10
    assert handle("отключи напоминание о встрече").changed == ["calendar"]
    assert Calendar(store).get(event["id"])["reminder_at"] is None
    assert store.list("tasks") == []


def test_draft_reminder_does_not_modify_previous_event(tmp_path):
    store = Store(tmp_path)
    handle = lambda text: CalendarWorkflows(store).handle(text, "UTC", NOW)
    handle("создай встречу Первая завтра в 10")
    handle("создай встречу Вторая")
    assert "пока не создано" in handle("напомни о встрече за 15 минут").text
    handle("завтра в 12")
    events = Calendar(store).list("2026-10-18T00:00Z", "2026-10-19T00:00Z")["events"]
    assert [(event["title"], event["reminder_minutes"]) for event in events] == [("Первая", None), ("Вторая", 15)]


@pytest.mark.parametrize("suffix", ["напомни за 0 минут", "напомни за 1.5 минуты", "напомни за 99999 минут", "напомни перед встречей", "напомни за 10 или 20 минут"])
def test_unclear_reminder_does_not_create_partial_event(tmp_path, suffix):
    store = Store(tmp_path)
    result = CalendarWorkflows(store).handle("создай встречу Обзор завтра в 10, " + suffix, "UTC", NOW)
    assert not result.changed
    assert Calendar(store).list("2026-10-17T00:00Z", "2026-10-20T00:00Z")["total"] == 0


def test_backup_pending_and_delivered_alerts_and_v4_compatibility(tmp_path, clock):
    store = Store(tmp_path / "source")
    event = Calendar(store).save(body())
    clock[0] += timedelta(minutes=45)
    alert, = store.queue_due_notifications()
    archive = Backups(store).export()
    assert json.loads(archive)["version"] == 8
    target = Store(tmp_path / "target")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.queue_due_notifications() == []
    # Editing a label must keep imported canonical timestamps and its pending alert.
    imported = Calendar(target).get(event["id"])
    Calendar(target).save(body(title="После импорта"), imported["id"], imported["updated"])
    assert "После импорта" in target.claim_notification(alert["id"])["title"]
    archive_delivered = manager.export()
    third = Store(tmp_path / "third")
    copied = Backups(third)
    copied.restore(copied.preview(archive_delivered)["ticket"])
    assert third.queue_due_notifications() == [] and third.pending_notifications() == []
    old = json.loads(archive)
    old["version"] = 4
    with pytest.raises(ValueError): parse(encode(old))
    old["data"].pop("calendar_alerts")
    for row in old["data"]["calendar_events"]:
        for key in ("reminder_at", "reminder_minutes", "reminder_sent"): row.pop(key)
    copied.restore(copied.preview(encode(old))["ticket"])
    assert Calendar(third).get(event["id"])["reminder_minutes"] is None
    assert third.queue_due_notifications() == []


@pytest.mark.parametrize("change", ["offset", "time", "parent", "sent", "duplicate", "collision"])
def test_backup_rejects_inconsistent_alerts(tmp_path, clock, change):
    store = Store(tmp_path)
    Calendar(store).save(body())
    clock[0] += timedelta(minutes=45)
    store.queue_due_notifications()
    raw = json.loads(Backups(store).export())
    event, = raw["data"]["calendar_events"]
    alert, = raw["data"]["calendar_alerts"]
    if change == "offset": event["reminder_minutes"] = 30
    elif change == "time": event["reminder_at"] = "2026-10-17T08:00:00Z"
    elif change == "parent": alert["event_id"] = "missing"
    elif change == "sent": event["reminder_sent"] = 0
    elif change == "collision": raw["data"]["notifications"].append(dict(id=alert["id"], task_id="old-task", title="Доставленное ранее", delivered=1, created=NOW.isoformat()))
    else: raw["data"]["calendar_alerts"].append({**alert, "id": "second-id"})
    with pytest.raises(ValueError): parse(encode(raw))


def test_migration_keeps_old_events_and_defaults_alerts_off(tmp_path):
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE calendar_events (id TEXT PRIMARY KEY,title TEXT,starts_at TEXT,ends_at TEXT,timezone TEXT,location TEXT,description TEXT,scope_id TEXT,created TEXT,updated TEXT)")
        db.execute("INSERT INTO calendar_events VALUES ('old','Прежняя встреча','2026-10-17T10:00:00.000000+00:00','2026-10-17T11:00:00.000000+00:00','UTC','','','',?,?)", (NOW.isoformat(), NOW.isoformat()))
    store = Store(tmp_path)
    assert Calendar(store).get("old")["reminder_minutes"] is None
    assert Calendar(Store(tmp_path)).get("old")["title"] == "Прежняя встреча"


def test_api_claim_ignores_disabled_event_and_refuses_second_claim(tmp_path, clock):
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as api:
        event = api.post("/calendar/events", json=body().model_dump()).json()
        clock[0] += timedelta(minutes=45)
        api.app.state.store.queue_due_notifications()
        alert, = api.get("/notifications").json()
        assert api.post("/notifications/" + alert["id"] + "/claim", headers={"Authorization": ""}).status_code == 401
        assert api.put("/calendar/events/" + event["id"], json=body(reminder_minutes=None).model_dump()).status_code == 200
        assert api.post("/notifications/" + alert["id"] + "/claim").json() is None
        api.put("/calendar/events/" + event["id"], json=body().model_dump())
        api.app.state.store.queue_due_notifications()
        alert, = api.get("/notifications").json()
        assert api.post("/notifications/" + alert["id"] + "/claim").json()["kind"] == "calendar"
        assert api.post("/notifications/" + alert["id"] + "/claim").json() is None
