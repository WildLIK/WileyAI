"""Validated local wall-clock schedules; no model, cron service or extra runtime."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class RepeatRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule: Literal["daily", "weekdays", "weekly"]
    weekday: StrictInt | None = Field(default=None, ge=0, le=6)
    weekdays: list[StrictInt] = Field(default_factory=list, max_length=7)
    timezone: str = Field(default="UTC", max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Неизвестный часовой пояс повтора")
        return value

    @model_validator(mode="after")
    def valid_days(self):
        if any(not 0 <= day <= 6 for day in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Дни повтора должны быть разными числами от 0 до 6")
        if self.rule == "weekly":
            if (self.weekday is None) == (not self.weekdays):
                raise ValueError("Выберите один или несколько дней недели")
        elif self.weekday is not None or self.weekdays:
            raise ValueError("Для этого повтора отдельные дни не задаются")
        return self

    def days(self):
        return set(range(7)) if self.rule == "daily" else set(range(5)) if self.rule == "weekdays" else set(self.weekdays or [self.weekday])


@dataclass(frozen=True)
class Recurrence:
    rule: str
    weekday: int | None = None
    weekdays: tuple[int, ...] = ()


FORMS = {
    "понедельник": 0, "понедельника": 0, "понедельникам": 0,
    "вторник": 1, "вторника": 1, "вторникам": 1,
    "среду": 2, "среды": 2, "средам": 2,
    "четверг": 3, "четверга": 3, "четвергам": 3,
    "пятницу": 4, "пятницы": 4, "пятницам": 4,
    "субботу": 5, "субботы": 5, "субботам": 5,
    "воскресенье": 6, "воскресенья": 6, "воскресеньям": 6,
}
DAY_NAMES = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]
DAY_PATTERN = "(?:" + "|".join(sorted(FORMS, key=len, reverse=True)) + ")"
DAY_RULE = re.compile(r"\b(?:(?:еженедельно\s+)?(?:каждый|каждую|каждое|каждые|по)\s+)" + DAY_PATTERN + r"(?:\s*(?:,\s*(?:и\s+)?|\s+и\s+)(?:по\s+)?" + DAY_PATTERN + r")*\b", re.I)
SIMPLE_RULES = [
    (re.compile(r"\b(?:ежедневно|каждый день|каждые сутки)\b", re.I), Recurrence("daily")),
    (re.compile(r"\b(?:по будням|каждый будний день|в будни|по рабочим дням)\b", re.I), Recurrence("weekdays")),
    (re.compile(r"\b(?:по выходным|каждые выходные)\b", re.I), Recurrence("weekly", weekdays=(5, 6))),
]


def split_recurrence(text):
    matches = [(match, rule) for pattern, rule in SIMPLE_RULES for match in pattern.finditer(text)]
    for match in DAY_RULE.finditer(text):
        days = sorted({FORMS[word] for word in re.findall(DAY_PATTERN, match[0].casefold())})
        matches.append((match, Recurrence("weekly", weekday=days[0]) if len(days) == 1 else Recurrence("weekly", weekdays=tuple(days))))
    if len(matches) > 1:
        raise ValueError("Укажите одно правило повтора: ежедневно, по будням или по выбранным дням недели.")
    rule = matches[0][1] if matches else None
    rest = text
    if matches:
        match = matches[0][0]
        rest = text[:match.start()] + " " + text[match.end():]
    if re.search(r"\b(?:ежедневно|еженедельно|каждый|каждую|каждые|каждое)\b", rest, re.I) or re.search(r"\b(?:или|либо)\s+" + DAY_PATTERN, rest, re.I):
        raise ValueError("Поддерживаются повторы ежедневно, по будням и по дням недели. Например: «по понедельникам и средам в 10».")
    return rule, re.sub(r"\s+", " ", rest).strip()


def parse_recurrence(text):
    return split_recurrence(text)[0]


def recurrence_label(rule):
    if rule.rule == "daily":
        return "ежедневно"
    if rule.rule == "weekdays":
        return "по будням"
    days = sorted(rule.weekdays or [rule.weekday])
    return "по " + ", ".join(DAY_NAMES[day] for day in days)


def validate(value, kind, due):
    if value is None:
        return None
    if kind not in {"reminder", "alarm"} or not due:
        raise ValueError("Повтор доступен для напоминания или будильника с указанным временем")
    RepeatRule.model_validate_json(value)
    if datetime.fromisoformat(due).tzinfo is None:
        raise ValueError("Для повтора нужно время с часовым поясом")
    return value


def wall_time(day, clock, zone):
    value = datetime.combine(day, clock.replace(tzinfo=None), zone).replace(fold=0)
    if value.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value.replace(tzinfo=None):
        return None  # A spring clock jump skips this day's occurrence.
    return value


def next_due(base: datetime, rule: RepeatRule, after: datetime | None = None):
    zone = ZoneInfo(rule.timezone)
    local = base.astimezone(zone)
    after = (after or base).astimezone(timezone.utc)
    day = max(local.date() + timedelta(days=1), after.astimezone(zone).date())
    for offset in range(15):
        candidate_day = day + timedelta(days=offset)
        if candidate_day.weekday() in rule.days():
            candidate = wall_time(candidate_day, local.timetz(), zone)
            if candidate and candidate.astimezone(timezone.utc) > after:
                return candidate
    raise ValueError("Не удалось вычислить следующий срок повтора")


def first_due(now: datetime, rule: RepeatRule, clock: time, day: date | None = None):
    zone = ZoneInfo(rule.timezone)
    now = now.astimezone(zone)
    if day is not None:
        candidate = wall_time(day, clock, zone)
        if day.weekday() not in rule.days():
            raise ValueError("Эта дата не входит в выбранные дни повтора. Укажите подходящий день или измените повтор в разделе «Задачи».")
        if candidate is None:
            raise ValueError("Это местное время пропускается при переводе часов. Выберите другое время.")
        if candidate.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
            raise ValueError("Это время уже прошло. Укажите будущую дату и время.")
        return candidate
    for offset in range(15):
        candidate_day = now.date() + timedelta(days=offset)
        candidate = wall_time(candidate_day, clock, zone) if candidate_day.weekday() in rule.days() else None
        if candidate and candidate.astimezone(timezone.utc) > now.astimezone(timezone.utc):
            return candidate
    raise ValueError("Не удалось вычислить первый срок повтора")


def next_recurrence(base: datetime, recurrence: Recurrence):
    zone = getattr(base.tzinfo, "key", "UTC")
    return next_due(base, RepeatRule(rule=recurrence.rule, weekday=recurrence.weekday, weekdays=list(recurrence.weekdays), timezone=zone))
