"""Portable data snapshots. Imports are data, never SQLite files or executable code."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import threading
import time
from typing import Annotated, Literal
import uuid

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .config import Settings
from .memory import fingerprint, normalized
from .storage import Store, now
from .websearch import public_url
from .routines import Step, RoutineBody
from .commands import normalize
from .tools import ACCESS_FIELDS
from .calendar import EventBody
from .calendar_repeats import occurrences
from .mail_drafts import DraftBody, DraftSource
from .contacts import ContactBody
from .notifications import reminder_time
from . import repeats
from .document_library import rebuild_index as rebuild_document_index
from .document_context import DocumentFragment
from .history import rebuild_index as rebuild_history_index

MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 200_000
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ScopeId = Id | Literal[""]
Bit = Annotated[int, Field(ge=0, le=1)]


def utc(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Нужен часовой пояс")
    return parsed.astimezone(timezone.utc).isoformat()


Timestamp = Annotated[str, AfterValidator(utc)]
CalendarTimestamp = Annotated[Timestamp, AfterValidator(lambda value: datetime.fromisoformat(value).isoformat(timespec="microseconds"))]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Dated(Record):
    id: Id
    created: Timestamp


class Message(Dated):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1_000_000)
    conversation_id: Id = "legacy"
    document_context: list[DocumentFragment] = Field(default_factory=list, max_length=20)


class Memory(Dated):
    content: str = Field(min_length=1, max_length=6000)  # Preserve older manual records too.
    category: Literal["fact", "preference", "profile"]
    pinned: Bit
    source_message_id: Id | None
    updated: Timestamp
    revision: int = Field(ge=1)
    scope_id: ScopeId = ""


class Candidate(Dated):
    content: str = Field(max_length=1200)
    category: Literal["fact", "preference", "profile"]
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    source_message_id: Id
    status: Literal["pending", "accepted", "dismissed"]
    memory_id: Id | None
    scope_id: ScopeId = ""


class Reference(Record):
    message_id: Id
    memory_id: Id
    revision: int = Field(ge=1)


class Alias(Record):
    id: Id
    name: str = Field(min_length=1, max_length=150)
    kind: Literal["folder", "file", "app", "url"]
    target: str = Field(min_length=1, max_length=4096)


class Document(Dated):
    name: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=1_000_000)
    conversation_id: Id = "legacy"


class ProjectDocument(Dated):
    name: str = Field(min_length=1, max_length=4096)
    content: str = Field(min_length=1, max_length=1_000_000)
    project_id: Id


class Note(Dated):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=20000)
    scope_id: ScopeId = ""


class Task(Dated):
    title: str = Field(min_length=1, max_length=500)
    kind: Literal["todo", "reminder", "timer", "alarm"]
    due: Timestamp | None
    done: Bit
    notified: Bit
    scope_id: ScopeId = ""
    recurrence: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def valid_recurrence(self):
        repeats.validate(self.recurrence, self.kind, self.due)
        return self


class CalendarEvent(Dated):
    title: str = Field(min_length=1, max_length=200)
    starts_at: CalendarTimestamp
    ends_at: CalendarTimestamp
    timezone: str = Field(min_length=1, max_length=100)
    location: str = Field(max_length=500)
    description: str = Field(max_length=10000)
    scope_id: ScopeId = ""
    updated: Timestamp
    reminder_minutes: Annotated[int, Field(strict=True, ge=0, le=10080)] | None = None
    reminder_at: CalendarTimestamp | None = None
    reminder_sent: Bit = 0
    all_day: Bit = 0
    recurrence: str | None = Field(default=None, max_length=32000)
    reminder_cursor: CalendarTimestamp | None = None
    parent_id: Id | None = None
    original_start: CalendarTimestamp | None = None


class CalendarAlert(Dated):
    event_id: Id
    scheduled_for: CalendarTimestamp
    delivered: Bit
    deferred: Bit = 0
    occurrence_start: CalendarTimestamp | None = None
    occurrence_end: CalendarTimestamp | None = None


class MailDraft(Dated, DraftBody, DraftSource):
    scope_id: ScopeId = ""
    updated: Timestamp


class Contact(Dated,ContactBody):
    scope_id: ScopeId=""
    updated: Timestamp


class Project(Dated):
    name: str = Field(min_length=1, max_length=100)
    updated: Timestamp


class Conversation(Dated):
    title: str = Field(min_length=1, max_length=100)
    project_id: Id | None
    updated: Timestamp


class Routine(Dated):
    name: str = Field(min_length=1, max_length=80)
    name_key: str = Field(min_length=1, max_length=240)
    steps: list[Step] = Field(min_length=1, max_length=12)
    scope_id: ScopeId = ""
    updated: Timestamp


class Notification(Dated):
    task_id: Id
    title: str = Field(max_length=500)
    delivered: Bit
    scheduled_for: Timestamp | None = None


def valid_source_url(value: str) -> str:
    result = public_url(value)
    if not result:
        raise ValueError("Недопустимый URL источника")
    return result


class WebResult(Record):
    title: str = Field(min_length=1, max_length=180)
    url: Annotated[str, AfterValidator(valid_source_url)]
    snippet: str = Field(max_length=120000)


class WebSearch(Record):
    message_id: Id
    query: str = Field(min_length=2, max_length=500)
    provider: Literal["brave", "searxng", "page", "open-meteo", "cbr"]
    checked_at: Timestamp
    results: list[WebResult] = Field(max_length=5)
    partial: Bit


TABLES = {
    "projects": Project, "conversations": Conversation,
    "messages": Message, "memories": Memory, "memory_candidates": Candidate,
    "message_memories": Reference, "aliases": Alias, "documents": Document,
    "notes": Note, "tasks": Task, "notifications": Notification,
    "web_searches": WebSearch,
    "routines": Routine,
    "calendar_events": CalendarEvent,
    "calendar_alerts": CalendarAlert,
    "mail_drafts": MailDraft,
    "contacts": Contact,
    "project_documents": ProjectDocument,
}


class Data(Record):
    projects: list[Project] = Field(default_factory=list)
    conversations: list[Conversation] = Field(default_factory=list)
    messages: list[Message]
    memories: list[Memory]
    memory_candidates: list[Candidate]
    message_memories: list[Reference]
    aliases: list[Alias]
    documents: list[Document]
    notes: list[Note]
    tasks: list[Task]
    notifications: list[Notification]
    web_searches: list[WebSearch] = Field(default_factory=list)
    routines: list[Routine] = Field(default_factory=list)
    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    calendar_alerts: list[CalendarAlert] = Field(default_factory=list)
    mail_drafts: list[MailDraft] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    project_documents: list[ProjectDocument] = Field(default_factory=list)


class Bundle(Record):
    format: Literal["wileyai.backup"]
    version: Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    created: Timestamp
    settings: dict
    data: Data


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повторяющееся поле")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("Неверное число")


def parse(data: bytes) -> Bundle:
    if len(data) > MAX_BYTES:
        raise ValueError("Копия превышает 64 МБ")
    try:
        raw = json.loads(data, object_pairs_hook=unique_keys, parse_constant=reject_constant)
        if not isinstance(raw, dict) or type(raw.get("version")) is not int:
            raise ValueError("Неверная версия")
        bundle = Bundle.model_validate(raw)
        if bundle.version < 11 and any(row.parent_id or (row.recurrence and (json.loads(row.recurrence).get("excluded") or json.loads(row.recurrence).get("rule") == "monthly")) for row in bundle.data.calendar_events):
            raise ValueError("Месячные повторы и исключения требуют формат 11")
        if bundle.version < 11 and any(row.attachments for row in bundle.data.mail_drafts):
            raise ValueError("Вложения требуют формат 11")
        if bundle.version < 11 and bundle.data.contacts:
            raise ValueError("Контакты требуют формат 11")
        event_map = {row.id: row for row in bundle.data.calendar_events}
        for row in bundle.data.calendar_events:
            parent = event_map.get(row.parent_id) if row.parent_id else None
            if bool(row.parent_id) != bool(row.original_start) or (row.parent_id and (not parent or parent.scope_id != row.scope_id or parent.parent_id or not parent.recurrence)):
                raise ValueError("Некорректная связь перенесённого вхождения календаря")
        if bundle.version < 10 and bundle.data.mail_drafts:
            raise ValueError("Почтовые черновики требуют формат 10")
        if bundle.version < 9 and (any(row.all_day or row.recurrence or row.reminder_cursor for row in bundle.data.calendar_events)
                                  or any(row.occurrence_start or row.occurrence_end for row in bundle.data.calendar_alerts)):
            raise ValueError("События на весь день и повторы календаря требуют формат 9")
        if bundle.version < 8 and (any(row.recurrence for row in bundle.data.tasks) or any(row.scheduled_for for row in bundle.data.notifications)):
            raise ValueError("Повторы и сроки уведомлений требуют формат 8")
        if bundle.version < 7 and any(row.document_context for row in bundle.data.messages):
            raise ValueError("Контекст документов требует формат 7")
        if any(row.document_context and row.role != "assistant" for row in bundle.data.messages):
            raise ValueError("Фрагменты документов без ответа ассистента")
        if bundle.version < 6 and bundle.data.project_documents:
            raise ValueError("Документы проекта требуют формат 6")
        if bundle.version < 5 and (bundle.data.calendar_alerts or any(row.reminder_minutes is not None or row.reminder_at is not None or row.reminder_sent for row in bundle.data.calendar_events)):
            raise ValueError("Уведомления календаря требуют формат 5")
        if bundle.version < 4 and bundle.data.calendar_events:
            raise ValueError("Календарь требует формат 4")
        if bundle.version < 3 and bundle.data.routines:
            raise ValueError("Сценарии требуют формат 3")
        if bundle.version == 1:
            if bundle.data.projects or bundle.data.conversations:
                raise ValueError("Проекты требуют формат 2")
            bundle.data.conversations = [Conversation(id="legacy", title="Переписка до обновления", project_id=None, created=bundle.created, updated=bundle.created)]
        if set(bundle.settings) - Settings.model_fields.keys():
            raise ValueError("Неизвестные настройки")
        bundle.settings = Settings.model_validate(bundle.settings, strict=True).model_dump()
        tables = bundle.data.model_dump()
        if sum(map(len, tables.values())) > MAX_RECORDS:
            raise ValueError("Слишком много записей")
        for name, rows in tables.items():
            keys = [(row["message_id"], row["memory_id"]) if name == "message_memories" else row["message_id"] if name == "web_searches" else row["id"] for row in rows]
            if len(keys) != len(set(keys)):
                raise ValueError("Повторяющиеся записи")
        messages = {row["id"]: row for row in tables["messages"]}
        memories = {row["id"]: row for row in tables["memories"]}
        tasks = {row["id"]: row for row in tables["tasks"]}
        projects = {row["id"] for row in tables["projects"]}
        chats = {row["id"]: row for row in tables["conversations"]}
        if any(row["project_id"] not in projects for row in tables["project_documents"]):
            raise ValueError("Документ без проекта")
        if any(not row["content"].strip() for row in tables["project_documents"]):
            raise ValueError("Пустой текст документа проекта")
        if {row["id"] for row in tables["documents"]} & {row["id"] for row in tables["project_documents"]}:
            raise ValueError("Повторяющийся ID документа")
        if not chats or any(row["project_id"] is not None and row["project_id"] not in projects for row in chats.values()):
            raise ValueError("Неверный проект чата")
        for table in ("messages", "documents"):
            if any(row["conversation_id"] not in chats for row in tables[table]):
                raise ValueError("Запись без чата")
        for table in ("memories", "memory_candidates", "tasks", "notes", "routines", "calendar_events", "mail_drafts", "contacts"):
            if any(row["scope_id"] and row["scope_id"] not in projects for row in tables[table]):
                raise ValueError("Запись без проекта")
        if any(count > 200 for count in Counter(row["scope_id"] for row in tables["mail_drafts"]).values()):
            raise ValueError("Слишком много почтовых черновиков в пространстве")
        if any(count > 500 for count in Counter(row["scope_id"] for row in tables["contacts"]).values()):
            raise ValueError("Слишком много контактов")
        for row in tables["calendar_events"]:
            body = EventBody.from_item(row)
            # Keep lexically sortable canonical UTC times after importing any offset.
            row.update(body.model_dump())
            row.update(all_day=int(body.all_day), recurrence=body.recurrence.model_dump_json() if body.recurrence else None)
            actual = reminder_time(row["starts_at"], row["reminder_minutes"])
            if actual != (reminder_time(row["reminder_at"], 0) if row["reminder_at"] else None) or (actual is None and row["reminder_sent"]):
                raise ValueError("Неверное время напоминания события")
            row["reminder_at"] = actual
            if row["reminder_cursor"]:
                cursor = datetime.fromisoformat(row["reminder_cursor"])
                if not body.recurrence or body.reminder_minutes is None:
                    raise ValueError("Курсор напоминания без повтора")
                begin = cursor + timedelta(minutes=body.reminder_minutes)
                if not any(start == begin for start, _ in occurrences(row, begin, begin + timedelta(seconds=1))):
                    raise ValueError("Курсор вне серии событий")
        bundle.data.calendar_events = [CalendarEvent.model_validate(row) for row in tables["calendar_events"]]
        events = {row["id"]: row for row in tables["calendar_events"]}
        pending_alerts = set()
        if {row["id"] for row in tables["notifications"]} & {row["id"] for row in tables["calendar_alerts"]}:
            raise ValueError("Повторяющийся ID уведомления")
        for alert in tables["calendar_alerts"]:
            parent = events.get(alert["event_id"])
            if parent is None:
                raise ValueError("Уведомление без события")
            if bool(alert["occurrence_start"]) != bool(alert["occurrence_end"]):
                raise ValueError("Неполный интервал уведомления")
            if alert["occurrence_start"]:
                begin, end = datetime.fromisoformat(alert["occurrence_start"]), datetime.fromisoformat(alert["occurrence_end"])
                if end <= begin or (not alert["delivered"] and (not parent["recurrence"] or not any(start == begin and stop == end for start, stop in occurrences(parent, begin, begin + timedelta(seconds=1))))):
                    raise ValueError("Уведомление вне серии событий")
            if not alert["delivered"]:
                valid = (parent["reminder_cursor"] == reminder_time(alert["scheduled_for"], 0)
                         and alert["occurrence_start"] and reminder_time(alert["occurrence_start"], parent["reminder_minutes"]) == parent["reminder_cursor"]) if parent["recurrence"] else (
                             parent["reminder_sent"] and reminder_time(alert["scheduled_for"], 0) == parent["reminder_at"])
                if alert["event_id"] in pending_alerts or not valid:
                    raise ValueError("Неверное ожидающее уведомление")
                pending_alerts.add(alert["event_id"])
        routine_keys = set()
        for row in tables["routines"]:
            body = RoutineBody.model_validate({"name": row["name"], "steps": row["steps"]})
            key = (row["scope_id"], row["name_key"])
            if body.name != row["name"] or normalize(row["name"]) != row["name_key"] or key in routine_keys:
                raise ValueError("Неверное или повторяющееся название сценария")
            routine_keys.add(key)
        def message_scope(message_id):
            source = messages.get(message_id)
            return (chats[source["conversation_id"]]["project_id"] or "") if source else None
        for search in tables["web_searches"]:
            if messages.get(search["message_id"], {}).get("role") != "assistant":
                raise ValueError("Поиск без ответа ассистента")
        for memory in memories.values():
            if memory["source_message_id"] is not None and (messages.get(memory["source_message_id"], {}).get("role") != "user" or message_scope(memory["source_message_id"]) != memory["scope_id"]):
                raise ValueError("Неверный источник памяти")
        for ref in tables["message_memories"]:
            if messages.get(ref["message_id"], {}).get("role") != "assistant" or ref["memory_id"] not in memories or ref["revision"] > memories[ref["memory_id"]]["revision"]:
                raise ValueError("Неверная ссылка памяти")
            if message_scope(ref["message_id"]) != memories[ref["memory_id"]]["scope_id"]:
                raise ValueError("Ссылка на память другого проекта")
        candidates = tables["memory_candidates"]
        if len({(row["scope_id"], row["fingerprint"]) for row in candidates}) != len(candidates):
            raise ValueError("Повторяющиеся предложения")
        if any(count > 50 for count in Counter(row["scope_id"] for row in candidates if row["status"] == "pending").values()):
            raise ValueError("Слишком много предложений")
        for row in candidates:
            if messages.get(row["source_message_id"], {}).get("role") != "user" or message_scope(row["source_message_id"]) != row["scope_id"]:
                raise ValueError("Неверный источник предложения")
            if row["memory_id"] in memories and memories[row["memory_id"]]["scope_id"] != row["scope_id"]:
                raise ValueError("Предложение ссылается на чужой проект")
            if row["status"] == "pending":
                if not row["content"].strip() or fingerprint(row["content"]) != row["fingerprint"] or row["memory_id"] is not None:
                    raise ValueError("Неверное предложение")
            elif row["content"] or (row["status"] == "accepted" and row["memory_id"] is None):
                raise ValueError("Неверный статус предложения")
        names = [row["name"].casefold().strip() for row in tables["aliases"]]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Повторяющиеся команды")
        pending_tasks = set()
        for row in tables["notifications"]:
            if not row["delivered"] and row["task_id"] not in tasks:
                raise ValueError("Напоминание без задачи")
            if not row["delivered"]:
                if bundle.version >= 8 and (row["task_id"] in pending_tasks or row["scheduled_for"] is None):
                    raise ValueError("Повторяющееся ожидающее уведомление")
                pending_tasks.add(row["task_id"])
        # Before format 8, a pending one-shot alert used its task's due time.
        if bundle.version < 8:
            legacy_pending = {}
            for row in bundle.data.notifications:
                if not row.delivered:
                    parent = tasks[row.task_id]
                    if parent["due"] and parent["notified"] and not parent["done"]:
                        row.scheduled_for = parent["due"]
                        legacy_pending[row.task_id] = row
            # Old edits could leave multiple stale pending rows. Preserve history
            # and coalesce the currently deliverable one instead of duplicating it.
            bundle.data.notifications = [row for row in bundle.data.notifications if row.delivered] + list(legacy_pending.values())
        return bundle
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("Не удалось проверить копию: файл повреждён, имеет другую версию или содержит некорректные записи") from error


def snapshot(db) -> dict:
    row = db.execute("SELECT value FROM config WHERE id=1").fetchone()
    settings = Settings.model_validate_json(row[0]) if row else Settings()
    tables = {}
    for name, schema in TABLES.items():
        columns = ",".join(schema.model_fields)
        tables[name] = [dict(row) for row in db.execute(f"SELECT {columns} FROM {name} ORDER BY rowid")]
        if name == "web_searches":
            for item in tables[name]:
                item["results"] = json.loads(item["results"])
        if name == "messages":
            for item in tables[name]:
                item["document_context"] = json.loads(item["document_context"])
        if name == "routines":
            for item in tables[name]:
                item["steps"] = json.loads(item["steps"])
        if name == "mail_drafts":
            for item in tables[name]:
                for key in ("to_addresses", "cc_addresses", "bcc_addresses", "attachments"):
                    item[key] = json.loads(item[key])
    return {"format": "wileyai.backup", "version": 11, "created": now(), "settings": settings.model_dump(), "data": tables}


def state_digest(db, value: dict) -> str:
    dialogue = [dict(row) for row in db.execute("SELECT * FROM dialogue_state")]
    chats = [dict(row) for row in db.execute("SELECT * FROM chat_dialogue ORDER BY conversation_id")]
    return hashlib.sha256(encode({"settings": value["settings"], "data": value["data"], "dialogue": dialogue, "chat_dialogue": chats})).hexdigest()


class Backups:
    def __init__(self, store: Store):
        self.store = store
        self.pending = None
        self.lock = threading.Lock()

    def export(self) -> bytes:
        with self.store.db() as db:
            db.execute("BEGIN")
            result = encode(snapshot(db))
        if len(result) > MAX_BYTES:
            raise ValueError("Данные превышают лимит копии 64 МБ; копия не создана")
        # Never offer a backup the current version cannot restore.
        parse(result)
        return result

    def preview(self, content: bytes) -> dict:
        bundle = parse(content)
        with self.store.db() as db:
            db.execute("BEGIN")
            current = snapshot(db)
            digest = state_digest(db, current)
        ticket = uuid.uuid4().hex
        with self.lock:
            self.pending = (ticket, time.monotonic() + 600, digest, bundle)
        return {"ticket": ticket, "created": bundle.created,
                "counts": {name: len(rows) for name, rows in bundle.data.model_dump().items()},
                "current_counts": {name: len(rows) for name, rows in current["data"].items()},
                "pending_suggestions": sum(row.status == "pending" for row in bundle.data.memory_candidates),
                "current_pending_suggestions": sum(row["status"] == "pending" for row in current["data"]["memory_candidates"]),
                "name": bundle.settings["name"], "provider": bundle.settings["provider"],
                "model": bundle.settings["model"], "base_url": bundle.settings["base_url"]}

    def restore(self, ticket: str, connections: bool = False, aliases: bool = False) -> dict:
        with self.lock:
            pending = self.pending
            if not pending or pending[0] != ticket or pending[1] < time.monotonic():
                raise ValueError("Предпросмотр устарел. Выберите и проверьте копию заново")
            self.pending = None  # A preview authorizes at most one attempt.
        _, _, expected, bundle = pending
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = snapshot(db)
            if state_digest(db, previous) != expected:
                raise ValueError("После просмотра данные изменились. Выберите копию заново, чтобы проверить заменяемые записи")
            recovery = encode(previous)
            if len(recovery) > MAX_BYTES:
                raise ValueError("Защитная копия превышает 64 МБ. Восстановление не выполнялось")
            parse(recovery)
            folder = self.store.root / "backups"
            path = folder / ("before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".wileyai.json")
            created = False
            try:
                folder.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as file:
                    created = True
                    file.write(recovery)
                    file.flush()
                    os.fsync(file.fileno())
            except OSError as error:
                if created:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise ValueError("Не удалось сохранить защитную копию. Текущие данные не изменены") from error
            tables = bundle.data.model_dump()
            for name in TABLES:
                if name == "aliases" and not aliases:
                    continue
                db.execute(f"DELETE FROM {name}")
                rows = tables[name]
                columns = list(TABLES[name].model_fields)
                if name == "memories":
                    columns.append("fingerprint")
                    rows = [{**row, "fingerprint": fingerprint(row["content"])} for row in rows]
                if name == "web_searches":
                    rows = [{**row, "results": json.dumps(row["results"], ensure_ascii=False)} for row in rows]
                if name == "messages":
                    rows = [{**row, "document_context": json.dumps([DocumentFragment.model_validate(fragment).model_dump(exclude_defaults=True)
                             for fragment in row["document_context"]], ensure_ascii=False)} for row in rows]
                if name == "routines":
                    rows = [{**row, "steps": json.dumps(row["steps"], ensure_ascii=False)} for row in rows]
                if name == "mail_drafts":
                    rows = [{**row, **{key: json.dumps(row[key], ensure_ascii=False) for key in ("to_addresses", "cc_addresses", "bcc_addresses", "attachments")}} for row in rows]
                if rows:
                    db.executemany(f"INSERT INTO {name} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [tuple(row[column] for column in columns) for row in rows])
            db.execute("DELETE FROM memories_fts")
            rebuild_document_index(db)
            rebuild_history_index(db)
            db.executemany("INSERT INTO memories_fts VALUES (?,?)", [(row["id"], normalized(row["content"])) for row in tables["memories"]])
            db.execute("DELETE FROM dialogue_state")
            db.execute("DELETE FROM chat_dialogue")
            # Restoring local data must never retain authority to overwrite a remote calendar.
            for table in ("google_calendar_links", "google_calendar_bindings", "google_calendar_auto", "mail_bindings", "mail_remote_drafts", "home_bindings"):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    db.execute(f"DELETE FROM {table}")
            settings = {**bundle.settings, "search_enabled": False, "web_read_enabled": False, "weather_enabled": False, "currency_enabled": False} if connections else {**previous["settings"], **{key: bundle.settings[key] for key in ("name", "personality", "grammatical_gender", "memory_suggestions")}}
            settings.update({field: previous["settings"][field] for field in (*ACCESS_FIELDS, "command_understanding", "task_understanding", "plan_understanding", "embedding_enabled", "embedding_model", "embedding_base_url")})
            # Imported settings cannot select another profile's registration.
            # OAuth tokens themselves never enter the archive.
            settings["chatgpt_connection"] = previous["settings"].get("chatgpt_connection", "")
            db.execute("INSERT OR REPLACE INTO config VALUES (1,?)", (Settings.model_validate(settings).model_dump_json(),))
            db.execute("INSERT INTO actions (id,kind,target,status,created) VALUES (?,?,?,?,?)", (uuid.uuid4().hex, "backup", "restore", "restored", now()))
        return {"recovery_path": str(path.resolve()), "counts": {name: len(rows) for name, rows in tables.items()}, "connections": connections, "aliases": aliases}
