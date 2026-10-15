"""Portable data snapshots. Imports are data, never SQLite files or executable code."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import threading
import time
from typing import Annotated, Literal
import uuid

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from .config import Settings
from .memory import fingerprint, normalized
from .storage import Store, now

MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 200_000
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Bit = Annotated[int, Field(ge=0, le=1)]


def utc(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Нужен часовой пояс")
    return parsed.astimezone(timezone.utc).isoformat()


Timestamp = Annotated[str, AfterValidator(utc)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Dated(Record):
    id: Id
    created: Timestamp


class Message(Dated):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1_000_000)


class Memory(Dated):
    content: str = Field(min_length=1, max_length=6000)  # Preserve older manual records too.
    category: Literal["fact", "preference", "profile"]
    pinned: Bit
    source_message_id: Id | None
    updated: Timestamp
    revision: int = Field(ge=1)


class Candidate(Dated):
    content: str = Field(max_length=1200)
    category: Literal["fact", "preference", "profile"]
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    source_message_id: Id
    status: Literal["pending", "accepted", "dismissed"]
    memory_id: Id | None


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


class Note(Dated):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=20000)


class Task(Dated):
    title: str = Field(min_length=1, max_length=500)
    kind: Literal["todo", "reminder", "timer", "alarm"]
    due: Timestamp | None
    done: Bit
    notified: Bit


class Notification(Dated):
    task_id: Id
    title: str = Field(max_length=500)
    delivered: Bit


TABLES = {
    "messages": Message, "memories": Memory, "memory_candidates": Candidate,
    "message_memories": Reference, "aliases": Alias, "documents": Document,
    "notes": Note, "tasks": Task, "notifications": Notification,
}


class Data(Record):
    messages: list[Message]
    memories: list[Memory]
    memory_candidates: list[Candidate]
    message_memories: list[Reference]
    aliases: list[Alias]
    documents: list[Document]
    notes: list[Note]
    tasks: list[Task]
    notifications: list[Notification]


class Bundle(Record):
    format: Literal["wileyai.backup"]
    version: Literal[1]
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
        if set(bundle.settings) - Settings.model_fields.keys():
            raise ValueError("Неизвестные настройки")
        bundle.settings = Settings.model_validate(bundle.settings, strict=True).model_dump()
        tables = bundle.data.model_dump()
        if sum(map(len, tables.values())) > MAX_RECORDS:
            raise ValueError("Слишком много записей")
        for name, rows in tables.items():
            keys = [(row["message_id"], row["memory_id"]) if name == "message_memories" else row["id"] for row in rows]
            if len(keys) != len(set(keys)):
                raise ValueError("Повторяющиеся записи")
        messages = {row["id"]: row for row in tables["messages"]}
        memories = {row["id"]: row for row in tables["memories"]}
        tasks = {row["id"]: row for row in tables["tasks"]}
        for memory in memories.values():
            if memory["source_message_id"] is not None and messages.get(memory["source_message_id"], {}).get("role") != "user":
                raise ValueError("Неверный источник памяти")
        for ref in tables["message_memories"]:
            if messages.get(ref["message_id"], {}).get("role") != "assistant" or ref["memory_id"] not in memories or ref["revision"] > memories[ref["memory_id"]]["revision"]:
                raise ValueError("Неверная ссылка памяти")
        candidates = tables["memory_candidates"]
        if len({row["fingerprint"] for row in candidates}) != len(candidates):
            raise ValueError("Повторяющиеся предложения")
        if sum(row["status"] == "pending" for row in candidates) > 50:
            raise ValueError("Слишком много предложений")
        for row in candidates:
            if messages.get(row["source_message_id"], {}).get("role") != "user":
                raise ValueError("Неверный источник предложения")
            if row["status"] == "pending":
                if not row["content"].strip() or fingerprint(row["content"]) != row["fingerprint"] or row["memory_id"] is not None:
                    raise ValueError("Неверное предложение")
            elif row["content"] or (row["status"] == "accepted" and row["memory_id"] is None):
                raise ValueError("Неверный статус предложения")
        names = [row["name"].casefold().strip() for row in tables["aliases"]]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Повторяющиеся команды")
        for row in tables["notifications"]:
            if not row["delivered"] and row["task_id"] not in tasks:
                raise ValueError("Напоминание без задачи")
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
    return {"format": "wileyai.backup", "version": 1, "created": now(), "settings": settings.model_dump(), "data": tables}


def state_digest(db, value: dict) -> str:
    dialogue = [dict(row) for row in db.execute("SELECT * FROM dialogue_state")]
    return hashlib.sha256(encode({"settings": value["settings"], "data": value["data"], "dialogue": dialogue})).hexdigest()


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
                if rows:
                    db.executemany(f"INSERT INTO {name} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [tuple(row[column] for column in columns) for row in rows])
            db.execute("DELETE FROM memories_fts")
            db.executemany("INSERT INTO memories_fts VALUES (?,?)", [(row["id"], normalized(row["content"])) for row in tables["memories"]])
            db.execute("DELETE FROM dialogue_state")
            settings = bundle.settings if connections else {**previous["settings"], **{key: bundle.settings[key] for key in ("name", "personality", "memory_suggestions")}}
            db.execute("INSERT OR REPLACE INTO config VALUES (1,?)", (Settings.model_validate(settings).model_dump_json(),))
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?)", (uuid.uuid4().hex, "backup", "restore", "restored", now()))
        return {"recovery_path": str(path.resolve()), "counts": {name: len(rows) for name, rows in tables.items()}, "connections": connections, "aliases": aliases}
