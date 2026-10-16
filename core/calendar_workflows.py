"""Explicit Russian calendar commands, independent of model-generated text."""
from datetime import date, datetime, time, timedelta, timezone
import re

from .calendar import Calendar, EventBody, calendar_zone, instant
from .timeparse import parse_time, due_time, describe_due, NUMBER
from .workflows import Result, CONTEXT_SECONDS


class CalendarWorkflows:
    def __init__(self, store):
        self.store = store
        self.calendar = Calendar(store)

    def expire_unanswered(self):
        """A short reply may only answer the immediately preceding calendar prompt."""
        state = self.store.dialogue()
        context = state.get("calendar", {})
        if context.get("pending"):
            messages = self.store.list("messages", 2)
            expected = f"Когда начнётся встреча «{context['pending']['title']}»?"
            if len(messages) != 2 or messages[0]["role"] != "assistant" or not messages[0]["content"].startswith(expected):
                context.pop("pending", None)
                self.store.save_dialogue(state)

    def handle(self, text, zone=None, now=None, name="Уайли"):
        zone = zone or "UTC"
        tz = calendar_zone(zone)
        now = (now or datetime.now(timezone.utc)).astimezone(tz)
        value = re.sub(r"\s+", " ", text.strip())
        value = re.sub(r"^" + re.escape(name) + r"[,!]?[ ]+", "", value, flags=re.I)
        value = re.sub(r"^пожалуйста[, ]+", "", value, flags=re.I)
        value = re.sub(r",? пожалуйста[.!]*$", "", value, flags=re.I).rstrip(".!")
        normalized = value.casefold().replace("ё", "е")
        state = self.store.dialogue()
        context = state.get("calendar", {})
        if now.timestamp() - context.get("updated", 0) > CONTEXT_SECONDS or context.get("zone") != zone:
            context = {}

        def remember():
            context.update(updated=now.timestamp(), zone=zone)
            state["calendar"] = context
            # Only one clarification can own a short time-only reply.
            state.pop("pending", None)
            self.store.save_dialogue(state)

        read = re.fullmatch(r"(?:покажи (?:мое |моё )?(?:расписание|календарь)|что у меня в календаре)(?: (.+?))?\??", normalized)
        if value.startswith(('"', '«', '“')) or normalized.startswith("не ") and normalized != "не надо" or ("?" in value and not read):
            return None
        if read:
            period = re.sub(r"^на\s+", "", (read[1] or "сегодня").rstrip("?"))
            days = 7 if period in {"неделю", "7 дней", "ближайшую неделю"} else 1
            if days == 7:
                day = now.date()
            else:
                parts = parse_time(period, now)
                if parts.error or not parts.day or parts.clock or parts.seconds is not None or parts.rest:
                    return Result("Укажите день или неделю: «покажи расписание завтра» или «покажи расписание на неделю».")
                day = parts.day
            start = datetime.combine(day, time.min, tz)
            end = datetime.combine(day + timedelta(days=days), time.min, tz)
            items = self.calendar.list(start.isoformat(), end.isoformat(), limit=8)
            if not items["total"]:
                return Result("В выбранном периоде событий нет. Это локальный календарь текущего пространства.")
            lines = []
            for item in items["events"]:
                begin, finish = instant(item["starts_at"]).astimezone(tz), instant(item["ends_at"]).astimezone(tz)
                lines.append(f"{begin:%d.%m %H:%M} — {finish:%d.%m %H:%M}: {item['title']}" + (" · пересечение" if item["conflict"] else ""))
            return Result("Локальное расписание:\n" + "\n".join(lines) + ("\nОстальные события — в разделе «Календарь»." if items["total"] > 8 else ""))

        create = re.fullmatch(r"(?:(?:создай|добавь|запланируй) (?:встречу|событие)(?: в календарь)?|добавь в календарь)\s*[:—-]?\s*(.*)", value, re.I)
        move = re.fullmatch(r"перенеси (?:эту |это |последнюю |последнее )?(?:встречу|событие)\s+(.+)", value, re.I)
        cancel = re.fullmatch(r"(?:отмени|удали) (?:эту |это |последнюю |последнее )?(?:встречу|событие)", normalized)
        alert = re.fullmatch(r"напомни (?:о встрече|об этой встрече|о событии) (за .+|в начале)", normalized)
        disable_alert = re.fullmatch(r"отключи напоминание (?:о встрече|об этой встрече|о событии)", normalized)
        if create:
            raw = create[1]
            reminder = re.search(r"[,;]?\s+(?:и\s+)?напомни (за .+|в начале)$", raw, re.I)
            reminder_minutes = None
            if reminder:
                try:
                    reminder_minutes = self._reminder_minutes(reminder[1], now)
                except ValueError as error:
                    return Result(str(error))
                raw = raw[:reminder.start()].strip()
            elif re.search(r"\bнапомни\b", raw, re.I):
                return Result("Укажите напоминание в конце команды: «создай встречу Обзор завтра в 10, напомни за 15 минут».")
            duration = re.search(rf"\bна\s+(?:полчаса|полтора часа|{NUMBER}\s*(?:минут[ауы]?|час(?:а|ов)?)(?:\s+(?:и\s+)?{NUMBER}\s*минут[ауы]?)?)\b", raw, re.I)
            parsed_duration = parse_time(duration[0], now) if duration else None
            if parsed_duration and (parsed_duration.error or parsed_duration.seconds is None):
                return Result("Не распознал длительность. Укажите, например, «на 30 минут».")
            minutes = parsed_duration.seconds / 60 if parsed_duration and parsed_duration.seconds is not None else 60
            if not 1 <= minutes <= 24 * 60:
                return Result("Для команды чата укажите длительность от 1 до 1440 минут. Более длинное событие можно добавить в календаре.")
            body = raw[:duration.start()] + raw[duration.end():] if duration else raw
            parts = parse_time(body, now, clock_context=True)
            if parts.error:
                return Result(parts.error)
            if parts.seconds is not None and not re.search(r"\bчерез\b", body, re.I):
                return Result("Для начала укажите «в 10» или «через 15 минут», длительность — «на 30 минут».")
            draft = {"title": parts.rest, "day": parts.day.isoformat() if parts.day else None,
                     "clock": parts.clock.isoformat() if parts.clock else None, "seconds": parts.seconds, "minutes": minutes, "reminder_minutes": reminder_minutes}
            return self._create(draft, context, now, zone, remember)

        if context.get("pending"):
            if alert or disable_alert:
                try:
                    context["pending"]["reminder_minutes"] = self._reminder_minutes(alert[1], now) if alert else None
                except ValueError as error:
                    return Result(str(error))
                remember()
                return Result(f"Когда начнётся встреча «{context['pending']['title']}»? Напоминание настроено в черновике, событие пока не создано.")
            if normalized in {"отмена", "отмени", "не надо", "передумал", "передумала"} or cancel:
                context.pop("pending", None)
                remember()
                return Result("Отменил создание события. Календарь не изменён.")
            if not move:
                parts = parse_time(value, now, bare=True, clock_context=True)
                if parts.found and not parts.rest and not parts.error:
                    draft = dict(context["pending"])
                    if parts.day:
                        draft.update(day=parts.day.isoformat(), seconds=None)
                    if parts.clock:
                        draft.update(clock=parts.clock.isoformat(), seconds=None)
                    if parts.seconds is not None:
                        draft.update(day=None, clock=None, seconds=parts.seconds)
                    return self._create(draft, context, now, zone, remember)
                # An unrelated turn must not leave a hidden calendar draft alive.
                context.pop("pending", None)
                state["calendar"] = context
                self.store.save_dialogue(state)

        if move or cancel or alert or disable_alert:
            item = self.calendar.get(context.get("last_id", ""))
            if not item:
                return Result("Не вижу недавнюю встречу в этом чате. Выберите событие в разделе «Календарь».")
            if item["updated"] != context.get("last_updated"):
                return Result("Эта встреча уже изменена в другом окне. Выберите её в календаре заново.")
            if alert or disable_alert:
                try:
                    minutes = self._reminder_minutes(alert[1], now) if alert else None
                except ValueError as error:
                    return Result(str(error))
                item = self.calendar.save(EventBody(**{key: item[key] for key in EventBody.model_fields if key != "reminder_minutes"}, reminder_minutes=minutes), item["id"], context["last_updated"])
                context.update(last_updated=item["updated"])
                remember()
                self.store.audit("calendar", item["id"], "reminder_changed")
                return Result(f"Встреча «{item['title']}»: " + self._reminder_text(item), ["calendar"])
            if cancel:
                self.calendar.remove(item["id"], context["last_updated"])
                context.clear()
                remember()
                self.store.audit("calendar", item["id"], "deleted")
                return Result(f"Удалил событие «{item['title']}» из локального календаря.", ["calendar"])
            body = re.sub(r"^на\s+(?=завтра|послезавтра|сегодня|\d{1,2}\.)", "", move[1], flags=re.I)
            parts = parse_time(body, now, clock_context=True)
            if parts.error or not parts.found or parts.rest not in {"", "позже", "раньше"}:
                return Result("Укажите новое начало: «перенеси встречу на завтра в 11». Длительность сохранится.")
            old = instant(item["starts_at"]).astimezone(tz)
            if parts.seconds is not None and body.casefold().startswith("на "):
                shifted = (old.astimezone(timezone.utc) + timedelta(seconds=parts.seconds * (-1 if parts.rest == "раньше" else 1))).astimezone(tz)
                parts.day, parts.clock, parts.seconds = shifted.date(), shifted.time(), None
            elif parts.rest:
                return Result("Для сдвига времени скажите, например, «перенеси встречу на 15 минут позже».")
            try:
                begin = due_time(parts.day or old.date(), parts.clock or old.time(), now, parts.seconds)
            except ValueError as error:
                return Result(str(error))
            finish = begin.astimezone(timezone.utc) + (instant(item["ends_at"]) - instant(item["starts_at"]))
            body = EventBody(**{key: item[key] for key in EventBody.model_fields if key not in {"starts_at", "ends_at", "timezone"}},
                             starts_at=begin.isoformat(), ends_at=finish.isoformat(), timezone=zone)
            item = self.calendar.save(body, item["id"], context["last_updated"])
            context.update(last_updated=item["updated"])
            remember()
            self.store.audit("calendar", item["id"], "rescheduled")
            return Result(f"Перенёс встречу «{item['title']}» на {describe_due(begin)}. Длительность сохранена. " + self._reminder_text(item), ["calendar"])
        return None

    def _create(self, draft, context, now, zone, remember):
        if not draft["title"] or len(draft["title"]) > 200:
            return Result("Укажите название до 200 символов: «создай встречу Обсуждение проекта завтра в 10 на 30 минут».")
        try:
            begin = due_time(date.fromisoformat(draft["day"]) if draft.get("day") else None,
                             time.fromisoformat(draft["clock"]) if draft.get("clock") else None, now, draft.get("seconds"))
        except ValueError as error:
            return Result(str(error))
        if begin is None:
            context["pending"] = draft
            remember()
            return Result(f"Когда начнётся встреча «{draft['title']}»? Например: «завтра в 10». Событие пока не создано.")
        finish = begin.astimezone(timezone.utc) + timedelta(minutes=draft["minutes"])
        item = self.calendar.save(EventBody(title=draft["title"], starts_at=begin.isoformat(), ends_at=finish.isoformat(), timezone=zone, reminder_minutes=draft.get("reminder_minutes")))
        context.pop("pending", None)
        context.update(last_id=item["id"], last_updated=item["updated"])
        remember()
        self.store.audit("calendar", item["id"], "created")
        overlap = self.calendar.list(item["starts_at"], item["ends_at"])["total"] > 1
        return Result(f"Создал встречу «{item['title']}» — {describe_due(begin)}, на {draft['minutes']:g} мин."
                      + (" Есть пересечение с другим событием." if overlap else "")
                      + " Локальный календарь; " + self._reminder_text(item).lower(), ["calendar"])

    @staticmethod
    def _reminder_minutes(value, now):
        value = value.casefold().strip()
        if value == "в начале":
            return 0
        parts = parse_time(re.sub(r"^за\s+", "через ", value), now)
        if parts.error or parts.rest or parts.seconds is None or parts.seconds % 60 or not 60 <= parts.seconds <= 10080 * 60:
            raise ValueError("Для напоминания укажите целые минуты от 1 до 10080, например «за 15 минут», или «в начале».")
        return int(parts.seconds // 60)

    @staticmethod
    def _reminder_text(item):
        minutes = item["reminder_minutes"]
        if minutes is None:
            return "Уведомление не установлено."
        return "Напоминание в начале встречи." if minutes == 0 else f"Напоминание за {minutes} мин. до начала."
