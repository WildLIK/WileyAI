from datetime import datetime, timedelta, timezone
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core import storage, quiet
from core.background import Background
from core.backups import Backups
from core.calendar import Calendar, EventBody
from core.config import Settings
from core.storage import Store


@pytest.mark.parametrize("clock,expected", [("22:59", False), ("23:00", True), ("00:00", True), ("07:59", True), ("08:00", False)])
def test_quiet_hours_cross_midnight(clock, expected):
    config = Settings(quiet_enabled=True)
    moment = datetime.fromisoformat("2026-10-18T" + clock + "+00:00")
    assert quiet.active(config, moment) == expected
    assert not quiet.active(config.model_copy(update={"quiet_enabled": False}), moment)


def test_quiet_hours_timezone_and_all_day():
    config = Settings(quiet_enabled=True, background_timezone="Asia/Yekaterinburg")
    assert quiet.active(config, datetime.fromisoformat("2026-10-18T18:00Z"))
    assert quiet.active(config.model_copy(update={"quiet_start": "12:00", "quiet_end": "12:00"}), datetime.fromisoformat("2026-10-18T10:00Z"))


def test_task_and_expired_calendar_alerts_survive_quiet_hours_restart_and_backup(tmp_path, monkeypatch):
    clock = [datetime.fromisoformat("2026-10-18T23:30Z")]
    monkeypatch.setattr(storage, "now", lambda: clock[0].isoformat())
    store = Store(tmp_path)
    store.save_settings(Settings(quiet_enabled=True))
    store.save_task("Позвонить", "reminder", "2026-10-18T23:20:00+00:00")
    event = Calendar(store).save(EventBody(title="Встреча ночью", starts_at="2026-10-18T23:30Z", ends_at="2026-10-18T23:45Z", timezone="UTC", reminder_minutes=0))
    queued = store.queue_due_notifications()
    assert len(queued) == 2 and store.pending_notifications() == []
    assert all(store.claim_notification(item["id"]) is None for item in queued)
    clock[0] += timedelta(hours=9)
    restarted = Store(tmp_path)
    restarted.queue_due_notifications()
    items = restarted.pending_notifications()
    assert len(items) == 2
    assert any(row.get("event_id") == event["id"] and "тихих часов" in row["title"] for row in items)
    target = Store(tmp_path / "restore")
    backups = Backups(target)
    backups.restore(backups.preview(Backups(restarted).export())["ticket"])
    assert len(target.pending_notifications()) == 2
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(target.claim_notification, [items[0]["id"], items[0]["id"]]))
    assert sum(row is not None for row in claimed) == 1


def test_daily_backups_once_retention_preserves_manual_copies_and_restores(tmp_path):
    store = Store(tmp_path)
    store.save_note("План", "Проверенные данные")
    store.save_settings(Settings(backup_schedule="daily", backup_time="18:00", backup_keep=2))
    manager = Background(store)
    now = datetime.fromisoformat("2026-10-18T18:01Z")
    manager.tick(now - timedelta(minutes=2))
    assert manager.status()["last_backup"] is None
    manager.tick(now)
    folder = tmp_path / "backups/scheduled"
    manual = folder / "manual.wileyai.json"
    manual.write_text("KEEP")
    for day in range(4):
        moment = now + timedelta(days=day)
        manager.tick(moment)
        Background(store).tick(moment + timedelta(minutes=2))
    files = list(folder.glob("auto-*.wileyai.json"))
    assert len(files) == 2 and manual.read_text() == "KEEP"
    target = Store(tmp_path / "restored")
    target_backups = Backups(target)
    latest = sorted(files)[-1]
    target_backups.restore(target_backups.preview(latest.read_bytes())["ticket"])
    assert target.list("notes")[0]["content"] == "Проверенные данные"
    assert not list(folder.glob("*.tmp"))


def test_failed_backup_does_not_delete_old_copy_and_retry_is_bounded(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save_settings(Settings(backup_schedule="weekly", backup_time="18:00", backup_keep=1))
    manager = Background(store)
    now = datetime.fromisoformat("2026-10-18T18:01Z")
    manager.tick(now)
    previous = manager.status()["path"]
    calls = []
    def fail(*args):
        calls.append(1)
        raise OSError("private diagnostic")
    monkeypatch.setattr(Backups, "export", fail)
    manager.tick(now + timedelta(days=7))
    manager.tick(now + timedelta(days=7, minutes=1))
    assert len(calls) == 1 and manager.status()["path"] == previous
    assert "private" not in manager.status()["error"] and manager.status()["error"]
    assert len(list((tmp_path / "backups/scheduled").glob("auto-*"))) == 1


@pytest.mark.parametrize("changes", [{"background_timezone": "unknown/time"}, {"backup_keep": 0}, {"backup_time": "25:00"}, {"quiet_start": "8:00"}])
def test_invalid_background_settings(changes):
    with pytest.raises(ValueError): Settings(**changes)
