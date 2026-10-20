"""Local, project-scoped calendar with explicitly enabled event reminders."""
from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage import Store, now
from .notifications import reminder_time
from .calendar_repeats import EventRepeat, occurrences, repeat_value


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
    all_day: bool = False
    recurrence: EventRepeat | None = None

    @classmethod
    def from_item(cls, item, **changes):
        values = {key: item[key] for key in cls.model_fields}
        values["recurrence"] = repeat_value(values["recurrence"])
        return cls.model_validate({**values, **changes})

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
        zone = calendar_zone(self.timezone)
        values = [value + "T00:00" if self.all_day and len(value) == 10 else value for value in (self.starts_at, self.ends_at)]
        start, end = [instant(value, self.timezone) for value in values]
        duration = end - start
        if self.all_day:
            local_start, local_end = start.astimezone(zone), end.astimezone(zone)
            if any((value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0) for value in (local_start, local_end)):
                raise ValueError("Событие на весь день должно начинаться и заканчиваться в местную полночь")
            duration = local_end.replace(tzinfo=None) - local_start.replace(tzinfo=None)
        if not timedelta(0) < duration <= timedelta(days=31):
            raise ValueError("Окончание должно быть позже начала; длительность — не больше 31 дня")
        if self.recurrence:
            self.recurrence.timezone = self.timezone
            first_day = start.astimezone(zone).date()
            if not self.recurrence.matches(first_day, first_day):
                raise ValueError("Первый день события не входит в выбранные дни повтора")
            if self.recurrence.rule == "monthly" and self.recurrence.monthday is None:
                self.recurrence.monthday = first_day.day
            if self.recurrence.until and self.recurrence.until < first_day.isoformat():
                raise ValueError("Последний день повтора раньше первого события")
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
        with self.store.db() as db:
            db.execute("BEGIN")
            self._check_chat(db)
            rows = db.execute("SELECT * FROM calendar_events WHERE scope_id=? AND starts_at<? AND (ends_at>? OR recurrence IS NOT NULL) LIMIT 2001",
                              (self.store.scope_id, timestamp(end), timestamp(start))).fetchall()
        if len(rows) > 2000:
            raise ValueError("Слишком много серий в календаре. Сократите период или число событий")
        events = []
        for row in rows:
            item = dict(row)
            for begin, stop in occurrences(item, start, end):
                events.append({**item, "starts_at": timestamp(begin), "ends_at": timestamp(stop), "conflict": False})
                if len(events) > 10000:
                    raise ValueError("Слишком много повторов. Выберите более короткий период")
        events.sort(key=lambda item: (item["starts_at"], item["ends_at"], item["id"]))
        active = []
        for item in events:
            active = [other for other in active if other["ends_at"] > item["starts_at"]]
            if active:
                item["conflict"] = True
                for other in active:
                    other["conflict"] = True
            active.append(item)
        return {"events": events[:limit], "total": len(events)}

    def get(self, item_id):
        with self.store.db() as db:
            self._check_chat(db)
            row = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
        return dict(row) if row else None

    def save(self, body: EventBody, item_id=None, expected_updated=None, *, connection=None):
        item = {**body.model_dump(), "id": item_id or uuid.uuid4().hex, "scope_id": self.store.scope_id, "created": now(), "updated": now()}
        item["all_day"] = int(body.all_day)
        item["recurrence"] = body.recurrence.model_dump_json() if body.recurrence else None
        item.update(parent_id=None, original_start=None)
        item.update(reminder_at=reminder_time(body.starts_at, body.reminder_minutes), reminder_sent=0, reminder_cursor=None)
        with (nullcontext(connection) if connection is not None else self.store.db()) as db:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            self._check_chat(db)
            if item_id:
                old = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
                if not old:
                    raise ValueError("Событие уже удалено или находится в другом пространстве")
                if expected_updated and old["updated"] != expected_updated:
                    raise ValueError("Событие изменилось в другом окне. Откройте его в календаре заново")
                item["created"] = old["created"]
                item.update(parent_id=old["parent_id"], original_start=old["original_start"])
                # Windows may return the same wall-clock timestamp for two edits.
                item["updated"] = max(datetime.fromisoformat(item["updated"]), datetime.fromisoformat(old["updated"]) + timedelta(microseconds=1)).isoformat(timespec="microseconds")
                changed = any(old[key] != item[key] for key in ("starts_at", "ends_at", "timezone", "all_day", "recurrence", "reminder_minutes"))
                if old["recurrence"] and not item["recurrence"]:
                    db.execute("UPDATE calendar_events SET parent_id=NULL,original_start=NULL WHERE parent_id=?", (item_id,))
                item["reminder_sent"] = 0 if changed else old["reminder_sent"]
                item["reminder_cursor"] = None if changed else old["reminder_cursor"]
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
            children = [row[0] for row in db.execute("SELECT id FROM calendar_events WHERE parent_id=? AND scope_id=?", (item_id, self.store.scope_id))]
            for selected in [item_id, *children]:
                db.execute("DELETE FROM calendar_events WHERE id=?", (selected,))
                db.execute("DELETE FROM calendar_alerts WHERE event_id=?", (selected,))

    def occurrence(self, item_id, original_start, expected_updated, replacement=None):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_chat(db)
            row = db.execute("SELECT * FROM calendar_events WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
            if not row or not row["recurrence"] or row["updated"] != expected_updated:
                raise ValueError("Серия удалена или изменилась. Откройте расписание заново")
            item = dict(row)
            begin = instant(original_start)
            if not any(first == begin for first, _ in occurrences(item, begin, begin + timedelta(microseconds=1))):
                raise ValueError("Такого вхождения нет в серии или оно уже изменено")
            rule = EventRepeat.model_validate_json(item["recurrence"])
            rule.excluded.append(begin.astimezone(calendar_zone(item["timezone"])).date().isoformat())
            rule = EventRepeat.model_validate(rule.model_dump())
            self.save(EventBody.from_item(item, recurrence=rule), item_id, expected_updated, connection=db)
            result = None
            if replacement:
                if replacement.recurrence:
                    raise ValueError("Перенос отдельного вхождения не создаёт новую серию")
                result = self.save(replacement, connection=db)
                db.execute("UPDATE calendar_events SET parent_id=?,original_start=? WHERE id=?", (item_id, timestamp(begin), result["id"]))
                result.update(parent_id=item_id,original_start=timestamp(begin))
            return result or {"cancelled": True}

    def _check_chat(self, db):
        row = db.execute("SELECT project_id FROM conversations WHERE id=?", (self.store.conversation_id,)).fetchone()
        if row is None or (row[0] or "") != self.store.scope_id:
            raise ValueError("Чат удалён или перемещён. Выберите его заново")


class OccurrenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_start: str = Field(max_length=100)
    expected_updated: str = Field(max_length=100)
    replacement: EventBody | None = None
