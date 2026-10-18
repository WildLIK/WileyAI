"""Literal task lookup and numbered clarification, scoped to the current project."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from .timeparse import parse_time, describe_due, recurrence_label
from .repeats import RepeatRule

KINDS = {"задачу": "todo", "задача": "todo", "задачи": "todo", "напоминание": "reminder", "напоминания": "reminder", "таймер": "timer", "таймера": "timer", "будильник": "alarm", "будильника": "alarm"}
NOUN = "(?:задачу|задача|напоминание|таймер|будильник)"
SERIES_NOUN = "(?:напоминание|напоминания|задачи|будильник|будильника)"
SNAPSHOT = ("id", "title", "kind", "due", "done", "recurrence", "scope_id")
NUMBERS = {"первое": 1, "первую": 1, "первый": 1, "второе": 2, "вторую": 2, "второй": 2,
           "третье": 3, "третью": 3, "третий": 3, "четвертое": 4, "пятое": 5, "шестое": 6, "седьмое": 7, "восьмое": 8}


def key(text):
    return " ".join(re.findall(r"\w+", text.casefold().replace("ё", "е")))


def snapshot(task):
    return {field: task.get(field) for field in SNAPSHOT}


def choice_number(text):
    text = text.casefold().replace("ё", "е").strip(" .!")
    text = re.sub(r"^(?:номер|выбираю|выбери)\s+", "", text)
    return int(text) if re.fullmatch(r"\d{1,2}", text) else NUMBERS.get(text)


@dataclass(frozen=True)
class Command:
    action: str
    kind: str
    query: str
    timing: str = ""


def command(text):
    """Only explicit user commands; quoted whole commands and questions are gated upstream."""
    patterns = [
        ("find", rf"(?:найди|покажи|выбери) ({NOUN})(?:\s+(.*))?"),
        ("delete", rf"(?:удали|отмени) ({NOUN})\s+(.+)"),
        ("complete", rf"(?:заверши|выполни) ({NOUN})\s+(.+)"),
        ("complete", rf"отметь ({NOUN})\s+(.+?)\s+(?:выполненной|завершенной|выполненным|завершенным)"),
        ("stop", rf"(?:останови|приостанови) (?:серию|повтор) ({SERIES_NOUN})\s+(.+)"),
        ("resume", rf"возобнови (?:серию|повтор) ({SERIES_NOUN})\s+(.+)"),
        ("no_repeat", rf"(?:отмени|отключи|убери) повтор ({SERIES_NOUN})\s+(.+)"),
        ("move", rf"(?:перенеси|перенести|переставь) ({NOUN})\s+(.+)"),
    ]
    for action, pattern in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if not match:
            continue
        query = (match[2] or "").strip()
        # These are the existing recent-task commands, not literal names.
        if query.casefold() in {"это", "эту", "этот", "его", "ее", "её"}:
            return None
        if action == "move":
            if re.match(r"^(?:на|в|через|сегодня|завтра|послезавтра)\b", query, re.I):
                return None
            # An explicit name can contain 'на'. The final unquoted delimiter is
            # the new deadline; quoted names make date-like titles unambiguous.
            quoted = re.match(r'^[«"](.+?)[»"](?:\s+(.*))?$', query)
            if quoted:
                query, timing = quoted[1], quoted[2] or ""
                query = "«" + query + "»"
            else:
                splits = list(re.finditer(r"\s+(?=на\s+|через\s+)", query, re.I))
                if splits:
                    split = splits[-1].start()
                    query, timing = query[:split].strip(), query[split:].strip()
                else:
                    timing = ""
            return Command(action, KINDS[match[1].casefold()], query, timing)
        return Command(action, KINDS[match[1].casefold()], query)
    return None


def selector(query, now):
    """A quoted name is literal. Otherwise a trailing date/time can narrow it."""
    query = re.sub(r"^(?:про|о|об|с названием|под названием)\s+", "", query, flags=re.I).strip()
    quoted = re.fullmatch(r'[«"](.+?)[»"](?:\s+(.*))?', query)
    text, filters = (quoted[1], quoted[2] or "") if quoted else (None, query)
    # Past dates are meaningful for lookup, even though new deadlines must be future.
    old = re.search(r"\b(?:(?:на|с)\s+)?(позавчера|вчера)\b", filters, re.I)
    old_day = None
    if old:
        old_day = now.date() - timedelta(days=2 if old[1].casefold() == "позавчера" else 1)
        filters = filters[:old.start()] + " " + filters[old.end():]
    filters = re.sub(r"\bс\s+(?=\d{1,2}\.\d{1,2}|сегодня\b|завтра\b|послезавтра\b)", "на ", filters, flags=re.I)
    parts = parse_time(filters, now, clock_context=True)
    if parts.error:
        raise ValueError(parts.error)
    if parts.seconds is not None or (old_day and parts.day):
        raise ValueError("Для поиска укажите одну дату и/или время суток, без интервала.")
    if quoted and parts.rest:
        raise ValueError("После названия в кавычках укажите только дату или время.")
    title = key(text if quoted else parts.rest)
    if not title and not (old_day or parts.day or parts.clock):
        raise ValueError("Укажите название или срок. Например: «найди напоминание купить хлеб на завтра».")
    if len(title) > 500 or len(title.split()) > 40:
        raise ValueError("Укажите более короткое название задачи.")
    return title, old_day or parts.day, parts.clock


def find(store, query, kind, now, include_stopped=False):
    title, day, clock = selector(query, now)
    words = title.split()
    def match(raw_title, raw_due):
        candidate = key(raw_title)
        if any(not any(word.startswith(part) for word in candidate.split()) for part in words):
            return 0
        due = datetime.fromisoformat(raw_due).astimezone(now.tzinfo) if raw_due else None
        return int((not day or due is not None and due.date() == day) and
                   (not clock or due is not None and (due.hour, due.minute) == (clock.hour, clock.minute)))
    with store.db() as db:
        db.create_function("task_match", 2, match)
        db.create_function("task_key", 1, key)
        where = "scope_id=? AND kind=? AND (? OR done=0) AND task_match(title,due)=1"
        args = (store.scope_id, kind, int(include_stopped))
        # Exact names take precedence. Otherwise show all prefix-word matches,
        # never silently truncate to the most recently created 500 tasks.
        if title and db.execute("SELECT 1 FROM tasks WHERE " + where + " AND task_key(title)=? LIMIT 1", (*args, title)).fetchone():
            where += " AND task_key(title)=?"
            args += (title,)
        rows = db.execute("SELECT * FROM tasks WHERE " + where + " ORDER BY due IS NULL,due,created,id LIMIT 9", args).fetchall()
    return [dict(row) for row in rows]


def describe(task, zone):
    due = describe_due(datetime.fromisoformat(task["due"]).astimezone(zone)) if task["due"] else "без срока"
    repeat = " · " + recurrence_label(RepeatRule.model_validate_json(task["recurrence"])) if task.get("recurrence") else ""
    stopped = " · остановлено/выполнено" if task["done"] else ""
    return f"«{task['title']}» — {due}{repeat}{stopped}"


def question(tasks, zone):
    return "Найдено несколько записей в текущем пространстве:\n" + "\n".join(
        f"{index}. {describe(task, zone)}" for index, task in enumerate(tasks, 1)
    ) + "\nОтветьте номером записи или скажите «отмена»."
