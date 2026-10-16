"""Local, project-scoped calendar with explicitly enabled event reminders."""
from datetime import datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage import Store, now
from .notifications import reminder_time


def calendar_zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("Неизвестный часовой пояс календаря") from error


def instant(value: str, zone: str | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Нужны дата и время в формате ISO") from error
    if "T" not in value and " " not in value:
        raise ValueError("Укажите время вместе с датой")
    if parsed.tzinfo is None:
        if not zone:
            raise ValueError("Передайте время с часовым поясом")
        tz = calendar_zone(zone)
        first, second = parsed.replace(tzinfo=tz, fold=0), parsed.replace(tzinfo=tz, fold=1)
        if first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != parsed:
            raise ValueError("Это время не существует из-за перевода часов")
        if first.utcoffset() != second.utcoffset():
            raise ValueError("Это время неоднозначно из-за перевода часов. Укажите явное смещение UTC")
        parsed = first
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError("Дата выходит за допустимый диапазон") from error


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class EventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    starts_at: str = Field(min_length=1, max_length=100)
    ends_at: str = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)
    location: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10000)
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080, strict=True)

    @field_validator("title")
    @classmethod
    def title_text(cls, value):
        if not value.strip():
            raise ValueError("Укажите название события")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        calendar_zone(value)
        return value

    @model_validator(mode="after")
    def interval(self):
        start, end = instant(self.starts_at, self.timezone), instant(self.ends_at, self.timezone)
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise ValueError("Окончание должно быть позже начала; длительность — не больше 31 дня")
        self.starts_at, self.ends_at = timestamp(start), timestamp(end)
        reminder_time(self.starts_at, self.reminder_minutes)
        return self


class Calendar:
    def __init__(self, store: Store):
        self.store = store

    def list(self, start: str, end: str, limit: int = 1000):
        start, end = instant(start), instant(end)
        if not timedelta(0) < end - start <= timedelta(days=370):
            raise ValueError("Выберите период от одного мгновения до 370 дней")
        args = (self.store.scope_id, timestamp(end), timestamp(start))
        with self.store.db() as db:
            db.execute("BEGIN")
            self._check_chat(db)
            total = db.execute("SELECT COUNT(*) FROM calendar_events WHERE scope_id=? AND starts_at<? AND ends_at>?", args).fetchone()[0]
            rows = db.execute("""SELECT e.*,EXISTS(SELECT 1 FROM calendar_events other
                WHERE other.scope_id=e.scope_id AND other.id!=e.id
                AND other.starts_at<e.ends_at AND other.ends_at>e.starts_at) AS conflict
                FROM calendar_events e WHERE e.scope_id=? AND e.starts_at<? AND e.ends_at>?
                ORDER BY e.starts_at,e.ends_at,e.id LIMIT ?""", (*args, limit)).fetchall()
        return {"events": [dict(row) for row in rows], "total": total}

    def get(self, item_id):
        with self.store.db() as db:
            self._check_chat(db)
            row = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
        return dict(row) if row else None

    def save(self, body: EventBody, item_id=None, expected_updated=None):
        item = {**body.model_dump(), "id": item_id or uuid.uuid4().hex, "scope_id": self.store.scope_id, "created": now(), "updated": now()}
        item.update(reminder_at=reminder_time(body.starts_at, body.reminder_minutes), reminder_sent=0)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_chat(db)
            if item_id:
                old = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
                if not old:
                    raise ValueError("Событие уже удалено или находится в другом пространстве")
                if expected_updated and old["updated"] != expected_updated:
                    raise ValueError("Событие изменилось в другом окне. Откройте его в календаре заново")
                item["created"] = old["created"]
                # Windows may return the same wall-clock timestamp for two edits.
                item["updated"] = max(datetime.fromisoformat(item["updated"]), datetime.fromisoformat(old["updated"]) + timedelta(microseconds=1)).isoformat(timespec="microseconds")
                changed = old["starts_at"] != item["starts_at"] or old["reminder_minutes"] != item["reminder_minutes"]
                item["reminder_sent"] = 0 if changed else old["reminder_sent"]
                if changed:
                    db.execute("DELETE FROM calendar_alerts WHERE event_id=? AND delivered=0", (item_id,))
                columns = [key for key in item if key not in {"id", "scope_id", "created"}]
                db.execute("UPDATE calendar_events SET " + ",".join(f"{key}=:{key}" for key in columns) + " WHERE id=:id", item)
            else:
                columns = ",".join(item)
                db.execute(f"INSERT INTO calendar_events ({columns}) VALUES ({','.join(':' + key for key in item)})", item)
        return item

    def remove(self, item_id, expected_updated=None):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_chat(db)
            item = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
            if not item:
                raise ValueError("Событие уже удалено или находится в другом пространстве")
            if expected_updated and item["updated"] != expected_updated:
                raise ValueError("Событие изменилось в другом окне. Откройте его в календаре заново")
            db.execute("DELETE FROM calendar_events WHERE id=?", (item_id,))
            db.execute("DELETE FROM calendar_alerts WHERE event_id=?", (item_id,))

    def _check_chat(self, db):
        row = db.execute("SELECT project_id FROM conversations WHERE id=?", (self.store.conversation_id,)).fetchone()
        if row is None or (row[0] or "") != self.store.scope_id:
            raise ValueError("Чат удалён или перемещён. Выберите его заново")
