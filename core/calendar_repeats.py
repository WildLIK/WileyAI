"""Bounded expansion of civil calendar dates, independent of storage and notifications."""
from datetime import date, datetime, timedelta, timezone
import json
import calendar as civil_calendar
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from .repeats import RepeatRule, wall_time


class EventRepeat(RepeatRule):
    rule: Literal["daily", "weekdays", "weekly", "monthly"]
    until: str | None = None
    monthday: int | None = Field(default=None, ge=-1, le=31, strict=True)
    excluded: list[str] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def calendar_fields(self):
        if self.monthday == 0 or (self.monthday is not None and self.rule != "monthly"):
            raise ValueError("Число месяца допустимо только для месячного повтора: 1–31 или -1 для последнего дня")
        if len(set(self.excluded)) != len(self.excluded):
            raise ValueError("Исключённые даты не должны повторяться")
        for value in self.excluded:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Дата исключения нужна в формате ГГГГ-ММ-ДД")
        return self

    def matches(self, day, first, days=None):
        return (day.day == (civil_calendar.monthrange(day.year, day.month)[1] if self.monthday == -1 else self.monthday or first.day)) if self.rule == "monthly" else day.weekday() in (days if days is not None else self.days())

    @field_validator("until")
    @classmethod
    def valid_until(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Последний день повтора нужен в формате ГГГГ-ММ-ДД")
        return value


def repeat_value(value):
    return json.loads(value) if isinstance(value, str) else value


def occurrences(event, start, end):
    """Yield overlapping UTC intervals. Preserve local clock time through DST.

    Spring gaps skip an occurrence; folds use the first instant. End dates of
    all-day events are exclusive. Iteration is bounded by the requested window.
    """
    first = datetime.fromisoformat(event["starts_at"])
    last = datetime.fromisoformat(event["ends_at"])
    rule = repeat_value(event.get("recurrence"))
    if not rule:
        if first < end and last > start:
            yield first, last
        return
    rule = EventRepeat.model_validate(rule)
    zone = ZoneInfo(event["timezone"])
    local_start, local_end = first.astimezone(zone), last.astimezone(zone)
    length = local_end.date() - local_start.date()
    day = max(local_start.date(), start.astimezone(zone).date() - length - timedelta(days=1))
    finish = min(end.astimezone(zone).date() + timedelta(days=1), date.max - timedelta(days=1))
    if rule.until:
        finish = min(finish, date.fromisoformat(rule.until))
    days, excluded = rule.days(), set(rule.excluded)
    while day <= finish:
        if rule.matches(day, local_start.date(), days) and day.isoformat() not in excluded:
            begin = wall_time(day, local_start.timetz(), zone)
            stop = wall_time(day + length, local_end.timetz(), zone)
            if begin and stop:
                begin, stop = begin.astimezone(timezone.utc), stop.astimezone(timezone.utc)
                if begin >= first and begin < end and stop > start and stop > begin:
                    yield begin, stop
        day += timedelta(days=1)
