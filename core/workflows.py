"""Local intent execution for a bounded grammar; LLM prose never triggers mutations."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .storage import Store
from .timeparse import describe_due, due_time, parse_time, parse_recurrence, recurrence_label, Recurrence
from .repeats import RepeatRule, first_due
from . import task_selection as selection


LABELS = {"todo": "Задача", "reminder": "Напоминание", "timer": "Таймер", "alarm": "Будильник"}
CONTEXT_SECONDS = 15 * 60


@dataclass
class Result:
    text: str
    changed: list[str] = field(default_factory=list)


class Workflows:
    def __init__(self, store: Store):
        self.store = store

    def expire_unanswered(self):
        """Only the immediately preceding task question can own a short reply."""
        state = self.store.dialogue()
        question = state.get("task_choice", {}).get("question") or state.get("pending", {}).get("prompt")
        if question:
            messages = self.store.list("messages", 2)
            if len(messages) != 2 or messages[0]["role"] != "assistant" or messages[0]["content"] != question:
                state.pop("task_choice", None)
                if state.get("pending", {}).get("prompt"):
                    state.pop("pending", None)
                self.store.save_dialogue(state)

    def handle(self, text: str, zone: str | None = None, now: datetime | None = None, name: str = "Уайли") -> Result | None:
        # Piper/espeak can change LC_CTYPE on Windows. Python may then expose
        # surrogate bytes in the localized zone name. The unnamed fixed offset
        # preserves the same fallback time semantics without storing that name.
        zone_info = ZoneInfo(zone) if zone else timezone(datetime.now().astimezone().utcoffset())
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

        choice = state.get("task_choice")
        if choice:
            number = selection.choice_number(value)
            if normalized in {"отмена", "отмени", "не надо", "передумал", "передумала"}:
                state.pop("task_choice", None)
                remember()
                return Result("Выбор отменён. Задачи не изменены.")
            if number is not None or normalized in {"да", "этот", "это", "выбираю"}:
                if number is None or not 1 <= number <= len(choice["options"]):
                    return Result(choice["question"])
                state.pop("task_choice", None)
                remember()
                task = self.store.task(choice["options"][number - 1]["id"])
                expected = choice["options"][number - 1]
                if not task or selection.snapshot(task) != expected or choice["scope_id"] != self.store.scope_id:
                    return Result("Запись изменилась или удалена после выбора. Повторите поиск: ничего не изменено.")
                return self._selected(task, choice["action"], choice["timing"], state, now, remember,
                                      expected, datetime.fromisoformat(choice["requested_at"]).astimezone(zone_info))
            state.pop("task_choice", None)
            remember()

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
                repeat = " · " + recurrence_label(RepeatRule.model_validate_json(item["recurrence"])) if item.get("recurrence") else ""
                lines.append(f"{LABELS[item['kind']]}: {item['title']}" + (f" — {describe_due(due)}" if due else "") + repeat)
            return Result("\n".join(lines) + ("\nОстальные записи — в разделе «Задачи»." if len(items) > 8 else ""))

        create = re.fullmatch(r"(напомни(?: мне)?|создай напоминание|(?:создай|добавь) задачу|добавь в список дел|(?:поставь|запусти|установи) таймер|(?:поставь|установи) будильник)\s*[:,—-]?\s*(.*)", value, re.I)
        if create:
            state.pop("task_choice", None)
            verb = create[1].casefold()
            kind = "timer" if "таймер" in verb else "alarm" if "будильник" in verb else "todo" if "задачу" in verb or "список дел" in verb else "reminder"
            body = re.sub(r"^пожалуйста[, ]+", "", create[2], flags=re.I)
            try:
                recurrence = parse_recurrence(body)
            except ValueError as error:
                return Result(str(error))
            if recurrence and kind not in {"reminder", "alarm"}:
                return Result("Повтор доступен для напоминаний и будильников. Например: «напомни ежедневно в 10 проверить почту».")
            if kind == "timer" and body.strip() and not re.match(r"(?:на|через)\b", body, re.I):
                body = "на " + body
            parts = parse_time(body, now, clock_context=kind != "timer", allow_recurrence=True)
            if parts.error:
                return Result(parts.error)
            title = parts.rest or ({"timer": "Таймер", "alarm": "Будильник"}.get(kind, ""))
            if len(title) > 500:
                return Result("Название задачи должно быть короче 500 символов.")
            if recurrence and not isinstance(zone_info, ZoneInfo):
                return Result("Для повторов нужен часовой пояс. Создайте напоминание из чата программы или раздела «Задачи».")
            draft = {"kind": kind, "title": title, "day": parts.day.isoformat() if parts.day else None, "clock": parts.clock.isoformat() if parts.clock else None, "seconds": parts.seconds, "recurrence": self._rec_json(recurrence, str(zone_info))}
            return self._create(draft, state, now, remember)

        named = selection.command(value)
        if named:
            state.pop("pending", None)
            state.pop("task_choice", None)
            state.pop("last_task", None)
            remember()
            try:
                tasks = selection.find(self.store, named.query, named.kind, now,
                                       include_stopped=named.action in {"find", "delete", "resume"})
            except ValueError as error:
                return Result(str(error))
            if not tasks:
                return Result("Не найдено подходящей записи в текущем пространстве. Уточните название/срок или откройте раздел «Задачи».")
            if len(tasks) > 8:
                return Result("Найдено больше восьми записей. Уточните название или дату, например «найди напоминание купить хлеб на завтра». Задачи не изменены.")
            if len(tasks) == 1:
                return self._selected(tasks[0], named.action, named.timing, state, now, remember, selection.snapshot(tasks[0]), now)
            question = selection.question(tasks, zone_info)
            state["task_choice"] = dict(action=named.action, timing=named.timing, options=[selection.snapshot(task) for task in tasks],
                                        question=question, requested_at=now.isoformat(), scope_id=self.store.scope_id)
            remember()
            return Result(question)

        pending = state.get("pending")
        if pending:
            if pending["draft"].get("recurrence") and re.fullmatch(r"(?:отмени|отключи|убери) повтор(?: напоминания)?", normalized):
                pending["draft"]["recurrence"] = None
                remember()
                return Result("Повтор в новом напоминании отменён. Укажите оставшиеся данные или скажите «отмена».")
            try:
                pending_recurrence = parse_recurrence(value)
            except ValueError as error:
                return Result(str(error))
            parts = parse_time(value, now, bare=True, clock_context=pending["draft"]["kind"] != "timer", allow_recurrence=True)
            if parts.error:
                return Result(parts.error)
            if parts.found or pending_recurrence:
                draft = dict(pending["draft"])
                if pending_recurrence:
                    if draft["kind"] not in {"reminder", "alarm"} or not isinstance(zone_info, ZoneInfo):
                        return Result("Повтор доступен для напоминаний и будильников с часовым поясом.")
                    draft["recurrence"] = self._rec_json(pending_recurrence, str(zone_info))
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
            return self._move_task(task, (move or implicit_move)[1], state, now, remember)

        cancel = re.fullmatch(r"(?:отмени|удали) (?:это |эту |этот |последнее |последнюю |последний )?(напоминание|задачу|таймер|будильник)", normalized)
        complete = re.fullmatch(r"(?:отметь (?:эту )?задачу (?:выполненной|завершенной)|задача выполнена|я это сделал|я это сделала)", normalized)
        cancel_series = re.fullmatch(r"(?:отмени|удали|убери|отключи) (?:повтор|серию|повторение|повторения|повторяющееся напоминание|расписание)(?: (?:напоминания|задачи|этого|этой))?", normalized)
        if cancel or complete or cancel_series:
            task = self._recent(state)
            expected = {"напоминание": "reminder", "таймер": "timer", "будильник": "alarm"}.get(cancel[1]) if cancel else None
            if not task or (expected and expected != task["kind"]):
                return Result("Не вижу подходящую недавнюю запись. Выберите её в разделе «Задачи».")
            if cancel_series:
                if re.search(r"\b(?:серию|повторяющееся напоминание)\b", normalized):
                    self.store.remove("tasks", task["id"])
                    self.store.audit("task", task["id"], "series_deleted")
                    state.pop("last_task", None)
                    state.pop("pending", None)
                    remember()
                    return Result(f"Отменил серию: «{task['title']}». Запись удалена из задач.", ["tasks"])
                if not task.get("recurrence"):
                    return Result("Это напоминание не повторяется.")
                self.store.revise_task(task["id"], recurrence=None)
                self.store.audit("task", task["id"], "series_cancelled")
                state["last_task"] = task["id"]
                remember()
                return Result(f"Повтор отменён: «{task['title']}» больше не будет повторяться. Ближайшее напоминание осталось однократным; «отмени напоминание» удалит его полностью.", ["tasks"])
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

    def _selected(self, task, action, timing, state, now, remember, expected, requested_at):
        try:
            if action == "move":
                return self._move_task(task, timing, state, now, remember, expected, requested_at)
            if action == "find":
                state["last_task"] = task["id"]
                remember()
                if task["done"]:
                    return Result("Найдена запись: " + selection.describe(task, now.tzinfo) + ". Для редактирования откройте «Задачи».")
                return Result("Выбрана запись: " + selection.describe(task, now.tzinfo) + ". Можно сказать «перенеси на 11» или «отмени это напоминание».")
            if action in {"stop", "resume", "no_repeat"} and not task.get("recurrence"):
                return Result("Эта запись не повторяется. Ничего не изменено.")
            if action == "resume" and not task["done"]:
                return Result("Эта серия уже включена. Ничего не изменено.")
            if action == "delete":
                self.store.remove("tasks", task["id"], expected=expected)
                state.pop("last_task", None)
                answer = f"Удалил: «{task['title']}». Запись удалена из задач."
            else:
                changes = {"recurrence": None} if action == "no_repeat" else {"done": action != "resume"}
                self.store.revise_task(task["id"], expected=expected, **changes)
                state["last_task"] = task["id"]
                answer = {
                    "complete": f"Отметил выполненной задачу «{task['title']}».",
                    "stop": f"Серия «{task['title']}» остановлена.",
                    "resume": f"Серия «{task['title']}» возобновлена.",
                    "no_repeat": f"Повтор отменён: «{task['title']}». Ближайший срок остался однократным.",
                }[action]
            state.pop("pending", None)
            remember()
            self.store.audit("task", task["id"], "selected_" + action)
            return Result(answer, ["tasks"])
        except ValueError as error:
            state.pop("pending", None)
            remember()
            return Result(str(error))

    def _move_task(self, task, body, state, now, remember, expected=None, requested_at=None):
        draft = {"kind": task["kind"], "title": task["title"], "day": None, "clock": None,
                 "seconds": None, "recurrence": task.get("recurrence")}
        if expected is not None:
            draft["expected"] = expected
        if not body:
            return self._reschedule(task["id"], draft, state, now, remember)
        anchor = requested_at or now
        body = re.sub(r"^на\s+(?=завтра|послезавтра|сегодня|\d{1,2}\.)", "", body, flags=re.I)
        parts = parse_time(body, anchor, clock_context=True)
        if parts.error:
            return Result(parts.error)
        if not parts.found or parts.rest not in {"", "позже", "раньше"}:
            return Result("Укажите новое время, например «перенеси на 11» или «перенеси на завтра в 12».")
        old = datetime.fromisoformat(task["due"]).astimezone(now.tzinfo) if task["due"] else None
        if parts.seconds is not None:
            if body.casefold().startswith("на "):
                if old is None:
                    return Result("У этой задачи ещё нет срока. Укажите дату и время, например «перенеси на завтра в 12».")
                base = old
            elif parts.rest:
                return Result("Для сдвига срока скажите, например, «перенеси на 15 минут позже».")
            else:
                base = anchor
            shifted = (base.astimezone(timezone.utc) + timedelta(seconds=parts.seconds * (-1 if parts.rest == "раньше" else 1))).astimezone(now.tzinfo)
            parts.day, parts.clock, parts.seconds = shifted.date(), shifted.timetz().replace(tzinfo=None), None
        elif parts.rest:
            return Result("Для сдвига срока скажите, например, «перенеси на 15 минут позже».")
        day = parts.day or (old.date() if old and old.date() > now.date() else None)
        clock = parts.clock or (old.timetz().replace(tzinfo=None) if old else None)
        draft.update(day=day.isoformat() if day else None, clock=clock.isoformat() if clock else None, seconds=parts.seconds)
        return self._reschedule(task["id"], draft, state, now, remember)

    @staticmethod
    def _rec_json(rec: Recurrence | None, zone="UTC") -> str | None:
        if rec is None:
            return None
        return RepeatRule(rule=rec.rule, weekday=rec.weekday, weekdays=list(rec.weekdays), timezone=zone).model_dump_json(exclude_defaults=True)

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
        rec_json = draft.get("recurrence")
        item = self.store.save_task(draft["title"], draft["kind"], due.astimezone(timezone.utc).isoformat() if due else None, recurrence=rec_json)
        state.pop("pending", None)
        state["last_task"] = item["id"]
        remember()
        self.store.audit("task", item["id"], "created")
        verb = {"todo": "создана", "reminder": "создано", "timer": "создан", "alarm": "создан"}[item["kind"]]
        rec_suffix = ""
        if rec_json:
            rec_suffix = " — " + recurrence_label(RepeatRule.model_validate_json(rec_json))
        return Result(f"{LABELS[item['kind']]} {verb}: «{item['title']}»" + (f" — {describe_due(due)}" if due else "") + rec_suffix + ".", ["tasks"])

    def _reschedule(self, task_id, draft, state, now, remember):
        try:
            due = self._due(draft, now)
        except ValueError as error:
            if state.get("pending", {}).get("prompt"):
                state["pending"]["prompt"] = str(error)
                remember()
            return Result(str(error))
        if due is None:
            prompt = "На какое время перенести? Например: «в 11»."
            state["pending"] = {"draft": draft, "task_id": task_id, **({"prompt": prompt} if draft.get("expected") else {})}
            remember()
            return Result(prompt)
        try:
            item = self.store.revise_task(task_id, expected=draft.get("expected"), due=due.astimezone(timezone.utc).isoformat(), recurrence=draft.get("recurrence"))
        except ValueError as error:
            state.pop("pending", None)
            remember()
            return Result(str(error))
        if not item:
            state.pop("pending", None)
            state.pop("last_task", None)
            remember()
            return Result("Эта задача уже удалена. Ничего не изменил.")
        state.pop("pending", None)
        state["last_task"] = task_id
        remember()
        self.store.audit("task", task_id, "rescheduled")
        suffix = " Время будущих повторов изменено; дни недели сохранены." if item.get("recurrence") else ""
        return Result(f"Перенёс «{item['title']}» на {describe_due(due)}." + suffix, ["tasks"])

    @staticmethod
    def _due(draft, now):
        if draft.get("recurrence"):
            if draft.get("seconds") is not None:
                raise ValueError("Для повтора укажите время суток, например «ежедневно в 10», а не интервал.")
            if not draft.get("clock"):
                return None
            return first_due(now, RepeatRule.model_validate_json(draft["recurrence"]), time.fromisoformat(draft["clock"]), date.fromisoformat(draft["day"]) if draft.get("day") else None)
        return due_time(date.fromisoformat(draft["day"]) if draft.get("day") else None, time.fromisoformat(draft["clock"]) if draft.get("clock") else None, now, draft.get("seconds"))
