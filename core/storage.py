from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from .config import Settings


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "wileyai.db"
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS aliases (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, target TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, name TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, due TEXT, done INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, title TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            yield db

    def settings(self) -> Settings:
        with self.db() as db:
            row = db.execute("SELECT value FROM config WHERE id=1").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, settings: Settings):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES (1, ?)", (settings.model_dump_json(),))

    def list(self, table: str, limit: int = 100) -> list[dict]:
        if table not in {"messages", "memories", "aliases", "documents", "actions", "tasks", "notes", "notifications"}:
            raise ValueError("Unknown table")
        ordering = "name" if table == "aliases" else "created"
        with self.db() as db:
            rows = db.execute(f"SELECT * FROM (SELECT * FROM {table} ORDER BY {ordering} DESC LIMIT ?) ORDER BY {ordering}", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def add_message(self, role: str, content: str) -> dict:
        item = dict(id=uuid.uuid4().hex, role=role, content=content, created=now())
        with self.db() as db:
            db.execute("INSERT INTO messages VALUES (:id,:role,:content,:created)", item)
        return item

    def add_memory(self, content: str) -> dict:
        item = dict(id=uuid.uuid4().hex, content=content, created=now())
        with self.db() as db:
            db.execute("INSERT INTO memories VALUES (:id,:content,:created)", item)
        return item

    def remove(self, table: str, item_id: str):
        if table not in {"memories", "aliases", "documents", "tasks", "notes"}:
            raise ValueError("Unknown table")
        with self.db() as db:
            db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            if table == "tasks":
                db.execute("DELETE FROM notifications WHERE task_id=? AND delivered=0", (item_id,))

    def audit(self, kind: str, target: str, status: str):
        with self.db() as db:
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?)", (uuid.uuid4().hex, kind, target, status, now()))

    def add_alias(self, name: str, kind: str, target: str) -> dict:
        item = dict(id=uuid.uuid4().hex, name=name.casefold().strip(), kind=kind, target=target)
        with self.db() as db:
            db.execute("INSERT INTO aliases VALUES (:id,:name,:kind,:target) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,target=excluded.target", item)
        return item

    def add_document(self, name: str, content: str) -> dict:
        item = dict(id=uuid.uuid4().hex, name=name, content=content, created=now())
        with self.db() as db:
            db.execute("INSERT INTO documents VALUES (:id,:name,:content,:created)", item)
        return item

    def save_note(self, title: str, content: str, item_id: str | None = None) -> dict:
        item = dict(id=item_id or uuid.uuid4().hex, title=title, content=content, created=now())
        with self.db() as db:
            db.execute("INSERT INTO notes VALUES (:id,:title,:content,:created) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content", item)
        return item

    def save_task(self, title: str, kind: str, due: str | None, done: bool = False, item_id: str | None = None) -> dict:
        item = dict(id=item_id or uuid.uuid4().hex, title=title, kind=kind, due=due, done=int(done), created=now())
        with self.db() as db:
            db.execute("INSERT INTO tasks (id,title,kind,due,done,created) VALUES (:id,:title,:kind,:due,:done,:created) ON CONFLICT(id) DO UPDATE SET title=excluded.title,kind=excluded.kind,due=excluded.due,done=excluded.done,notified=CASE WHEN tasks.due IS excluded.due THEN tasks.notified ELSE 0 END", item)
            if done:
                db.execute("UPDATE notifications SET delivered=1 WHERE task_id=?", (item["id"],))
        return item

    def queue_due_notifications(self) -> list[dict]:
        pending = []
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for task in db.execute("SELECT * FROM tasks WHERE done=0 AND notified=0 AND due IS NOT NULL AND due<=?", (now(),)).fetchall():
                item = dict(id=uuid.uuid4().hex, task_id=task["id"], title=task["title"], created=now())
                db.execute("INSERT INTO notifications (id,task_id,title,created) VALUES (:id,:task_id,:title,:created)", item)
                db.execute("UPDATE tasks SET notified=1 WHERE id=?", (task["id"],))
                pending.append(item)
        return pending

    def acknowledge_notification(self, item_id: str):
        with self.db() as db:
            db.execute("UPDATE notifications SET delivered=1 WHERE id=?", (item_id,))
