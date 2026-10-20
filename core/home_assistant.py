"""Home Assistant REST adapter: selected entities and reviewed absolute actions."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from anyio import CancelScope
import httpx
import keyring
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .mail_drafts import check_scope

ENTITY = r"[a-z][a-z0-9_]*\.[a-z0-9_]{1,120}"
CONTROL = {"light", "switch", "input_boolean", "fan"}
VISIBLE = CONTROL | {"sensor", "binary_sensor", "climate", "weather", "cover", "lock", "alarm_control_panel", "media_player"}
LABELS = {"on": "Включить", "off": "Выключить", "brightness": "Установить яркость", "speed": "Установить скорость"}


def stamp(): return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def server_url(value):
    try:
        parts = urlsplit(value.strip())
        port = parts.port
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError()
        host = parts.hostname.encode("idna").decode().lower()
        if not re.fullmatch(r"[a-z0-9.:-]+", host) or any(ord(char) < 33 for char in value): raise ValueError()
        prefix = parts.path.rstrip("/")
        if prefix and (not re.fullmatch(r"(?:/[A-Za-z0-9_~.-]+)+", prefix) or any(segment in {".", ".."} for segment in prefix.split("/"))): raise ValueError()
        if prefix.endswith("/api") or "/lovelace" in prefix or "/dashboard-" in prefix: raise ValueError()
        authority = ("[" + host + "]" if ":" in host else host) + (":" + str(port) if port is not None else "")
        return urlunsplit((parts.scheme, authority, prefix, "", ""))
    except (ValueError, UnicodeError) as error:
        raise ValueError("Укажите адрес сервера Home Assistant без /api и страницы панели, например http://homeassistant.local:8123") from error


class ConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=1000)
    token: SecretStr = Field(min_length=10, max_length=8192)

    @field_validator("url")
    @classmethod
    def address(cls, value): return server_url(value)

    @field_validator("token")
    @classmethod
    def clean_token(cls, value):
        if any(ord(char) < 33 or ord(char) > 126 for char in value.get_secret_value()): raise ValueError("Некорректный токен Home Assistant")
        return value


class AccessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)
    entities: list[str] = Field(max_length=100)
    expected_revision: str = Field(max_length=100)

    @field_validator("entities")
    @classmethod
    def identifiers(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(ENTITY, value) for value in values): raise ValueError("Выберите разные устройства из списка")
        return values


class HomeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(pattern="^" + ENTITY + "$")
    action: Literal["on", "off", "brightness", "speed"]
    value: int | None = Field(default=None, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def arguments(self):
        if (self.action in {"brightness", "speed"}) != (self.value is not None): raise ValueError("Для яркости или скорости укажите процент от 0 до 100")
        return self


class HomeError(ValueError):
    def __init__(self, status):
        self.status = status
        message = "Home Assistant отклонил токен. Проверьте подключение" if status == 401 else "Home Assistant запретил это действие. Проверьте права пользователя" if status == 403 else "Устройство или действие Home Assistant больше не доступно" if status == 404 else "Home Assistant ограничил частоту запросов. Повторите позже" if status == 429 else f"Home Assistant отклонил запрос (HTTP {status})"
        super().__init__(message)


def safe_state(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("entity_id"), str) or not re.fullmatch(ENTITY, raw["entity_id"]): raise ValueError("Home Assistant вернул некорректное устройство")
    state, attrs = raw.get("state"), raw.get("attributes", {})
    if not isinstance(state, str) or len(state) > 1000 or not isinstance(attrs, dict): raise ValueError("Home Assistant вернул некорректное состояние")
    def text(key, default="", limit=160):
        value = attrs.get(key, default)
        return value[:limit] if isinstance(value, str) else default
    attributes = {}
    for key in ("brightness", "percentage", "percentage_step", "temperature", "current_temperature", "min_temp", "max_temp"):
        value = attrs.get(key)
        if type(value) in {int, float} and abs(value) < 1e12: attributes[key] = value
    modes = attrs.get("supported_color_modes")
    if isinstance(modes, list) and len(modes) < 30 and all(isinstance(value, str) and len(value) < 50 for value in modes): attributes["supported_color_modes"] = sorted(modes)
    return {"entity_id": raw["entity_id"], "name": text("friendly_name", raw["entity_id"]), "domain": raw["entity_id"].split(".")[0], "state": state, "unit": text("unit_of_measurement", limit=30), "attributes": attributes}


def revision(state):
    # Confirmation is tied to the reviewed state, not just the device name.
    return hashlib.sha256(json.dumps({key: state[key] for key in ("entity_id", "name", "state", "attributes")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def plan(state, body, services):
    domain = state["domain"]
    if domain not in CONTROL: raise ValueError("Это устройство доступно для чтения. Управление поддержано для света, выключателей и вентиляторов")
    if state["state"] in {"unknown", "unavailable"}: raise ValueError("Home Assistant сообщает, что устройство недоступно")
    data, expected = {"entity_id": body.entity_id}, {}
    service = "turn_on" if body.action == "on" else "turn_off"
    if body.action in {"on", "off"}:
        expected["state"] = "on" if body.action == "on" else "off"
    elif body.action == "brightness":
        if domain != "light": raise ValueError("Яркость доступна только для света")
        modes = state["attributes"].get("supported_color_modes", [])
        if "brightness" not in state["attributes"] and not any(mode not in {"onoff", "unknown"} for mode in modes): raise ValueError("Этот светильник не сообщает поддержку регулировки яркости")
        service = "turn_on" if body.value else "turn_off"
        expected["state"] = "on" if body.value else "off"
        if body.value:
            expected["brightness"] = round(body.value * 255 / 100)
            data["brightness"] = expected["brightness"]
    else:
        if domain != "fan" or "percentage" not in state["attributes"]: raise ValueError("Этот вентилятор не сообщает поддержку регулировки скорости")
        service = "set_percentage"
        data["percentage"] = body.value
        expected = {"state": "on" if body.value else "off", "percentage": body.value}
    if service not in services.get(domain, set()): raise ValueError("На сервере Home Assistant нет нужного действия для устройства")
    return service, data, expected


def matches(state, expected):
    return all(state["state"] == value if key == "state" else abs(state["attributes"].get(key, -1000) - value) <= (3 if key == "brightness" else 1) for key, value in expected.items())


class HomeAssistant:
    service = "WileyAI.HomeAssistant"

    def __init__(self, store, client=None):
        self.store, self.client = store, client
        self.key = hashlib.sha256(str(store.root.resolve()).casefold().encode()).hexdigest()
        self.lock = asyncio.Lock()
        self.tickets = {}
        self.chat_pending = {}
        self.poll_delays = (0, .4, .8)
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS home_bindings(scope_id TEXT PRIMARY KEY,epoch TEXT NOT NULL,revision TEXT NOT NULL,enabled INTEGER NOT NULL,entities TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS home_actions(id TEXT PRIMARY KEY,scope_id TEXT NOT NULL,epoch TEXT NOT NULL,entity_id TEXT NOT NULL,label TEXT NOT NULL,action TEXT NOT NULL,expected TEXT NOT NULL,state TEXT NOT NULL,observed TEXT NOT NULL,created TEXT NOT NULL,sent INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS home_action_history ON home_actions(scope_id,epoch,created)")

    def read(self):
        try:
            value = keyring.get_password(self.service, self.key)
            return json.loads(value) if value else {}
        except Exception as error: raise ValueError("Не удалось прочитать подключение Home Assistant из Windows") from error

    def write(self, value):
        try: keyring.set_password(self.service, self.key, json.dumps(value))
        except Exception as error: raise ValueError("Не удалось сохранить подключение Home Assistant в Windows") from error

    def binding(self, store):
        value = self.read()
        with store.db() as db:
            check_scope(db, store)
            row = db.execute("SELECT * FROM home_bindings WHERE scope_id=? AND epoch=?", (store.scope_id, value.get("epoch", ""))).fetchone()
        return {"revision": row["revision"], "enabled": bool(row["enabled"]), "entities": json.loads(row["entities"])} if row else {"revision": "", "enabled": False, "entities": []}

    def status(self, store):
        value = self.read()
        return {"configured": bool(value.get("token")), "url": value.get("url", ""), "name": value.get("name", ""), "version": value.get("version", ""), "checked_at": value.get("checked_at", ""), "epoch": value.get("epoch", ""), "binding": self.binding(store)}

    def credentials(self):
        value = self.read()
        if not value.get("token"): raise ValueError("Подключите Home Assistant в разделе «Интеграции»: адрес сервера и долгосрочный токен")
        return value

    async def call(self, value, method, path, **kwargs):
        if value.get("epoch") and self.read().get("epoch") != value["epoch"]: raise ValueError("Подключение Home Assistant изменилось. Обновите устройства")
        allowed = method == "GET" and (path in {"", "config", "states", "services"} or re.fullmatch("states/" + ENTITY, path))
        allowed = allowed or method == "POST" and re.fullmatch(r"services/(?:light|switch|input_boolean|fan)/(?:turn_on|turn_off|set_percentage)", path)
        if not allowed: raise ValueError("Это действие Home Assistant не поддерживается")
        if self.client is None: self.client = httpx.AsyncClient(timeout=7, trust_env=False, follow_redirects=False)
        try:
            async with asyncio.timeout(8):
                async with self.client.stream(method, value["url"] + "/api/" + path, headers={"Authorization": "Bearer " + value["token"]}, follow_redirects=False, timeout=7, **kwargs) as response:
                    if response.status_code != 200: raise HomeError(response.status_code)
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=32768):
                        data.extend(chunk)
                        if len(data) > 8 * 1024 * 1024: raise ValueError("Ответ Home Assistant превышает 8 МБ")
                    result = json.loads(data)
        except HomeError: raise
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, json.JSONDecodeError, UnicodeError) as error:
            raise ValueError("Нет надёжного ответа Home Assistant. Проверьте адрес сервера и соединение; результат действия мог сохраниться") from error
        if value.get("epoch") and self.read().get("epoch") != value["epoch"]: raise ValueError("Подключение Home Assistant изменилось. Обновите устройства")
        return result

    async def check_connection(self, value=None):
        value = value or self.credentials()
        result = await self.call(value, "GET", "")
        if not isinstance(result, dict) or result.get("message") != "API running.": raise ValueError("Сервер не подтвердил Home Assistant API")
        config = await self.call(value, "GET", "config")
        if not isinstance(config, dict) or not isinstance(config.get("version"), str): raise ValueError("Сервер не подтвердил конфигурацию Home Assistant")
        return {"name": str(config.get("location_name", "Home Assistant"))[:160], "version": config["version"][:80], "checked_at": stamp()}

    async def configure(self, store, body):
        value = {"url": body.url, "token": body.token.get_secret_value()}
        info = await self.check_connection(value)
        self.write({**value, **info, "epoch": secrets.token_hex(16)})
        self.tickets.clear()
        self.chat_pending.clear()
        return self.status(store)

    def disconnect(self, store):
        self.write({})
        self.tickets.clear()
        self.chat_pending.clear()
        return self.status(store)

    async def services(self, value):
        rows = await self.call(value, "GET", "services")
        if not isinstance(rows, list) or len(rows) > 2000: raise ValueError("Некорректный список действий Home Assistant")
        return {row["domain"]: set(row["services"]) for row in rows if isinstance(row, dict) and isinstance(row.get("domain"), str) and isinstance(row.get("services"), dict)}

    async def entity(self, value, entity_id):
        result = safe_state(await self.call(value, "GET", "states/" + entity_id))
        if result["entity_id"] != entity_id: raise ValueError("Home Assistant вернул другое устройство")
        return result

    async def entities(self, store):
        value = self.credentials()
        rows = await self.call(value, "GET", "states")
        if not isinstance(rows, list) or len(rows) > 5000: raise ValueError("Слишком большой или некорректный список устройств Home Assistant")
        services = await self.services(value)
        binding = self.binding(store)
        result = []
        for raw in rows:
            state = safe_state(raw)
            if state["domain"] not in VISIBLE: continue
            actions = []
            for action in ("on", "off", "brightness", "speed"):
                try: plan(state, HomeAction(entity_id=state["entity_id"], action=action, value=50 if action in {"brightness", "speed"} else None), services)
                except ValueError: continue
                actions.append(action)
            result.append({**state, "actions": actions, "selected": state["entity_id"] in binding["entities"]})
        if len(result) > 2000: raise ValueError("Поддерживается до 2000 видимых устройств Home Assistant")
        return {"entities": result, "checked_at": stamp(), "epoch": value["epoch"]}

    async def access(self, store, body):
        value = self.credentials()
        current = self.binding(store)
        if current["revision"] != body.expected_revision: raise ValueError("Доступ изменился в другом окне. Обновите устройства")
        visible = {row["entity_id"] for row in (await self.entities(store))["entities"]}
        if any(entity_id not in visible for entity_id in body.entities): raise ValueError("Одно из выбранных устройств больше не доступно")
        new_revision = secrets.token_hex(16)
        if self.read().get("epoch") != value["epoch"]: raise ValueError("Подключение Home Assistant изменилось. Обновите устройства")
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db, store)
            old = db.execute("SELECT revision FROM home_bindings WHERE scope_id=? AND epoch=?", (store.scope_id, value["epoch"])).fetchone()
            if (old[0] if old else "") != body.expected_revision: raise ValueError("Доступ изменился в другом окне. Обновите устройства")
            db.execute("INSERT OR REPLACE INTO home_bindings VALUES (?,?,?,?,?)", (store.scope_id, value["epoch"], new_revision, int(body.enabled), json.dumps(body.entities)))
        return self.status(store)

    def guard(self, store, value, body, expected_binding=None):
        if self.read().get("epoch") != value["epoch"]: raise ValueError("Подключение Home Assistant изменилось")
        binding = self.binding(store)
        if expected_binding is not None and binding != expected_binding: raise ValueError("Доступ изменился после просмотра. Подготовьте действие заново")
        if not binding["enabled"] or body.entity_id not in binding["entities"]: raise ValueError("Разрешите управление этим устройством в разделе «Интеграции» для текущего пространства")
        return binding

    async def preview(self, store, body):
        value = self.credentials()
        binding = self.guard(store, value, body)
        state = await self.entity(value, body.entity_id)
        service, data, expected = plan(state, body, await self.services(value))
        self.guard(store, value, body, binding)
        self.tickets = {key: row for key, row in self.tickets.items() if row["expires"] > time.monotonic()}
        while len(self.tickets) >= 100: self.tickets.pop(next(iter(self.tickets)))
        ticket = secrets.token_hex(24)
        self.tickets[ticket] = {"scope": store.scope_id, "chat": store.conversation_id, "epoch": value["epoch"], "binding": binding, "expires": time.monotonic() + 300, "action": body.model_dump(), "baseline": revision(state), "service": service, "data": data, "expected": expected, "label": state["name"]}
        return {"ticket": ticket, "device": state, "action": body.action, "label": LABELS[body.action], "value": body.value, "expected": expected, "already": matches(state, expected)}

    def receipt(self, store, item_id):
        value = self.credentials()
        with store.db() as db:
            check_scope(db, store)
            row = db.execute("SELECT * FROM home_actions WHERE id=? AND scope_id=? AND epoch=?", (item_id, store.scope_id, value["epoch"])).fetchone()
        if not row: raise ValueError("Действие Home Assistant не найдено в этом пространстве")
        result = dict(row)
        for key in ("action", "expected", "observed"): result[key] = json.loads(result[key])
        result["text"] = ("Home Assistant подтвердил состояние: " if result["state"] == "verified" else "Home Assistant отклонил действие: " if result["state"] == "failed" else "Состояние после команды пока не подтверждено: ") + result["label"] + "."
        if result["observed"]:
            from .home_assistant_chat import state_text
            result["text"] += " " + state_text(result["observed"]) + "."
        return result

    def history(self, store):
        value = self.read()
        with store.db() as db:
            check_scope(db, store)
            ids = [row[0] for row in db.execute("SELECT id FROM home_actions WHERE scope_id=? AND epoch=? ORDER BY created DESC LIMIT 20", (store.scope_id, value.get("epoch", "")))]
        return [self.receipt(store, item_id) for item_id in ids]

    def mark(self, store, item_id, state, observed=None):
        with store.db() as db: db.execute("UPDATE home_actions SET state=?,observed=? WHERE id=? AND scope_id=?", (state, json.dumps(observed or {}, ensure_ascii=False), item_id, store.scope_id))

    async def confirm(self, store, ticket, confirmed):
        if not confirmed: raise ValueError("Подтвердите показанные устройство и действие")
        item = self.tickets.get(ticket)
        value = self.credentials()
        if not item or item["scope"] != store.scope_id or item["chat"] != store.conversation_id or item["epoch"] != value["epoch"] or item["expires"] < time.monotonic(): raise ValueError("Предпросмотр Home Assistant устарел или относится к другому чату")
        body = HomeAction.model_validate(item["action"])
        self.guard(store, value, body, item["binding"])
        current = await self.entity(value, body.entity_id)
        if revision(current) != item["baseline"]: raise ValueError("Состояние устройства изменилось после просмотра. Проверьте действие заново")
        self.guard(store, value, body, item["binding"])
        sent = not matches(current, item["expected"])
        with store.db() as db:
            check_scope(db, store)
            if db.execute("SELECT 1 FROM home_actions WHERE id=?", (ticket,)).fetchone(): raise ValueError("Это действие уже отправлялось. Проверьте результат в журнале")
            db.execute("INSERT INTO home_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)", (ticket, store.scope_id, value["epoch"], body.entity_id, item["label"], json.dumps(item["action"]), json.dumps(item["expected"]), "unknown", "{}", stamp(), int(sent)))
        self.tickets.pop(ticket, None)
        if not sent:
            self.mark(store, ticket, "verified", current)
        else:
            accepted = False
            try:
                await self.call(value, "POST", "services/" + current["domain"] + "/" + item["service"], json=item["data"])
                accepted = True
                for delay in self.poll_delays:
                    if delay: await asyncio.sleep(delay)
                    observed = await self.entity(value, body.entity_id)
                    self.mark(store, ticket, "verified" if matches(observed, item["expected"]) else "unknown", observed)
                    if matches(observed, item["expected"]): break
            except HomeError as error:
                if not accepted and error.status in {400, 401, 403, 404, 405, 422, 429}: self.mark(store, ticket, "failed")
            except ValueError: pass  # The persisted unknown outcome is never retried automatically.
        result = self.receipt(store, ticket)
        self.store.audit("home_assistant", body.entity_id, result["state"])
        return result

    async def dispatch(self, store, ticket, confirmed, progress=None):
        operation = asyncio.create_task(self.confirm(store, ticket, confirmed))
        try: result = await asyncio.shield(operation)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                try:
                    result = await operation
                    if progress is not None: progress.append(result["text"])
                except ValueError: pass
            raise
        if progress is not None: progress.append(result["text"])
        return result

    async def check(self, store, item_id):
        receipt = self.receipt(store, item_id)
        if receipt["state"] != "unknown": return receipt
        observed = await self.entity(self.credentials(), receipt["entity_id"])
        self.mark(store, item_id, "verified" if matches(observed, receipt["expected"]) else "unknown", observed)
        return self.receipt(store, item_id)

    async def close(self):
        self.tickets.clear()
        self.chat_pending.clear()
        if self.client is not None: await self.client.aclose()
