"""Durable local notification queues, including alerts tied to calendar events."""
from datetime import datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo
from .calendar_repeats import occurrences


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
    for name, definition in (("reminder_minutes", "INTEGER"), ("reminder_at", "TEXT"), ("reminder_sent", "INTEGER NOT NULL DEFAULT 0"),
                             ("all_day", "INTEGER NOT NULL DEFAULT 0"), ("recurrence", "TEXT"), ("reminder_cursor", "TEXT"), ("parent_id", "TEXT"), ("original_start", "TEXT")):
        if name not in columns:
            db.execute(f"ALTER TABLE calendar_events ADD COLUMN {name} {definition}")
    db.execute("CREATE TABLE IF NOT EXISTS calendar_alerts (id TEXT PRIMARY KEY,event_id TEXT NOT NULL,scheduled_for TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
    if "deferred" not in {row["name"] for row in db.execute("PRAGMA table_info(calendar_alerts)")}:
        db.execute("ALTER TABLE calendar_alerts ADD COLUMN deferred INTEGER NOT NULL DEFAULT 0")
    for name in ("occurrence_start", "occurrence_end"):
        if name not in {row["name"] for row in db.execute("PRAGMA table_info(calendar_alerts)")}:
            db.execute(f"ALTER TABLE calendar_alerts ADD COLUMN {name} TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS calendar_alert_pending ON calendar_alerts(event_id) WHERE delivered=0")
    db.execute("CREATE INDEX IF NOT EXISTS calendar_due ON calendar_events(reminder_sent,reminder_at)")
    db.execute("RELEASE migrate_calendar_alerts")


def recurring_due(db, current):
    """Latest due occurrence per repeating series that has no undelivered alert yet."""
    moment, result = datetime.fromisoformat(current), []
    for row in db.execute("SELECT * FROM calendar_events WHERE recurrence IS NOT NULL AND reminder_at<=? AND reminder_minutes IS NOT NULL", (current,)).fetchall():
        event = dict(row)
        due = [(begin, stop, reminder_time(utc_stamp(begin), event["reminder_minutes"])) for begin, stop in
               occurrences(event, moment - timedelta(days=32), moment + timedelta(days=8))]
        due = [item for item in due if item[2] <= current and (not event["reminder_cursor"] or item[2] > event["reminder_cursor"]) and item[1] > moment]
        # Coalesce a backlog to one alert per series, preserving a deferred alert.
        if due and not db.execute("SELECT 1 FROM calendar_alerts WHERE event_id=? AND delivered=0", (event["id"],)).fetchone():
            result.append((event, *due[-1]))
    return result


def calendar_due(db, current, quiet=False):
    """Read-only: would queue_calendar change anything? Lets the scheduler skip its write lock."""
    current = utc_stamp(datetime.fromisoformat(current))
    checks = [("SELECT 1 FROM calendar_alerts WHERE delivered=0 AND deferred=0 AND COALESCE(occurrence_end,(SELECT ends_at FROM calendar_events WHERE id=event_id))<=? LIMIT 1", (current,)),
              ("SELECT 1 FROM calendar_events WHERE recurrence IS NULL AND reminder_at IS NOT NULL AND reminder_sent=0 AND (reminder_at<=? OR ends_at<=?) LIMIT 1", (current, current))]
    if quiet:
        checks.append(("SELECT 1 FROM calendar_alerts WHERE delivered=0 AND deferred=0 LIMIT 1", ()))
    return any(db.execute(query, args).fetchone() for query, args in checks) or bool(recurring_due(db, current))


def queue_calendar(db, current, quiet=False):
    current = utc_stamp(datetime.fromisoformat(current))
    # Catch up while the meeting remains relevant, without alerting about old events.
    db.execute("DELETE FROM calendar_alerts WHERE delivered=0 AND deferred=0 AND COALESCE(occurrence_end,(SELECT ends_at FROM calendar_events WHERE id=event_id))<=?", (current,))
    db.execute("UPDATE calendar_events SET reminder_sent=1 WHERE recurrence IS NULL AND reminder_at IS NOT NULL AND reminder_sent=0 AND ends_at<=?", (current,))
    pending = []
    for event in db.execute("SELECT * FROM calendar_events WHERE recurrence IS NULL AND reminder_sent=0 AND reminder_at<=? AND ends_at>? ORDER BY reminder_at,id LIMIT 1000", (current, current)).fetchall():
        item = dict(id=uuid.uuid4().hex, event_id=event["id"], scheduled_for=event["reminder_at"], delivered=0, created=current)
        db.execute("INSERT INTO calendar_alerts (id,event_id,scheduled_for,delivered,created) VALUES (:id,:event_id,:scheduled_for,:delivered,:created)", item)
        db.execute("UPDATE calendar_events SET reminder_sent=1 WHERE id=?", (event["id"],))
        pending.append(item)
    for event, begin, stop, scheduled in recurring_due(db, current):
        item = dict(id=uuid.uuid4().hex, event_id=event["id"], scheduled_for=scheduled, delivered=0, created=current,
                    occurrence_start=utc_stamp(begin), occurrence_end=utc_stamp(stop))
        db.execute("INSERT INTO calendar_alerts (id,event_id,scheduled_for,delivered,created,occurrence_start,occurrence_end) VALUES (:id,:event_id,:scheduled_for,:delivered,:created,:occurrence_start,:occurrence_end)", item)
        db.execute("UPDATE calendar_events SET reminder_cursor=? WHERE id=?", (scheduled, event["id"]))
        pending.append(item)
    if quiet:
        db.execute("UPDATE calendar_alerts SET deferred=1 WHERE delivered=0")
    return pending


def calendar_message(db, row, projects=None):
    start = datetime.fromisoformat(row["starts_at"]).astimezone(ZoneInfo(row["timezone"]))
    offset = start.strftime("%z")
    space = "Общий календарь"
    if row["scope_id"]:
        if projects is None or row["scope_id"] not in projects:
            project = db.execute("SELECT name FROM projects WHERE id=?", (row["scope_id"],)).fetchone()
            name = project[0] if project else None
            if projects is not None:
                projects[row["scope_id"]] = name
        else:
            name = projects[row["scope_id"]]
        space = "Проект «" + name + "»" if name else "Календарь проекта"
    label = start.strftime("%d.%m.%Y") + (" · весь день" if row["all_day"] else start.strftime(" %H:%M"))
    text = ("После тихих часов · " if row["deferred"] else "") + f"{row['title']} · {label} (UTC{offset[:3]}:{offset[3:]}) · {space}"
    if row["location"]:
        text += " · " + row["location"]
    return text


CALENDAR_PENDING = """SELECT a.id,a.event_id,a.scheduled_for,a.created,a.deferred,e.title,COALESCE(a.occurrence_start,e.starts_at) AS starts_at,COALESCE(a.occurrence_end,e.ends_at) AS ends_at,e.timezone,e.location,e.scope_id,e.all_day
    FROM calendar_alerts a JOIN calendar_events e ON e.id=a.event_id
    WHERE a.delivered=0 AND ((e.recurrence IS NULL AND e.reminder_sent=1 AND a.scheduled_for=e.reminder_at)
    OR (e.recurrence IS NOT NULL AND e.reminder_minutes IS NOT NULL AND a.scheduled_for=e.reminder_cursor))
    AND a.scheduled_for<=? AND (COALESCE(a.occurrence_end,e.ends_at)>? OR a.deferred=1)"""

TASK_PENDING = """SELECT n.id,n.task_id,t.title,n.created FROM notifications n JOIN tasks t ON t.id=n.task_id
    WHERE n.delivered=0 AND t.done=0 AND n.scheduled_for<=?
    AND (t.recurrence IS NOT NULL OR (t.notified=1 AND t.due=n.scheduled_for))"""


def pending(db, current, limit=500):
    moment, projects = datetime.fromisoformat(current), {}
    calendar = [dict(id=row["id"], event_id=row["event_id"], kind="calendar", created=row["created"], title=calendar_message(db, row, projects))
                for row in db.execute(CALENDAR_PENDING + " ORDER BY a.created,a.id LIMIT ?", (utc_stamp(moment), utc_stamp(moment), limit))]
    tasks = [dict(row) | {"kind": "task"} for row in db.execute(TASK_PENDING + " ORDER BY n.created,n.id LIMIT ?", (current, limit))]
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
    row = db.execute(TASK_PENDING + " AND n.id=?", (current, item_id)).fetchone()
    if row:
        db.execute("UPDATE notifications SET delivered=1 WHERE id=?", (item_id,))
        return dict(row) | {"kind": "task"}
    return None
