"""Explicit, previewed exchange of calendar events. No background remote writes.

ETags protect Google edits. A persistent idempotency link precedes every insert,
so an interrupted request can be reconciled without inserting duplicates.
Remote deletions are never inferred from a window or propagated automatically.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .calendar import Calendar, EventBody, calendar_zone, instant, timestamp
from .calendar_repeats import EventRepeat, repeat_value
from .google_calendar_auth import GoogleAuth, GoogleError

BASE = "https://www.googleapis.com/calendar/v3"
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class GoogleClientBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: str = Field(max_length=16384)


class GoogleBindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar_id: str = Field(min_length=1, max_length=1024)


class GooglePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str


class GoogleChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    direction: str = Field(pattern="^(google|local)$")


class GoogleApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=1, max_length=100)
    choices: list[GoogleChoice] = Field(min_length=1, max_length=20)


def text_field(event, key, maximum, default=""):
    value = event.get(key, default)
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Поле Google «" + key + "» слишком длинное или некорректное; событие пропущено")
    return value


def event_body(event, zone):
    if event.get("eventType", "default") != "default" or event.get("status") == "cancelled":
        raise ValueError("Специальное или удалённое событие Google не переносится")
    start, end = event.get("start", {}), event.get("end", {})
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError("Некорректные даты Google")
    all_day = "date" in start
    if all_day != ("date" in end):
        raise ValueError("Некорректные даты Google")
    zone = start.get("timeZone", zone)
    values = {"title": text_field(event, "summary", 200, "Без названия"), "starts_at": start.get("date" if all_day else "dateTime", ""),
              "ends_at": end.get("date" if all_day else "dateTime", ""), "timezone": zone,
              "all_day": all_day, "location": text_field(event, "location", 500), "description": text_field(event, "description", 10000)}
    recurrence = event.get("recurrence")
    if recurrence:
        if not isinstance(recurrence, list) or not 1 <= len(recurrence) <= 2 or not isinstance(recurrence[0], str) or not recurrence[0].startswith("RRULE:"):
            raise ValueError("Сложный повтор Google нельзя заменить локальным правилом")
        pairs = recurrence[0][6:].split(";")
        fields = dict(pair.split("=", 1) for pair in pairs if "=" in pair)
        if len(fields) != len(pairs) or set(fields) - {"FREQ", "BYDAY", "BYMONTHDAY", "UNTIL"}:
            raise ValueError("Этот повтор Google пока не поддерживается")
        rule = {"rule": "daily", "timezone": zone}
        if "BYMONTHDAY" in fields and fields.get("FREQ") != "MONTHLY":
            raise ValueError("BYMONTHDAY поддерживается только для месячного повтора")
        if fields.get("FREQ") == "WEEKLY":
            days = fields.get("BYDAY", "").split(",")
            if not days or any(day not in DAYS for day in days):
                raise ValueError("Неподдерживаемые дни повтора Google")
            rule.update(rule="weekly", weekdays=sorted(DAYS.index(day) for day in days))
        elif fields.get("FREQ") == "MONTHLY" and "BYDAY" not in fields:
            rule.update(rule="monthly", monthday=int(fields.get("BYMONTHDAY", str(int(values["starts_at"][8:10])))))
        elif fields.get("FREQ") != "DAILY" or "BYDAY" in fields or "BYMONTHDAY" in fields:
            raise ValueError("Поддерживаются ежедневные и недельные повторы")
        if fields.get("UNTIL"):
            until = fields["UNTIL"]
            rule["until"] = (datetime.strptime(until, "%Y%m%d").date().isoformat() if len(until) == 8 else
                             datetime.strptime(until, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).date().isoformat())
        if len(recurrence) == 2:
            excluded = recurrence[1]
            prefix = "EXDATE;VALUE=DATE:" if all_day else "EXDATE:"
            if not isinstance(excluded, str) or not excluded.startswith(prefix) or len(excluded) > 20000:
                raise ValueError("Неподдерживаемые исключения Google")
            rule["excluded"]=[]
            first=instant(EventBody.model_validate(values).starts_at).astimezone(ZoneInfo(zone))
            from .repeats import wall_time
            for value in excluded[len(prefix):].split(","):
                if all_day:
                    day=datetime.strptime(value,"%Y%m%d").date()
                else:
                    moment=datetime.strptime(value,"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    day=moment.astimezone(ZoneInfo(zone)).date()
                    expected=wall_time(day,first.timetz(),ZoneInfo(zone))
                    if not expected or moment!=expected.astimezone(timezone.utc): raise ValueError("Время исключения Google не соответствует локальной серии")
                rule["excluded"].append(day.isoformat())
        values["recurrence"] = rule
    return EventBody.model_validate(values)


def google_body(body):
    zone = ZoneInfo(body.timezone)
    def endpoint(value):
        local = instant(value).astimezone(zone)
        return {"date": local.date().isoformat()} if body.all_day else {"dateTime": local.isoformat(), "timeZone": body.timezone}
    result = {"summary": body.title, "start": endpoint(body.starts_at), "end": endpoint(body.ends_at),
              "location": body.location, "description": body.description, "recurrence": []}
    if body.recurrence:
        rule = body.recurrence
        rrule = "FREQ=MONTHLY;BYMONTHDAY=" + str(rule.monthday) if rule.rule == "monthly" else "FREQ=DAILY" if rule.rule == "daily" else "FREQ=WEEKLY;BYDAY=" + ",".join(DAYS[day] for day in sorted(rule.days()))
        if rule.until:
            # RFC5545 requires a UTC UNTIL for a DTSTART with a time zone.
            until = datetime.fromisoformat(rule.until + "T23:59:59").replace(tzinfo=zone)
            rrule += ";UNTIL=" + (until.strftime("%Y%m%d") if body.all_day else until.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        result["recurrence"] = ["RRULE:" + rrule]
        if rule.excluded:
            first = instant(body.starts_at).astimezone(zone)
            values = [datetime.fromisoformat(day).replace(hour=first.hour, minute=first.minute, second=first.second, tzinfo=zone) for day in sorted(rule.excluded)]
            result["recurrence"].append(("EXDATE;VALUE=DATE:" if body.all_day else "EXDATE:") + ",".join(value.strftime("%Y%m%d") if body.all_day else value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") for value in values))
    return result


def digest(body):
    value = body.model_dump(exclude={"reminder_minutes"})
    # Daily weekdays and a weekly MO..FR rule express the same event set.
    if value["recurrence"]:
        rule = body.recurrence
        value["recurrence"] = {**({"monthly": rule.monthday} if rule.rule == "monthly" else {"days": sorted(rule.days())}), "until": rule.until, "excluded": sorted(rule.excluded)}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class GoogleCalendar:
    def __init__(self, store, auth=None):
        self.store, self.auth = store, auth or GoogleAuth(store.root)
        self.lock = asyncio.Lock()
        self.previews = {}
        with store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS google_calendar_auto(binding_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,last_checked TEXT NOT NULL,error TEXT NOT NULL,pending INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS google_calendar_bindings(scope_id TEXT PRIMARY KEY,id TEXT UNIQUE NOT NULL,calendar_id TEXT UNIQUE NOT NULL,name TEXT NOT NULL,timezone TEXT NOT NULL,writable INTEGER NOT NULL,epoch TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS google_calendar_links(binding_id TEXT NOT NULL,local_id TEXT NOT NULL,google_id TEXT NOT NULL,local_hash TEXT,google_hash TEXT,PRIMARY KEY(binding_id,local_id),UNIQUE(binding_id,google_id));
            """)

    def binding(self, store):
        with store.db() as db:
            Calendar(store)._check_chat(db)
            row = db.execute("SELECT * FROM google_calendar_bindings WHERE scope_id=?", (store.scope_id,)).fetchone()
        return dict(row) if row else None

    def status(self, store):
        status, binding = self.auth.status(), self.binding(store)
        epoch = self.auth.read().get("epoch")
        status["binding"] = binding if binding and binding["epoch"] == epoch else None
        with store.db() as db:
            row = db.execute("SELECT * FROM google_calendar_auto WHERE binding_id=?", (binding["id"] if binding else "",)).fetchone()
        status["auto"] = dict(row) if row else {"enabled": False, "last_checked": "", "error": "", "pending": 0}
        return status

    def set_auto(self, store, enabled):
        binding = self.status(store)["binding"]
        if not binding:
            raise ValueError("Сначала выберите Google-календарь")
        with store.db() as db:
            db.execute("INSERT OR REPLACE INTO google_calendar_auto VALUES (?,?,?,?,?)", (binding["id"], int(enabled), "", "", 0))
        return self.status(store)

    async def auto_tick(self):
        with self.store.db() as db:
            rows = [dict(row) for row in db.execute("SELECT a.*,b.scope_id FROM google_calendar_auto a JOIN google_calendar_bindings b ON b.id=a.binding_id WHERE a.enabled=1")]
        moment = datetime.now(timezone.utc)
        for row in rows:
            if row["last_checked"] and moment - datetime.fromisoformat(row["last_checked"]) < timedelta(minutes=5):
                continue
            with self.store.db() as db:
                chat = db.execute("SELECT id FROM conversations WHERE COALESCE(project_id,'')=? LIMIT 1", (row["scope_id"],)).fetchone()
            if not chat:
                continue
            pending, error = 0, ""
            try:
                async with self.lock:
                    scoped = self.store.for_chat(chat[0])
                    if self.status(scoped)["binding"] is None:
                        raise ValueError("Повторите вход Google для фонового чтения")
                    preview = await self.preview(scoped, timestamp(moment - timedelta(days=1)), timestamp(moment + timedelta(days=31)))
                    imports = [GoogleChoice(id=item["id"], direction="google") for item in preview["rows"] if item["action"] == "import"]
                    pending = len(preview["rows"]) - min(20, len(imports))
                    if imports:
                        result = await self.apply(scoped, preview["ticket"], imports[:20])
                        error = "; ".join(item["message"] for item in result["results"] if not item["ok"])[:300]
                    else:
                        self.previews.pop(preview["ticket"], None)
            except (ValueError, TypeError, KeyError) as failure:
                error = str(failure)[:300]
            with self.store.db() as db:
                db.execute("UPDATE google_calendar_auto SET last_checked=?,error=?,pending=? WHERE binding_id=?", (moment.isoformat(), error, pending, row["binding_id"]))

    async def run_auto(self):
        while True:
            try:
                await self.auto_tick()
            except Exception:
                pass  # Individual connection errors are saved by auto_tick.
            await asyncio.sleep(60)

    async def call(self, method, path, *, expected_epoch=None, **kwargs):
        token, epoch = await self.auth.access()
        if expected_epoch is not None and epoch!=expected_epoch: raise GoogleError(401)
        headers = {**kwargs.pop("headers", {}), "Authorization": "Bearer " + token}
        result = await self.auth.request(method, BASE + path, headers=headers, **kwargs)
        if self.auth.read().get("epoch") != epoch:
            raise ValueError("Подключение Google изменилось. Обновите предпросмотр")
        return result

    async def pages(self, path, params, *, expected_epoch=None):
        result, seen, token = [], set(), None
        for _ in range(12):
            data = await self.call("GET", path, params={**params, **({"pageToken": token} if token else {})},expected_epoch=expected_epoch)
            items = data.get("items", [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("Некорректный список Google")
            result.extend(items)
            if len(result) > 2000:
                raise ValueError("Слишком много событий Google. Сократите период")
            token = data.get("nextPageToken")
            if not token:
                return result
            if not isinstance(token, str) or len(token) > 4000 or token in seen:
                break
            seen.add(token)
        raise ValueError("Список Google не получен полностью. Сократите период")

    async def calendars(self):
        items = await self.pages("/users/me/calendarList", {"maxResults": 250})
        return [{"id": text_field(item, "id", 1024), "name": text_field(item, "summary", 300), "timezone": text_field(item, "timeZone", 100, "UTC"),
                 "writable": item.get("accessRole") in {"owner", "writer"}} for item in items if item.get("accessRole") in {"owner", "writer", "reader"}]

    async def bind(self, store, calendar_id):
        calendars = await self.calendars()
        item = next((item for item in calendars if item["id"] == calendar_id), None)
        if not item:
            raise ValueError("Календарь недоступен в подключённом аккаунте")
        calendar_zone(item["timezone"])
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            Calendar(store)._check_chat(db)
            old = db.execute("SELECT scope_id FROM google_calendar_bindings WHERE calendar_id=?", (calendar_id,)).fetchone()
            if old and old[0] != store.scope_id:
                raise ValueError("Этот Google-календарь уже связан с другим пространством WileyAI")
            current = db.execute("SELECT * FROM google_calendar_bindings WHERE scope_id=?", (store.scope_id,)).fetchone()
            epoch = self.auth.read()["epoch"]
            if current and current["calendar_id"] == calendar_id:
                # An explicit reselection of the same Google calendar after
                # reauthentication preserves IDs and prevents duplicate exports.
                db.execute("UPDATE google_calendar_bindings SET name=?,timezone=?,writable=?,epoch=? WHERE id=?",
                           (item["name"],item["timezone"],int(item["writable"]),epoch,current["id"]))
            else:
                if current:
                    db.execute("DELETE FROM google_calendar_links WHERE binding_id=?", (current["id"],))
                db.execute("INSERT OR REPLACE INTO google_calendar_bindings VALUES (?,?,?,?,?,?,?)",
                           (store.scope_id, secrets.token_hex(16), calendar_id, item["name"], item["timezone"], int(item["writable"]), epoch))
        self.previews.clear()
        return self.status(store)

    @staticmethod
    def path(binding, event_id=""):
        if not isinstance(event_id, str) or len(event_id) > 1024:
            raise ValueError("Некорректный идентификатор Google")
        return "/calendars/" + quote(binding["calendar_id"], safe="") + "/events" + ("/" + quote(event_id, safe="") if event_id else "")

    async def remote(self, binding, event_id):
        try:
            event = await self.call("GET", self.path(binding, event_id),expected_epoch=binding["epoch"])
            return None if event.get("status") == "cancelled" else event
        except GoogleError as error:
            if error.status in {404, 410}:
                return None
            raise

    async def preview(self, store, start, end):
        begin, finish = instant(start), instant(end)
        if not timedelta(0) < finish - begin <= timedelta(days=93):
            raise ValueError("Для обмена Google выберите период до 93 дней")
        binding = self.binding(store)
        if not binding or binding["epoch"] != self.auth.read().get("epoch"):
            raise ValueError("Выберите Google-календарь для этого пространства")
        calendar = Calendar(store)
        local = {item["id"]: calendar.get(item["id"]) for item in calendar.list(start, end, limit=10000)["events"]}
        if any(item is None for item in local.values()):
            raise ValueError("Локальные события изменились. Повторите предпросмотр")
        with store.db() as db:
            links = [dict(row) for row in db.execute("SELECT * FROM google_calendar_links WHERE binding_id=?", (binding["id"],))]
        if len(links) > 100:
            raise ValueError("Для одного подключения поддерживается до 100 связанных событий")
        remote = await self.pages(self.path(binding), {"timeMin": timestamp(begin), "timeMax": timestamp(finish), "singleEvents": "true", "maxResults": 250, "showDeleted": "false"},expected_epoch=binding["epoch"])
        linked_remote = {link["google_id"] for link in links}
        rows, skipped = [], []
        def add(action, item, event, link=None, reason=""):
            if event:
                if not text_field(event, "id", 1024) or not text_field(event, "etag", 500):
                    raise ValueError("Google не выдал идентификатор или версию события")
            rows.append({"id": secrets.token_hex(12), "action": action, "title": item["title"] if item else event.get("summary", "Без названия"),
                         "local": item, "remote": event, "link": link, "reason": reason})
        for link in links:
            item = calendar.get(link["local_id"])
            event = await self.remote(binding, link["google_id"])
            if item:
                local.pop(item["id"], None)
            if not item or not event:
                if item and not event and link["local_hash"] is None and link["google_hash"] is None and binding["writable"]:
                    add("export", item, None, link, "Предыдущая отправка не подтверждена; повтор использует тот же ID")
                    continue
                skipped.append("Связанное событие удалено с одной стороны; вторая копия сохранена. Автоматического удаления нет")
                continue
            try:
                remote_body = event_body(event, binding["timezone"])
                local_body = EventBody.from_item(item)
                left, right = digest(local_body), digest(remote_body)
                if left == right:
                    self.link(binding, item["id"], event["id"], left, right)
                    continue
                lc, rc = left != link["local_hash"], right != link["google_hash"]
                action = "conflict" if lc and rc else "export" if lc else "import"
                if action in {"export", "conflict"} and (not binding["writable"] or event.get("attendees")):
                    skipped.append(item["title"] + ": отправка недоступна (права календаря или встреча с участниками)")
                    continue
                if action in {"export", "conflict"} and event.get("recurringEventId"):
                    skipped.append(item["title"] + ": это вхождение серии Google. Его изменения выполняются в Google Calendar")
                    continue
                add(action, item, event, link)
            except (ValueError, TypeError, KeyError) as error:
                skipped.append(item["title"] + ": " + str(error))
        for event in remote:
            if event.get("id") in linked_remote or event.get("recurringEventId") in linked_remote:
                continue
            try:
                event_body(event, binding["timezone"])
                add("import", None, event, reason="Отдельное вхождение серии" if event.get("recurringEventId") else "")
            except (ValueError, TypeError, KeyError) as error:
                skipped.append(str(error))
        for item in local.values():
            if binding["writable"]:
                # Google interprets all-day dates in the calendar's time zone.
                if item["all_day"] and item["timezone"] != binding["timezone"]:
                    skipped.append(item["title"] + ": для отправки события на весь день нужен часовой пояс Google-календаря")
                else:
                    add("export", item, None)
        if self.binding(store) != binding or self.auth.read().get("epoch") != binding["epoch"]:
            raise ValueError("Подключение изменилось. Повторите предпросмотр")
        ticket = secrets.token_hex(24)
        self.previews = {key: value for key, value in self.previews.items() if value["expires"] > time.monotonic()}
        if len(self.previews) >= 10:
            self.previews.pop(next(iter(self.previews)))
        self.previews[ticket] = {"expires": time.monotonic() + 600, "binding": binding, "scope": store.scope_id, "rows": rows}
        def version(body):
            return body.model_dump(exclude={"reminder_minutes"}) if body else None
        return {"ticket": ticket, "rows": [{key: row[key] for key in ("id", "action", "title", "reason")} |
                {"starts_at": (row["local"] or event_body(row["remote"], binding["timezone"]).model_dump())["starts_at"],
                 "local_version": version(EventBody.from_item(row["local"]) if row["local"] else None),
                 "google_version": version(event_body(row["remote"], binding["timezone"]) if row["remote"] else None)} for row in rows],
                "skipped": skipped, "period": {"start": start, "end": end}}

    def link(self, binding, local_id, google_id, local_hash=None, google_hash=None, connection=None):
        if connection is None:
            with self.store.db() as db:
                self.link(binding, local_id, google_id, local_hash, google_hash, db)
            return
        if not connection.execute("SELECT 1 FROM google_calendar_links WHERE binding_id=? AND local_id=?", (binding["id"],local_id)).fetchone():
            count = connection.execute("SELECT COUNT(*) FROM google_calendar_links WHERE binding_id=?", (binding["id"],)).fetchone()[0]
            if count >= 100:
                raise ValueError("Достигнут предел 100 связанных событий этого подключения")
        connection.execute("INSERT OR REPLACE INTO google_calendar_links VALUES (?,?,?,?,?)", (binding["id"], local_id, google_id, local_hash, google_hash))

    async def apply(self, store, ticket, choices):
        preview = self.previews.pop(ticket, None)
        if not preview or preview["expires"] < time.monotonic() or preview["scope"] != store.scope_id:
            raise ValueError("Предпросмотр устарел или относится к другому пространству")
        binding = preview["binding"]
        if self.binding(store) != binding or self.auth.read().get("epoch") != binding["epoch"]:
            raise ValueError("Подключение изменилось. Повторите предпросмотр")
        rows = {row["id"]: row for row in preview["rows"]}
        if len({choice.id for choice in choices}) != len(choices) or any(choice.id not in rows for choice in choices):
            raise ValueError("Неверный список изменений")
        results = []
        for choice in choices:
            row = rows[choice.id]
            try:
                if row["action"] != "conflict" and choice.direction != ("google" if row["action"] == "import" else "local"):
                    raise ValueError("Направление переноса не соответствует предпросмотру")
                await self.apply_one(store, binding, row, choice.direction)
                results.append({"id": row["id"], "title": row["title"], "ok": True, "message": "Импортировано" if choice.direction == "google" else "Google подтвердил сохранение"})
            except (ValueError, TypeError, KeyError) as error:
                results.append({"id": row["id"], "title": row["title"], "ok": False, "message": str(error)})
        return {"results": results}

    async def apply_one(self, store, binding, row, direction):
        calendar = Calendar(store)
        old = row["local"]
        if old and calendar.get(old["id"]) != old:
            raise ValueError("Локальное событие изменилось. Повторите предпросмотр")
        event = row["remote"]
        if event:
            current = await self.remote(binding, event["id"])
            if not current or current.get("etag") != event.get("etag"):
                raise ValueError("Событие Google изменилось. Повторите предпросмотр")
            event = current
        if self.binding(store) != binding:
            raise ValueError("Подключение изменилось")
        if old and calendar.get(old["id"]) != old:
            raise ValueError("Локальное событие изменилось во время проверки Google. Повторите предпросмотр")
        if direction == "google":
            body = event_body(event, binding["timezone"])
            if old:
                body.reminder_minutes = old["reminder_minutes"]
            # Check for an import committed by a different, earlier preview.
            with store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                Calendar(store)._check_chat(db)
                linked = db.execute("SELECT local_id FROM google_calendar_links WHERE binding_id=? AND google_id=?", (binding["id"], event["id"])).fetchone()
                if linked and (not old or linked[0] != old["id"]):
                    raise ValueError("Событие уже импортировано. Обновите предпросмотр")
                item = calendar.save(body, old["id"] if old else None, old["updated"] if old else None, connection=db)
                self.link(binding, item["id"], event["id"], digest(body), digest(body), db)
        else:
            if not binding["writable"] or event and event.get("attendees"):
                raise ValueError("Нет права изменять это событие Google")
            body = EventBody.from_item(old)
            event_id = event["id"] if event else hashlib.sha256((binding["id"] + old["id"]).encode()).hexdigest()
            # This intent remains after timeout. The next preview reconciles it.
            link = row["link"]
            self.link(binding, old["id"], event_id, link["local_hash"] if link else None, link["google_hash"] if link else None)
            payload = google_body(body)
            if event:
                etag = text_field(event, "etag", 500)
                if not etag or any(char in etag for char in "\r\n"):
                    raise ValueError("Google не выдал версию события для безопасного изменения")
                await self.call("PATCH", self.path(binding, event_id), json=payload, headers={"If-Match": etag}, params={"sendUpdates": "none"},expected_epoch=binding["epoch"])
            else:
                try:
                    await self.call("POST", self.path(binding), json={**payload, "id": event_id}, params={"sendUpdates": "none"},expected_epoch=binding["epoch"])
                except GoogleError as error:
                    if error.status != 409:
                        raise
            confirmed = await self.remote(binding, event_id)
            if not confirmed or digest(event_body(confirmed, binding["timezone"])) != digest(body):
                raise ValueError("Google не подтвердил ожидаемые поля. Обновите предпросмотр; локальная запись сохранена")
            self.link(binding, old["id"], event_id, digest(body), digest(body))
        store.audit("google_calendar", old["id"] if old else item["id"], "imported" if direction == "google" else "exported")

    async def close(self):
        self.previews.clear()
        await self.auth.close()
