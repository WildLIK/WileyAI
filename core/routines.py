"""Named, scoped sequences of opening tools. No scripts or generated actions."""
import asyncio
import json
import re
import uuid
from typing import Literal

from anyio import CancelScope
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import commands
from .storage import now
from .tools import OpenTools, ToolDisabled


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["folder", "file", "app", "url"]
    target: str = Field(min_length=1, max_length=4096)
    label: str = Field(min_length=1, max_length=150)

    @field_validator("target", "label")
    @classmethod
    def clean(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Укажите название и путь без управляющих символов")
        return value.strip()

    def command(self):
        return commands.Command(self.kind, self.target, self.label)


class RoutineBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    steps: list[Step] = Field(min_length=1, max_length=12)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not commands.normalize(value) or any(mark in value for mark in ('"', '«', '»', '“', '”', '?')):
            raise ValueError("Название сценария должно быть без кавычек и вопросительного знака")
        return value


def requested_name(text):
    if any(mark in text for mark in ('"', '«', '»', '“', '”', '?')) or any(ord(char) < 32 for char in text):
        return None
    match = re.fullmatch(r"(?:пожалуйста,?\s+)?(?:запусти|выполни|запустить)\s+сценарий\s+(.+?)[.! ]*", text.strip(), re.I)
    return commands.normalize(match[1]) if match else None


class Routines:
    def __init__(self, store):
        self.store = store

    def list(self):
        with self.store.db() as db:
            rows = db.execute("SELECT * FROM routines WHERE scope_id=? ORDER BY updated DESC,id", (self.store.scope_id,)).fetchall()
        return [{**dict(row), "steps": json.loads(row["steps"])} for row in rows]

    def get(self, item_id):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM routines WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
        return {**dict(row), "steps": json.loads(row["steps"])} if row else None

    def find(self, name):
        # Prefer an exact saved title, even if it ends with «пожалуйста».
        with self.store.db() as db:
            for key in dict.fromkeys([name, re.sub(r",?\s+пожалуйста$", "", name)]):
                row = db.execute("SELECT * FROM routines WHERE name_key=? AND scope_id=?", (key, self.store.scope_id)).fetchone()
                if row:
                    return {**dict(row), "steps": json.loads(row["steps"])}
        return None

    def save(self, body, item_id=None):
        # Validate paths now; backups may carry missing paths and are checked on run.
        for step in body.steps:
            commands.validate(step.command())
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._check_scope(db)
            if item_id and not db.execute("SELECT 1 FROM routines WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone():
                raise ValueError("Сценарий уже удалён или принадлежит другому проекту")
            key = commands.normalize(body.name)
            if db.execute("SELECT 1 FROM routines WHERE name_key=? AND scope_id=? AND id!=?", (key, self.store.scope_id, item_id or "")).fetchone():
                raise ValueError("Сценарий с таким названием уже есть в этом пространстве")
            item_id = item_id or uuid.uuid4().hex
            db.execute("INSERT INTO routines VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,name_key=excluded.name_key,steps=excluded.steps,updated=excluded.updated", (item_id, body.name, key, json.dumps([step.model_dump() for step in body.steps], ensure_ascii=False), self.store.scope_id, now(), now()))
        return self.get(item_id)

    def remove(self, item_id):
        with self.store.db() as db:
            db.execute("DELETE FROM routines WHERE id=? AND scope_id=?", (item_id, self.store.scope_id))

    def check(self, item):
        tools = OpenTools(self.store)
        for index, value in enumerate(item["steps"], 1):
            try:
                tools.validate(Step.model_validate(value).command())
            except ValueError as error:
                raise ValueError(f"Шаг {index}: {error}") from error
        return {"text": f"Проверено шагов: {len(item['steps'])}. Запуск не выполнялся."}


async def run_step(tools, value, progress, outcomes=None, on_dispatch=None):
    """Wait for an in-flight Windows dispatch before releasing the chat lock."""
    step = Step.model_validate(value)
    operation = asyncio.create_task(asyncio.to_thread(tools.execute, step.command(), **({"on_dispatch": on_dispatch} if on_dispatch else {})))
    def finish(result=None, error=None):
        progress.append(f"{len(progress) + 1}. {result}" if error is None else f"{len(progress) + 1}. Не выполнено «{step.label}»: {error}")
        if outcomes is not None:
            evidence = getattr(result, "evidence", None) or {}
            outcomes.append({"action": step.kind, "target": step.label, "status": ("denied" if isinstance(error, ToolDisabled) else "error") if error else evidence.get("status", "dispatched"), "details": evidence})
        return error is None
    try:
        result = await asyncio.shield(operation)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            try:
                finish(result=await operation)
            except Exception as error:
                finish(error=error)
        raise
    except Exception as error:
        return finish(error=error)
    return finish(result=result)
