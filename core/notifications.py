"""Durable local notification queues, including alerts tied to calendar events."""
from datetime import datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo


def utc_stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def reminder_time(starts_at, minutes):
    if minutes is None:
        return None
    try:
        return utc_stamp(datetime.fromisoformat(starts_at) - timedelta(minutes=minutes))
    except OverflowError as error:
        raise ValueError("Время напоминания выходит за допустимый диапазон") from error


def migrate(db):
    db.execute("SAVEPOINT migrate_calendar_alerts")
    columns = {row["name"] for row in db.execute("PRAGMA table_info(calendar_events)")}
    for name, definition in (("reminder_minutes", "INTEGER"), ("reminder_at", "TEXT"), ("reminder_sent", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            db.execute(f"ALTER TABLE calendar_events ADD COLUMN {name} {definition}")
    db.execute("CREATE TABLE IF NOT EXISTS calendar_alerts (id TEXT PRIMARY KEY,event_id TEXT NOT NULL,scheduled_for TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS calendar_alert_pending ON calendar_alerts(event_id) WHERE delivered=0")
    db.execute("CREATE INDEX IF NOT EXISTS calendar_due ON calendar_events(reminder_sent,reminder_at)")
    db.execute("RELEASE migrate_calendar_alerts")


def queue_calendar(db, current):
    current = utc_stamp(datetime.fromisoformat(current))
    # Catch up while the meeting remains relevant, without alerting about old events.
    db.execute("DELETE FROM calendar_alerts WHERE delivered=0 AND event_id IN (SELECT id FROM calendar_events WHERE ends_at<=?)", (current,))
    db.execute("UPDATE calendar_events SET reminder_sent=1 WHERE reminder_at IS NOT NULL AND reminder_sent=0 AND ends_at<=?", (current,))
    pending = []
    for event in db.execute("SELECT * FROM calendar_events WHERE reminder_sent=0 AND reminder_at<=? AND ends_at>? ORDER BY reminder_at,id LIMIT 1000", (current, current)).fetchall():
        item = dict(id=uuid.uuid4().hex, event_id=event["id"], scheduled_for=event["reminder_at"], delivered=0, created=current)
        db.execute("INSERT INTO calendar_alerts (id,event_id,scheduled_for,delivered,created) VALUES (:id,:event_id,:scheduled_for,:delivered,:created)", item)
        db.execute("UPDATE calendar_events SET reminder_sent=1 WHERE id=?", (event["id"],))
        pending.append(item)
    return pending


def calendar_message(db, row):
    start = datetime.fromisoformat(row["starts_at"]).astimezone(ZoneInfo(row["timezone"]))
    offset = start.strftime("%z")
    space = "Общий календарь"
    if row["scope_id"]:
        project = db.execute("SELECT name FROM projects WHERE id=?", (row["scope_id"],)).fetchone()
        space = "Проект «" + project[0] + "»" if project else "Календарь проекта"
    text = f"{row['title']} · {start:%d.%m.%Y %H:%M} (UTC{offset[:3]}:{offset[3:]}) · {space}"
    if row["location"]:
        text += " · " + row["location"]
    return text


CALENDAR_PENDING = """SELECT a.id,a.event_id,a.scheduled_for,a.created,e.title,e.starts_at,e.ends_at,e.timezone,e.location,e.scope_id
    FROM calendar_alerts a JOIN calendar_events e ON e.id=a.event_id
    WHERE a.delivered=0 AND e.reminder_sent=1 AND a.scheduled_for=e.reminder_at
    AND e.reminder_at<=? AND e.ends_at>?"""


def pending(db, current, limit=500):
    moment = datetime.fromisoformat(current)
    calendar = [dict(id=row["id"], event_id=row["event_id"], kind="calendar", created=row["created"], title=calendar_message(db, row))
                for row in db.execute(CALENDAR_PENDING + " ORDER BY a.created,a.id LIMIT ?", (utc_stamp(moment), utc_stamp(moment), limit))]
    tasks = [dict(row) | {"kind": "task"} for row in db.execute("""SELECT n.id,n.task_id,t.title,n.created FROM notifications n
        JOIN tasks t ON t.id=n.task_id WHERE n.delivered=0 AND t.done=0 AND t.notified=1 AND t.due<=?
        ORDER BY n.created,n.id LIMIT ?""", (current, limit))]
    return sorted(tasks + calendar, key=lambda item: (datetime.fromisoformat(item["created"]), item["id"]))[:limit]


def claim(db, item_id, current):
    """Check the current schedule and hand an alert to exactly one app poller."""
    # Caller holds BEGIN IMMEDIATE. A moved/deleted/disabled alert cannot be claimed.
    stamp = utc_stamp(datetime.fromisoformat(current))
    row = db.execute(CALENDAR_PENDING + " AND a.id=?", (stamp, stamp, item_id)).fetchone()
    if row:
        item = dict(id=row["id"], event_id=row["event_id"], kind="calendar", title=calendar_message(db, row), created=row["created"])
        db.execute("UPDATE calendar_alerts SET delivered=1 WHERE id=?", (item_id,))
        return item
    row = db.execute("""SELECT n.id,n.task_id,t.title,n.created FROM notifications n JOIN tasks t ON t.id=n.task_id
        WHERE n.id=? AND n.delivered=0 AND t.done=0 AND t.notified=1 AND t.due<=?""", (item_id, current)).fetchone()
    if row:
        db.execute("UPDATE notifications SET delivered=1 WHERE id=?", (item_id,))
        return dict(row) | {"kind": "task"}
    return None
