"""Recurrence must survive delivery, edits, clock changes and portable backups."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timezone
import json
import sqlite3
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.backups import Backups, encode, parse
from core.chatspaces import Spaces
from core.repeats import RepeatRule, first_due, next_due
from core.storage import Store
from core.workflows import Workflows

ZONE = "Asia/Yekaterinburg"
RULE = RepeatRule(rule="daily", timezone=ZONE).model_dump_json(exclude_defaults=True)
TOKEN = "recurring-reminders-test-0123456789"


def clock(monkeypatch, value):
    monkeypatch.setattr("core.storage.now", lambda: value)


def test_missed_series_advances_once_and_claim_survives_restart(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    task = store.save_task("Вода", "reminder", "2025-01-01T05:00:00+00:00", recurrence=RULE)
    alert, = store.queue_due_notifications()
    assert store.task(task["id"])["due"] == "2026-10-18T05:00:00+00:00"
    assert store.queue_due_notifications() == []
    restarted = Store(tmp_path)
    assert [item["id"] for item in restarted.pending_notifications()] == [alert["id"]]
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: Store(tmp_path).claim_notification(alert["id"]), range(4)))
    assert len([item for item in results if item]) == 1
    assert Store(tmp_path).pending_notifications() == []
    clock(monkeypatch, "2026-10-18T05:00:00+00:00")
    new_alert, = restarted.queue_due_notifications()
    assert new_alert["id"] != alert["id"]
    assert restarted.task(task["id"])["due"] == "2026-10-19T05:00:00+00:00"


def test_unclaimed_missed_alerts_coalesce_but_keep_advancing(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    task = store.save_task("Вода", "reminder", "2026-10-16T05:00:00+00:00", recurrence=RULE)
    alert, = store.queue_due_notifications()
    clock(monkeypatch, "2026-11-20T06:00:00+00:00")
    assert store.queue_due_notifications() == []
    assert store.task(task["id"])["due"] == "2026-11-21T05:00:00+00:00"
    assert [item["id"] for item in store.pending_notifications()] == [alert["id"]]


@pytest.mark.parametrize("action", ["move", "rule", "stop", "delete"])
def test_edit_invalidates_pending_delivery(tmp_path, monkeypatch, action):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    task = store.save_task("Вода", "reminder", "2026-10-17T05:00:00+00:00", recurrence=RULE)
    alert, = store.queue_due_notifications()
    if action == "move":
        store.revise_task(task["id"], due="2026-10-20T06:00:00+00:00")
    elif action == "rule":
        store.revise_task(task["id"], recurrence=None)
    elif action == "stop":
        store.revise_task(task["id"], done=True)
    else:
        store.remove("tasks", task["id"])
    assert store.claim_notification(alert["id"]) is None
    assert store.pending_notifications() == []


def test_rename_keeps_delivery_with_current_title(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    task = store.save_task("Вода", "alarm", "2026-10-17T05:00:00+00:00", recurrence=RULE)
    alert, = store.queue_due_notifications()
    store.revise_task(task["id"], title="Чай")
    assert store.claim_notification(alert["id"])["title"] == "Чай"


@pytest.mark.parametrize("rule", [
    {"rule": "monthly"}, {"rule": "weekly"}, {"rule": "weekly", "weekdays": []},
    {"rule": "weekly", "weekdays": [0, 7]}, {"rule": "weekly", "weekdays": [False]},
    {"rule": "weekly", "weekdays": [0, 0]}, {"rule": "weekly", "weekday": 2, "weekdays": [0]},
    {"rule": "daily", "weekday": 0}, {"rule": "daily", "timezone": "No/Zone"},
    {"rule": "daily", "script": "anything"},
])
def test_api_rejects_invalid_schedules(tmp_path, rule):
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as api:
        response = api.post("/tasks", json={"title": "Вода", "kind": "reminder", "due": "2026-11-01T10:00:00+05:00", "recurrence": rule})
        assert response.status_code == 422
        assert api.get("/tasks").json() == []


@pytest.mark.parametrize("kind,due", [("todo", None), ("timer", "2026-11-01T05:00:00+00:00"), ("reminder", None), ("alarm", "2026-11-01T05:00:00")])
def test_store_checks_kind_and_timezone(tmp_path, kind, due):
    with pytest.raises(ValueError):
        Store(tmp_path).save_task("Вода", kind, due, recurrence=RULE)


def test_weekday_schedule_in_local_timezone():
    rule = RepeatRule(rule="weekdays", timezone=ZONE)
    now = datetime(2026, 10, 17, 9, tzinfo=ZoneInfo(ZONE))  # Saturday
    assert first_due(now, rule, time(10)).isoformat() == "2026-10-19T10:00:00+05:00"
    rule = RepeatRule(rule="weekly", weekdays=[0, 2], timezone=ZONE)
    monday = first_due(now, rule, time(10))
    assert next_due(monday, rule).isoformat() == "2026-10-21T10:00:00+05:00"


def test_dst_skips_nonexistent_time_and_never_repeats_fold():
    rule = RepeatRule(rule="daily", timezone="America/New_York")
    before_spring = datetime.fromisoformat("2026-03-07T07:30:00+00:00")
    assert next_due(before_spring, rule).isoformat() == "2026-03-09T02:30:00-04:00"
    before_fall = datetime.fromisoformat("2026-10-31T05:30:00+00:00")
    first = next_due(before_fall, rule)
    assert first.isoformat() == "2026-11-01T01:30:00-04:00"
    assert next_due(first, rule).isoformat() == "2026-11-02T01:30:00-05:00"
    # Catch-up between the first and second 01:30 skips the duplicate local time.
    assert next_due(before_fall, rule, datetime.fromisoformat("2026-11-01T06:00:00+00:00")).date().isoformat() == "2026-11-02"


def test_backup_roundtrip_pending_series_and_v7_upgrade(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path / "source")
    task = store.save_task("Вода", "reminder", "2026-10-17T05:00:00+00:00", recurrence=RULE)
    alert, = store.queue_due_notifications()
    archive = Backups(store).export()
    assert parse(archive).version == 8
    target = Store(tmp_path / "target")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.task(task["id"])["due"] == "2026-10-18T05:00:00+00:00"
    assert target.claim_notification(alert["id"])["title"] == "Вода"
    # Old archives have no immutable alert time. Infer it for one-shot reminders.
    legacy = Store(tmp_path / "legacy")
    legacy.save_task("Старое", "reminder", "2026-10-17T04:00:00+00:00")
    old_alert, = legacy.queue_due_notifications()
    value = json.loads(Backups(legacy).export())
    value["version"] = 7
    for row in value["data"]["tasks"]:
        row.pop("recurrence")
    for row in value["data"]["notifications"]:
        row.pop("scheduled_for")
    manager.restore(manager.preview(encode(value))["ticket"])
    assert target.claim_notification(old_alert["id"])["title"] == "Старое"


def test_bad_backup_rule_does_not_replace_data(tmp_path):
    store = Store(tmp_path)
    store.save_task("Вода", "reminder", "2026-11-01T05:00:00+00:00", recurrence=RULE)
    manager = Backups(store)
    value = json.loads(manager.export())
    value["data"]["tasks"][0]["recurrence"] = '{"rule":"weekly","weekdays":[9]}'
    with pytest.raises(ValueError, match="Не удалось проверить"):
        manager.preview(encode(value))
    assert manager.pending is None
    assert store.list("tasks")[0]["recurrence"] == RULE


def test_existing_database_without_repeat_fields_migrates(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL,due TEXT,done INTEGER NOT NULL DEFAULT 0,notified INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
        db.execute("CREATE TABLE notifications (id TEXT PRIMARY KEY,task_id TEXT NOT NULL,title TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
        db.execute("INSERT INTO tasks VALUES ('old','Раньше','reminder','2026-10-17T04:00:00+00:00',0,1,'2026-10-16T04:00:00+00:00')")
        db.execute("INSERT INTO notifications VALUES ('notice','old','Раньше',0,'2026-10-17T04:00:00+00:00')")
    store = Store(tmp_path)
    assert store.task("old")["recurrence"] is None
    assert store.claim_notification("notice")["title"] == "Раньше"


@pytest.mark.parametrize("phrase,days,title", [
    ("Напомни по понедельникам и средам в 10 зарядка", [0, 2], "зарядка"),
    ("Напомни зарядка в 10 по понедельникам, средам и пятницам", [0, 2, 4], "зарядка"),
    ("Напомни по выходным в 10 зарядка", [5, 6], "зарядка"),
])
def test_russian_multiweekday_commands(tmp_path, phrase, days, title):
    store = Store(tmp_path)
    result = Workflows(store).handle(phrase, ZONE, datetime(2026, 10, 16, 9, tzinfo=ZoneInfo(ZONE)))
    assert result.changed == ["tasks"], result.text
    task, = store.list("tasks")
    rule = RepeatRule.model_validate_json(task["recurrence"])
    assert rule.weekdays == days and task["title"] == title
    assert rule.timezone == ZONE


def test_durable_repeat_draft_and_cancel_only_draft(tmp_path):
    store = Store(tmp_path)
    now = datetime(2026, 10, 16, 9, tzinfo=ZoneInfo(ZONE))
    handle = lambda text: Workflows(Store(tmp_path)).handle(text, ZONE, now)
    handle("Напомни ежедневно в 10 зарядка")
    handle("Напомни ежедневно почта")
    assert "новом напоминании" in handle("отмени повтор").text
    assert store.list("tasks")[0]["recurrence"] is not None
    assert handle("в 11").changed == ["tasks"]
    assert next(task for task in store.list("tasks") if task["title"] == "почта")["recurrence"] is None


def test_unsupported_recurrence_does_not_create_one_shot(tmp_path):
    store = Store(tmp_path)
    result = Workflows(store).handle("Напомни каждый месяц в 10 почта", ZONE)
    assert "Поддерживаются" in result.text
    assert store.list("tasks") == []


def test_delete_series_removes_next_occurrence_too(tmp_path):
    store = Store(tmp_path)
    now = datetime(2026, 10, 16, 9, tzinfo=ZoneInfo(ZONE))
    workflow = Workflows(store)
    workflow.handle("Напомни ежедневно в 10 зарядка", ZONE, now)
    assert workflow.handle("Удали серию", ZONE, now).changed == ["tasks"]
    assert store.list("tasks") == []


def test_project_series_cannot_be_changed_from_another_chat(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    spaces = Spaces(store)
    project = spaces.create_project("Работа")
    chat = spaces.create_chat(project["id"], "Напоминания")
    private = store.for_chat(chat["id"])
    task = private.save_task("Почта", "reminder", "2026-10-17T05:00:00+00:00", recurrence=RULE)
    assert store.list("tasks") == [] and store.task(task["id"]) is None
    assert store.revise_task(task["id"], recurrence=None) is None
    with pytest.raises(ValueError):
        store.save_task("Чужое", "reminder", task["due"], item_id=task["id"])
    alert, = store.queue_due_notifications()  # All projects can notify while app runs.
    assert private.task(task["id"])["due"] == "2026-10-18T05:00:00+00:00"
    assert store.claim_notification(alert["id"])["title"] == "Почта"


def test_repeat_only_clarification_is_retained_until_time_arrives(tmp_path):
    store = Store(tmp_path)
    now = datetime(2026, 10, 16, 9, tzinfo=ZoneInfo(ZONE))
    handle = lambda text: Workflows(Store(tmp_path)).handle(text, ZONE, now)
    handle("Напомни почта")
    assert "Когда напомнить" in handle("по будням").text
    assert handle("в 11").changed == ["tasks"]
    task, = store.list("tasks")
    assert json.loads(task["recurrence"])["rule"] == "weekdays"


def test_backup_pending_validation_and_legacy_coalescing(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-10-17T05:00:00+00:00")
    store = Store(tmp_path)
    store.save_task("Вода", "reminder", "2026-10-17T04:00:00+00:00")
    store.queue_due_notifications()
    value = json.loads(Backups(store).export())
    value["data"]["notifications"].append({**value["data"]["notifications"][0], "id": "second"})
    with pytest.raises(ValueError):
        parse(encode(value))
    value["version"] = 7
    for row in value["data"]["notifications"]:
        row.pop("scheduled_for")
    bundle = parse(encode(value))
    assert len(bundle.data.notifications) == 1
    assert bundle.data.notifications[0].scheduled_for == "2026-10-17T04:00:00+00:00"
