from datetime import datetime, timedelta, timezone
import json

import pytest

from core import storage, calendar as module
from core.backups import Backups, encode, parse
from core.calendar import Calendar, EventBody
from core.chatspaces import Spaces
from core.storage import Store


def body(**changes):
    return EventBody(**{**dict(title="Планёрка", starts_at="2026-10-19T10:00", ends_at="2026-10-19T11:00", timezone="Asia/Yekaterinburg", recurrence={"rule": "weekdays"}), **changes})


def test_weekdays_expansion_and_conflicts_and_scope(tmp_path):
    store = Store(tmp_path)
    calendar = Calendar(store)
    master = calendar.save(body())
    calendar.save(body(title="Пересечение", starts_at="2026-10-20T10:30", ends_at="2026-10-20T11:30", recurrence=None))
    result = calendar.list("2026-10-19T00:00Z", "2026-10-26T00:00Z")
    assert result["total"] == 6
    assert sum(item["conflict"] for item in result["events"]) == 2
    assert len({item["starts_at"] for item in result["events"] if item["id"] == master["id"]}) == 5
    assert calendar.get(master["id"])["starts_at"] == "2026-10-19T05:00:00.000000+00:00"
    project = Spaces(store).create_project("Другое")
    chat = Spaces(store).create_chat(project["id"])
    assert Calendar(store.for_chat(chat["id"])).list("2026-10-19T00:00Z", "2026-10-26T00:00Z")["total"] == 0


def test_all_day_exclusive_end_dst_and_until(tmp_path):
    calendar = Calendar(Store(tmp_path))
    event = calendar.save(body(starts_at="2026-10-24", ends_at="2026-10-26", timezone="Europe/Berlin", all_day=True, recurrence={"rule": "daily", "until": "2026-10-26"}))
    assert event["starts_at"] == "2026-10-23T22:00:00.000000+00:00"
    assert event["ends_at"] == "2026-10-25T23:00:00.000000+00:00"
    events = calendar.list("2026-10-24T00:00Z", "2026-10-29T00:00Z")["events"]
    assert len(events) == 3
    assert events[-1]["ends_at"] == "2026-10-27T23:00:00.000000+00:00"
    assert events[0]["conflict"]


def test_spring_gap_skipped_and_fall_clock_kept(tmp_path):
    calendar = Calendar(Store(tmp_path))
    calendar.save(body(starts_at="2026-03-28T02:30", ends_at="2026-03-28T03:30", timezone="Europe/Berlin", recurrence={"rule": "daily"}))
    events = calendar.list("2026-03-28T00:00Z", "2026-03-31T00:00Z")["events"]
    assert [item["starts_at"][8:10] for item in events] == ["28", "30"]
    event = calendar.save(body(starts_at="2026-10-24T10:00", ends_at="2026-10-24T11:00", timezone="Europe/Berlin", recurrence={"rule": "daily"}))
    events = calendar.list("2026-10-24T00:00Z", "2026-10-27T00:00Z")["events"]
    assert [item["starts_at"][11:16] for item in events if item["id"] == event["id"]] == ["08:00", "09:00", "09:00"]


@pytest.mark.parametrize("changes", [
    {"all_day": True}, {"recurrence": {"rule": "weekly", "weekdays": [1]}},
    {"recurrence": {"rule": "daily", "until": "2026-10-18"}}, {"recurrence": {"rule": "yearly"}},
    {"recurrence": {"rule": "daily", "until": "bad"}},
])
def test_invalid_calendar_rules_rejected(changes):
    with pytest.raises(ValueError): body(**changes)


def test_repeating_reminders_restart_quiet_backup_and_edits(tmp_path, monkeypatch):
    current = [datetime(2026, 10, 19, 4, 45, tzinfo=timezone.utc)]
    monkeypatch.setattr(storage, "now", lambda: current[0].isoformat())
    monkeypatch.setattr(module, "now", lambda: current[0].isoformat())
    store = Store(tmp_path)
    calendar = Calendar(store)
    event = calendar.save(body(reminder_minutes=15))
    alert, = store.queue_due_notifications()
    assert "19.10.2026 10:00" in store.claim_notification(alert["id"])["title"]
    assert Store(tmp_path).queue_due_notifications() == []
    current[0] += timedelta(days=1)
    alert, = Store(tmp_path).queue_due_notifications()
    assert "20.10.2026 10:00" in store.pending_notifications()[0]["title"]
    assert Store(tmp_path).queue_due_notifications() == []
    archive = Backups(store).export()
    target = Store(tmp_path / "target")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.queue_due_notifications() == []
    assert target.claim_notification(alert["id"])
    calendar.save(body(title="Переименована", reminder_minutes=15), event["id"])
    assert store.queue_due_notifications() == []
    # A delivered historical occurrence remains valid in backups after rescheduling.
    store.claim_notification(alert["id"])
    calendar.save(body(starts_at="2026-10-21T12:00", ends_at="2026-10-21T13:00", recurrence=None), event["id"])
    Backups(store).export()


def test_repeating_quiet_alert_delivered_after_its_end(tmp_path, monkeypatch):
    current = [datetime(2026, 10, 19, 5, tzinfo=timezone.utc)]
    monkeypatch.setattr(storage, "now", lambda: current[0].isoformat())
    store = Store(tmp_path)
    store.save_settings(store.settings().model_copy(update={"quiet_enabled": True, "quiet_start": "04:00", "quiet_end": "08:00", "background_timezone": "UTC"}))
    Calendar(store).save(body(reminder_minutes=0))
    alert, = store.queue_due_notifications()
    assert store.pending_notifications() == []
    current[0] += timedelta(hours=3)
    assert Store(tmp_path).queue_due_notifications() == []
    assert "После тихих часов" in store.claim_notification(alert["id"])["title"]


def test_backup_series_validation_and_v8_compatibility(tmp_path):
    store = Store(tmp_path)
    event = Calendar(store).save(body(reminder_minutes=0))
    archive = json.loads(Backups(store).export())
    assert archive["version"] == 11
    assert parse(encode(archive)).data.calendar_events[0].recurrence
    archive["version"] = 8
    with pytest.raises(ValueError): parse(encode(archive))
    archive["version"] = 9
    archive["data"]["calendar_events"][0]["reminder_cursor"] = "2026-10-20T09:32Z"
    with pytest.raises(ValueError): parse(encode(archive))
    Calendar(store).save(body(recurrence=None), event["id"])
    archive = json.loads(Backups(store).export())
    archive["version"] = 8
    assert parse(encode(archive)).data.calendar_events
