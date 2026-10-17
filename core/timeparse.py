"""Small, explicit Russian date grammar. Unclear dates never become guessed actions."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re


from .repeats import Recurrence, parse_recurrence, recurrence_label, next_recurrence, split_recurrence


ONES = {"ноль": 0, "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9}
TEENS = dict(zip("десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать".split(), range(10, 20)))
TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50}
NUMBERS = {**ONES, **TEENS, **TENS}
NUMBERS.update({f"{tens} {one}": total + value for tens, total in TENS.items() for one, value in ONES.items() if 0 < value < 10})
NUMBER = r"(?:\d+(?:[,.]\d+)?|" + "|".join(re.escape(word) for word in sorted(NUMBERS, key=len, reverse=True)) + r")"
INTEGER = r"(?:\d{1,2}|" + "|".join(re.escape(word) for word in sorted(NUMBERS, key=len, reverse=True)) + r")"
WEEKDAYS = {"понедельник": 0, "вторник": 1, "среду": 2, "четверг": 3, "пятницу": 4, "субботу": 5, "воскресенье": 6}


@dataclass
class TimeParts:
    rest: str
    day: date | None = None
    clock: time | None = None
    seconds: float | None = None
    found: bool = False
    error: str = ""


def number(value: str) -> float:
    return float(NUMBERS[value]) if value in NUMBERS else float(value.replace(",", "."))


def parse_time(text: str, now: datetime, bare: bool = False, clock_context: bool = False, allow_recurrence: bool = False) -> TimeParts:
    result = TimeParts(text)
    value = text.casefold().replace("ё", "е")
    spans = []
    try:
        recurrence, text = split_recurrence(text)
        if recurrence and not allow_recurrence:
            return TimeParts(rest=text, error="В этой команде повторы пока не поддерживаются. Повторяющееся напоминание можно создать в разделе «Задачи».")
    except ValueError as error:
        result.error = str(error)
        return result
    value = text.casefold().replace("ё", "е")
    if re.search(rf"\b(?:или|либо)\s+(?:в\b|на\b|завтра\b|сегодня\b|послезавтра\b|{INTEGER}\b)", value):
        result.error = "В реплике несколько вариантов времени. Укажите один."
        return result

    half = re.search(r"\b(?:через|на)\s+(полчаса|полтора часа|полторы минуты)\b", value)
    duration = re.search(rf"\b(?:через|на)\s+({NUMBER})\s*(секунд[ауы]?|минут[ауы]?|час(?:а|ов)?)\b", value)
    # «Будильник на одиннадцать часов» is 11:00; «таймер на 11 часов» is an interval.
    # An explicit «позже/раньше» or «через» always denotes an interval.
    if duration and clock_context and duration[0].startswith("на ") and duration[2].startswith("час") and not re.search(r"\b(?:позже|раньше)\b", value):
        duration = None
    if half or duration:
        match = half or duration
        if half:
            seconds = {"полчаса": 1800, "полтора часа": 5400, "полторы минуты": 90}[half[1]]
        else:
            scale = 3600 if duration[2].startswith("час") else 60 if duration[2].startswith("минут") else 1
            seconds = number(duration[1]) * scale
        end = match.end()
        # A combined duration: «на 1 час 30 минут».
        extra = re.match(rf"\s+(?:и\s+)?({NUMBER})\s*(секунд[ауы]?|минут[ауы]?|час(?:а|ов)?)\b", value[end:])
        if extra:
            seconds += number(extra[1]) * (3600 if extra[2].startswith("час") else 60 if extra[2].startswith("минут") else 1)
            end += extra.end()
        result.found = True
        if not 1 <= seconds <= 366 * 86400:
            result.error = "Интервал должен быть от секунды до 366 дней."
            return result
        result.seconds = seconds
        spans.append((match.start(), end))
        value = value[:match.start()] + " " * (end - match.start()) + value[end:]

    clock_pattern = rf"\b(?:в|на)\s+({INTEGER})(?::([0-9]{{2}})|\s+({INTEGER}))?(?:\s+час(?:а|ов)?)?(?:\s+(утра|вечера|дня|ночи))?\b(?![.:]\d)"
    clocks = list(re.finditer(clock_pattern, value))
    if bare and not clocks:
        match = re.fullmatch(rf"\s*({INTEGER})(?:[:.]([0-9]{{2}})|\s+({INTEGER}))?\s*[.!]?", value)
        if match:
            value = "в " + value.strip().rstrip(".!")
            # Recurse only for the explicitly requested missing time slot.
            return parse_time(value, now, clock_context=clock_context, allow_recurrence=allow_recurrence)
    if len(clocks) > 1:
        result.error = "В реплике несколько вариантов времени. Укажите один."
        return result
    if clocks:
        match = clocks[0]
        hour = int(number(match[1]))
        minute = int(match[2]) if match[2] else int(number(match[3])) if match[3] else 0
        if re.match(r"[:.]\d", value[match.end():]):
            result.error = "Укажите минуты двумя цифрами, например «в 10:05»."
            return result
        period = match[4]
        if period:
            if not 1 <= hour <= 12:
                result.error = "Для времени с указанием части суток используйте часы от 1 до 12."
                return result
            hour = hour % 12 + (12 if period in {"вечера", "дня"} else 0)
        if hour > 23 or minute > 59:
            result.error = "Такого времени нет. Укажите часы 0–23 и минуты 0–59."
            return result
        result.clock = time(hour, minute)
        result.found = True
        spans.append(match.span())
        value = value[:match.start()] + " " * (match.end() - match.start()) + value[match.end():]

    day_matches = list(re.finditer(r"\b(?:(?:на|к|в)\s+)?(послезавтра|завтра|сегодня)\b|\b(?:(?:в|на)\s+)?(" + "|".join(WEEKDAYS) + r")\b|(?<!\w)(?:(?:на|к|в)\s+)?(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\d)", value))
    if len(day_matches) > 1:
        result.error = "Укажите одну дату для напоминания."
        return result
    if day_matches:
        match = day_matches[0]
        if match[1]:
            result.day = now.date() + timedelta(days={"сегодня": 0, "завтра": 1, "послезавтра": 2}[match[1]])
        elif match[2]:
            result.day = now.date() + timedelta(days=(WEEKDAYS[match[2]] - now.weekday()) % 7)
        else:
            try:
                result.day = date(int(match[5] or now.year), int(match[4]), int(match[3]))
                if not match[5] and result.day < now.date():
                    result.day = result.day.replace(year=now.year + 1)
            except ValueError:
                result.error = "Такой даты нет. Укажите дату в формате ДД.ММ.ГГГГ."
                return result
        result.found = True
        spans.append(match.span())
    if result.seconds is not None and (result.day or result.clock):
        result.error = "Назовите либо интервал, либо дату и время, чтобы не смешать два срока."
        return result
    remaining = list(text)
    for start, end in spans:
        remaining[start:end] = " " * (end - start)
    result.rest = re.sub(r"\s+", " ", "".join(remaining)).strip(" ,:;.!—-")
    return result


def due_time(day: date | None, clock: time | None, now: datetime, seconds: float | None = None) -> datetime | None:
    if seconds is not None:
        return (now.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(now.tzinfo)
    if clock is None:
        return None
    candidate = datetime.combine(day or now.date(), clock, now.tzinfo)
    if day is None and candidate <= now:
        candidate += timedelta(days=1)
    wall = candidate.replace(tzinfo=None)
    if candidate.astimezone(timezone.utc).astimezone(now.tzinfo).replace(tzinfo=None) != wall:
        raise ValueError("Это местное время пропускается при переводе часов. Выберите другое время.")
    if candidate.replace(fold=0).utcoffset() != candidate.replace(fold=1).utcoffset():
        raise ValueError("Это местное время встречается дважды при переводе часов. Выберите другое время или задайте срок в разделе «Задачи».")
    if candidate <= now:
        raise ValueError("Это время уже прошло. Укажите будущую дату и время.")
    return candidate


def describe_due(due: datetime) -> str:
    offset = due.strftime("%z")
    pattern = "%d.%m.%Y в %H:%M:%S" if due.second or due.microsecond else "%d.%m.%Y в %H:%M"
    return due.strftime(pattern) + f" (UTC{offset[:3]}:{offset[3:]})"
