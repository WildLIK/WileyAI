"""Local intent execution for a bounded grammar; LLM prose never triggers mutations."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .storage import Store
from .timeparse import describe_due, due_time, parse_time


LABELS = {"todo": "Задача", "reminder": "Напоминание", "timer": "Таймер", "alarm": "Будильник"}
CONTEXT_SECONDS = 15 * 60


@dataclass
class Result:
    text: str
    changed: list[str] = field(default_factory=list)


class Workflows:
    def __init__(self, store: Store):
        self.store = store

    def handle(self, text: str, zone: str | None = None, now: datetime | None = None, name: str = "Уайли") -> Result | None:
        zone_info = ZoneInfo(zone) if zone else datetime.now().astimezone().tzinfo
        now = (now or datetime.now(timezone.utc)).astimezone(zone_info)
        state = self.store.dialogue()
        if now.timestamp() - state.get("updated", 0) > CONTEXT_SECONDS or state.get("zone", str(zone_info)) != str(zone_info):
            state = {"calendar": state["calendar"]} if "calendar" in state else {}
        value = re.sub(r"\s+", " ", text.strip()).strip()
        value = re.sub(r"^" + re.escape(name) + r"[,!]?[ ]+", "", value, flags=re.I)
        value = re.sub(r"^пожалуйста[, ]+", "", value, flags=re.I)
        value = re.sub(r",? пожалуйста[.!]*$", "", value, flags=re.I).rstrip(".!")
        normalized = value.casefold().replace("ё", "е")
        read_query = re.fullmatch(r"(?:покажи|список|покажи список|какие у меня) (?:все )?(?:задачи|задач|напоминания|напоминаний)", normalized.rstrip("?"))
        # Questions about commands, quoted examples and negative sentences are not actions.
        if ("?" in value and not read_query) or value.startswith(('"', '«', '“')) or normalized.startswith("не "):
            if state.get("last_task") and normalized in {"а если я буду занят?", "а если я буду занята?"}:
                return Result("Можно перенести напоминание. Например: «перенеси на 11» или «перенеси на завтра в 12».")
            return None

        def remember():
            state["updated"] = now.timestamp()
            state["zone"] = str(zone_info)
            self.store.save_dialogue(state)

        if state.get("pending") and (normalized in {"отмена", "отмени", "не надо", "передумал", "передумала"} or re.fullmatch(r"отмени (?:это |эту |этот )?(?:напоминание|задачу|таймер|будильник)", normalized)):
            state.pop("pending", None)
            remember()
            return Result("Отменил уточнение. Задачи не изменены.")

        note = re.fullmatch(r"(?:создай|добавь|запиши) заметку\s*[:—-]?\s*(.*)", value, re.I)
        if note:
            body = note[1].strip()
            if not body:
                return Result("Что записать? Например: «создай заметку Покупки: хлеб и молоко».")
            title, separator, content = body.partition(":")
            if not separator:
                content, title = body, body[:80]
            if not title.strip() or len(title.strip()) > 200:
                return Result("Название заметки должно содержать от 1 до 200 символов.")
            item = self.store.save_note(title.strip(), content.strip())
            self.store.audit("note", item["id"], "created")
            state.pop("pending", None)
            remember()
            return Result(f"Создал заметку «{item['title']}». Она доступна в разделе «Заметки».", ["notes"])

        if read_query:
            items = [item for item in self.store.list("tasks", 500) if not item["done"]]
            items.sort(key=lambda item: item["due"] or "9999")
            if not items:
                return Result("Незавершённых задач и напоминаний пока нет.")
            lines = []
            for item in items[:8]:
                due = datetime.fromisoformat(item["due"]).astimezone(zone_info) if item["due"] else None
                lines.append(f"{LABELS[item['kind']]}: {item['title']}" + (f" — {describe_due(due)}" if due else ""))
            return Result("\n".join(lines) + ("\nОстальные записи — в разделе «Задачи»." if len(items) > 8 else ""))

        create = re.fullmatch(r"(напомни(?: мне)?|создай напоминание|(?:создай|добавь) задачу|добавь в список дел|(?:поставь|запусти|установи) таймер|(?:поставь|установи) будильник)\s*[:,—-]?\s*(.*)", value, re.I)
        if create:
            verb = create[1].casefold()
            kind = "timer" if "таймер" in verb else "alarm" if "будильник" in verb else "todo" if "задачу" in verb or "список дел" in verb else "reminder"
            body = re.sub(r"^пожалуйста[, ]+", "", create[2], flags=re.I)
            if kind == "timer" and body.strip() and not re.match(r"(?:на|через)\b", body, re.I):
                body = "на " + body
            parts = parse_time(body, now, clock_context=kind != "timer")
            if parts.error:
                return Result(parts.error)
            title = parts.rest or ({"timer": "Таймер", "alarm": "Будильник"}.get(kind, ""))
            if len(title) > 500:
                return Result("Название задачи должно быть короче 500 символов.")
            draft = {"kind": kind, "title": title, "day": parts.day.isoformat() if parts.day else None, "clock": parts.clock.isoformat() if parts.clock else None, "seconds": parts.seconds}
            return self._create(draft, state, now, remember)

        pending = state.get("pending")
        if pending:
            parts = parse_time(value, now, bare=True, clock_context=pending["draft"]["kind"] != "timer")
            if parts.error:
                return Result(parts.error)
            if parts.found:
                draft = dict(pending["draft"])
                if parts.rest and not re.fullmatch(r"(?:нет|лучше|тогда|да)[, ]*", parts.rest, re.I):
                    # Do not hide an extra task, condition or alternative inside a time slot.
                    return Result("Укажите только дату и время, например «завтра в 10», или скажите «отмена».")
                if parts.day:
                    draft.update(day=parts.day.isoformat(), seconds=None)
                if parts.clock:
                    draft.update(clock=parts.clock.isoformat(), seconds=None)
                if parts.seconds is not None:
                    draft.update(day=None, clock=None, seconds=parts.seconds)
                if pending.get("task_id"):
                    return self._reschedule(pending["task_id"], draft, state, now, remember)
                return self._create(draft, state, now, remember)
            if not pending["draft"].get("title") and not re.match(r"(?:открой|запусти|запомни|привет|спасибо|расскажи|покажи|перенеси|отмени|удали|что|как|почему|можешь|ты)\b", normalized):
                draft = {**pending["draft"], "title": value}
                return self._create(draft, state, now, remember)

        move = re.fullmatch(r"(?:перенеси|перенести|переставь)(?: (?:это |эту |этот )?(?:напоминание|задачу|таймер|будильник|его|ее|её))?\s+(.+)", value, re.I)
        implicit_move = re.fullmatch(r"(?:нет,?\s+|лучше\s+|тогда\s+)((?:в|на|завтра|послезавтра|сегодня|через)\b.+)", value, re.I)
        if move or implicit_move:
            task = self._recent(state)
            if not task:
                return Result("Не вижу недавнюю задачу для переноса. Создайте напоминание в этом диалоге или выберите запись в разделе «Задачи».")
            body = (move or implicit_move)[1]
            body = re.sub(r"^на\s+(?=завтра|послезавтра|сегодня|\d{1,2}\.)", "", body, flags=re.I)
            parts = parse_time(body, now, clock_context=True)
            if parts.error:
                return Result(parts.error)
            if not parts.found or parts.rest not in {"", "позже", "раньше"}:
                return Result("Укажите новое время, например «перенеси на 11» или «перенеси на завтра в 12».")
            old = datetime.fromisoformat(task["due"]).astimezone(zone_info) if task["due"] else None
            if parts.seconds is not None and body.casefold().startswith("на "):
                if old is None:
                    return Result("У этой задачи ещё нет срока. Укажите дату и время, например «перенеси на завтра в 12».")
                shifted = (old.astimezone(timezone.utc) + timedelta(seconds=parts.seconds * (-1 if parts.rest == "раньше" else 1))).astimezone(zone_info)
                parts.day, parts.clock, parts.seconds = shifted.date(), shifted.timetz().replace(tzinfo=None), None
            elif parts.rest:
                return Result("Для сдвига срока скажите, например, «перенеси на 15 минут позже».")
            draft = {"kind": task["kind"], "title": task["title"], "day": (parts.day or (old.date() if old else None)).isoformat() if parts.day or old else None, "clock": (parts.clock or (old.timetz().replace(tzinfo=None) if old else None)).isoformat() if parts.clock or old else None, "seconds": parts.seconds}
            return self._reschedule(task["id"], draft, state, now, remember)

        cancel = re.fullmatch(r"(?:отмени|удали) (?:это |эту |этот |последнее |последнюю |последний )?(напоминание|задачу|таймер|будильник)", normalized)
        complete = re.fullmatch(r"(?:отметь (?:эту )?задачу (?:выполненной|завершенной)|задача выполнена|я это сделал|я это сделала)", normalized)
        if cancel or complete:
            task = self._recent(state)
            expected = {"напоминание": "reminder", "таймер": "timer", "будильник": "alarm"}.get(cancel[1]) if cancel else None
            if not task or (expected and expected != task["kind"]):
                return Result("Не вижу подходящую недавнюю запись. Выберите её в разделе «Задачи».")
            if cancel:
                self.store.remove("tasks", task["id"])
                state.pop("last_task", None)
                action, answer = "deleted", f"Отменил: «{task['title']}». Запись удалена из задач."
            else:
                if not self.store.revise_task(task["id"], done=True):
                    return Result("Эта задача уже удалена. Ничего не изменил.")
                action, answer = "completed", f"Отметил выполненной задачу «{task['title']}»."
            state.pop("pending", None)
            remember()
            self.store.audit("task", task["id"], action)
            return Result(answer, ["tasks"])
        if re.match(r"^(?:перенесено|перенесена|перенесен|переноси|перенеси|перенести|переставь)\b", normalized):
            return Result("Срок не менял: не распознал точную команду переноса. Повторите, например: «перенеси напоминание на одиннадцать часов».")
        return None

    def _recent(self, state):
        task = self.store.task(state.get("last_task", ""))
        return task if task and not task["done"] else None

    def _create(self, draft, state, now, remember):
        if len(draft["title"]) > 500:
            return Result("Название задачи должно быть короче 500 символов.")
        try:
            due = self._due(draft, now)
        except ValueError as error:
            return Result(str(error))
        if not draft["title"] or (due is None and (draft["kind"] != "todo" or draft.get("day"))):
            if due:
                draft.update(day=due.date().isoformat(), clock=due.timetz().replace(tzinfo=None).isoformat(), seconds=None)
            state["pending"] = {"draft": draft}
            remember()
            if not draft["title"]:
                return Result("Что нужно сделать или о чём напомнить?")
            return Result(f"Когда напомнить: «{draft['title']}»? Например: «завтра в 10» или «через 15 минут». Пока запись не создана.")
        item = self.store.save_task(draft["title"], draft["kind"], due.astimezone(timezone.utc).isoformat() if due else None)
        state.pop("pending", None)
        state["last_task"] = item["id"]
        remember()
        self.store.audit("task", item["id"], "created")
        verb = {"todo": "создана", "reminder": "создано", "timer": "создан", "alarm": "создан"}[item["kind"]]
        return Result(f"{LABELS[item['kind']]} {verb}: «{item['title']}»" + (f" — {describe_due(due)}." if due else "."), ["tasks"])

    def _reschedule(self, task_id, draft, state, now, remember):
        try:
            due = self._due(draft, now)
        except ValueError as error:
            return Result(str(error))
        if due is None:
            state["pending"] = {"draft": draft, "task_id": task_id}
            remember()
            return Result("На какое время перенести? Например: «в 11».")
        item = self.store.revise_task(task_id, due=due.astimezone(timezone.utc).isoformat())
        if not item:
            state.pop("pending", None)
            state.pop("last_task", None)
            remember()
            return Result("Эта задача уже удалена. Ничего не изменил.")
        state.pop("pending", None)
        state["last_task"] = task_id
        remember()
        self.store.audit("task", task_id, "rescheduled")
        return Result(f"Перенёс «{item['title']}» на {describe_due(due)}.", ["tasks"])

    @staticmethod
    def _due(draft, now):
        return due_time(date.fromisoformat(draft["day"]) if draft.get("day") else None, time.fromisoformat(draft["clock"]) if draft.get("clock") else None, now, draft.get("seconds"))
