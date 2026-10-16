from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from .config import Settings
from .memory import CATEGORIES, fingerprint, infer_category, normalized, search_expression, suggestions


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
                CREATE TABLE IF NOT EXISTS dialogue_state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memory_candidates (id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, source_message_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', memory_id TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS message_memories (message_id TEXT NOT NULL, memory_id TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(message_id,memory_id));
                CREATE TABLE IF NOT EXISTS web_searches (message_id TEXT PRIMARY KEY, query TEXT NOT NULL, provider TEXT NOT NULL, checked_at TEXT NOT NULL, results TEXT NOT NULL, partial INTEGER NOT NULL DEFAULT 0);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id UNINDEXED, text);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(memories)")}
            for column, definition in {"category": "TEXT NOT NULL DEFAULT 'fact'", "pinned": "INTEGER NOT NULL DEFAULT 0", "source_message_id": "TEXT", "updated": "TEXT", "revision": "INTEGER NOT NULL DEFAULT 1", "fingerprint": "TEXT"}.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")
            for row in db.execute("SELECT * FROM memories WHERE fingerprint IS NULL").fetchall():
                db.execute("UPDATE memories SET fingerprint=?,updated=?,category=? WHERE id=?", (fingerprint(row["content"]), row["created"], infer_category(row["content"]), row["id"]))
            for row in db.execute("SELECT id,content FROM memories WHERE id NOT IN (SELECT id FROM memories_fts)").fetchall():
                db.execute("INSERT INTO memories_fts VALUES (?,?)", (row["id"], normalized(row["content"])))

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

    def add_message(self, role: str, content: str, memory_context: list[dict] | None = None, web_search: dict | None = None) -> dict:
        item = dict(id=uuid.uuid4().hex, role=role, content=content, created=now())
        with self.db() as db:
            db.execute("INSERT INTO messages VALUES (:id,:role,:content,:created)", item)
            for memory in memory_context or []:
                db.execute("INSERT OR IGNORE INTO message_memories SELECT ?,id,revision FROM memories WHERE id=? AND revision=?", (item["id"], memory["id"], memory["revision"]))
            item["memory_context"] = [dict(row) for row in db.execute("SELECT m.id,m.content,m.revision FROM memories m JOIN message_memories mm ON mm.memory_id=m.id AND mm.revision=m.revision WHERE mm.message_id=?", (item["id"],))]
            if web_search is not None:
                db.execute("INSERT INTO web_searches VALUES (?,?,?,?,?,?)", (item["id"], web_search["query"], web_search["provider"], web_search["checked_at"], json.dumps(web_search["results"], ensure_ascii=False), int(web_search["partial"])))
                item["web_search"] = web_search
        return item

    def messages(self, limit: int = 250) -> list[dict]:
        items = self.list("messages", limit)
        if items:
            by_id = {item["id"]: item for item in items}
            for item in items:
                item["memory_context"] = []
            with self.db() as db:
                rows = db.execute(f"SELECT mm.message_id,m.id,m.content,m.revision FROM message_memories mm JOIN memories m ON m.id=mm.memory_id AND m.revision=mm.revision WHERE mm.message_id IN ({','.join('?' for _ in items)})", tuple(by_id)).fetchall()
                searches = db.execute(f"SELECT * FROM web_searches WHERE message_id IN ({','.join('?' for _ in items)})", tuple(by_id)).fetchall()
            for row in rows:
                by_id[row["message_id"]]["memory_context"].append({"id": row["id"], "content": row["content"], "revision": row["revision"]})
            for row in searches:
                by_id[row["message_id"]]["web_search"] = {"query": row["query"], "provider": row["provider"], "checked_at": row["checked_at"], "results": json.loads(row["results"]), "partial": bool(row["partial"])}
        return items

    def web_source(self, message_id: str, index: int) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT results FROM web_searches WHERE message_id=?", (message_id,)).fetchone()
        results = json.loads(row[0]) if row else []
        return results[index] if 0 <= index < len(results) else None

    def _write_memory(self, db, content, category, pinned=False, source_message_id=None, item_id=None):
        content = content.strip()
        if not 1 <= len(content) <= 1200 or category not in CATEGORIES:
            raise ValueError("Запись памяти должна содержать от 1 до 1200 символов и допустимую категорию")
        digest = fingerprint(content)
        existing = db.execute("SELECT * FROM memories WHERE fingerprint=? AND id!=?", (digest, item_id or "")).fetchone()
        if existing:
            if item_id:
                raise ValueError("Такая запись памяти уже существует")
            return dict(existing)
        if item_id:
            previous = db.execute("SELECT * FROM memories WHERE id=?", (item_id,)).fetchone()
            if not previous:
                raise ValueError("Запись памяти уже удалена")
            revised = int(content != previous["content"] or category != previous["category"])
            db.execute("UPDATE memories SET content=?,category=?,pinned=?,fingerprint=?,updated=?,revision=revision+? WHERE id=?", (content, category, int(pinned), digest, now(), revised, item_id))
        else:
            item_id = uuid.uuid4().hex
            db.execute("INSERT INTO memories (id,content,created,category,pinned,source_message_id,updated,fingerprint) VALUES (?,?,?,?,?,?,?,?)", (item_id, content, now(), category, int(pinned), source_message_id, now(), digest))
        db.execute("DELETE FROM memories_fts WHERE id=?", (item_id,))
        db.execute("INSERT INTO memories_fts VALUES (?,?)", (item_id, normalized(content)))
        return dict(db.execute("SELECT * FROM memories WHERE id=?", (item_id,)).fetchone())

    def add_memory(self, content: str, category: str | None = None, pinned: bool = False, source_message_id: str | None = None) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._write_memory(db, content, category or infer_category(content), pinned, source_message_id)

    def edit_memory(self, item_id: str, content: str, category: str | None, pinned: bool) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT category FROM memories WHERE id=?", (item_id,)).fetchone()
            return self._write_memory(db, content, category or (previous[0] if previous else "fact"), pinned, item_id=item_id)

    def memories(self, query: str = "", limit: int = 500) -> list[dict]:
        expression = search_expression(query)
        with self.db() as db:
            if query.strip() and not expression:
                return []
            if expression:
                rows = db.execute("SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.id WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts),m.pinned DESC,m.updated DESC LIMIT ?", (expression, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM memories ORDER BY pinned DESC,updated DESC,id LIMIT ?", (limit,)).fetchall()
            result = [dict(row) for row in rows]
            for item in result:
                source = db.execute("SELECT content FROM messages WHERE id=?", (item["source_message_id"],)).fetchone()
                item["source_text"] = source[0] if source else None
            return result

    def memory_context(self, text: str, budget: int = 1600) -> list[dict]:
        recent = self.memories(limit=12)
        candidates = [item for item in recent if item["pinned"]][:4] + self.memories(text, 8) + recent[:3]
        selected, seen, used = [], set(), 2
        for item in candidates:
            cost = len(json.dumps({"id": item["id"], "content": item["content"], "category": item["category"]}, ensure_ascii=False)) + (2 if selected else 0)
            if item["fingerprint"] in seen or used + cost > budget:
                continue
            selected.append(item)
            seen.add(item["fingerprint"])
            used += cost
            if len(selected) == 8:
                break
        return selected

    def suggest_memories(self, source_message_id: str) -> list[dict]:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            source = db.execute("SELECT content FROM messages WHERE id=? AND role='user'", (source_message_id,)).fetchone()
            if not source:
                return []
            for candidate in suggestions(source[0]):
                if db.execute("SELECT COUNT(*) FROM memory_candidates WHERE status='pending'").fetchone()[0] >= 50:
                    break
                digest = fingerprint(candidate["content"])
                if db.execute("SELECT 1 FROM memories WHERE fingerprint=?", (digest,)).fetchone():
                    continue
                db.execute("INSERT OR IGNORE INTO memory_candidates (id,content,category,fingerprint,source_message_id,created) VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, candidate["content"], candidate["category"], digest, source_message_id, now()))
        return self.memory_candidates()

    def memory_candidates(self) -> list[dict]:
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT c.*,m.content AS source_text FROM memory_candidates c JOIN messages m ON m.id=c.source_message_id WHERE c.status='pending' ORDER BY c.created DESC,c.id LIMIT 50")]

    def accept_memory(self, candidate_id: str, content: str, category: str | None, pinned: bool | None = None, replace_id: str | None = None) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            candidate = db.execute("SELECT * FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
            if not candidate or candidate["status"] == "dismissed":
                raise ValueError("Предложение уже отклонено или удалено")
            if candidate["status"] == "accepted":
                existing = db.execute("SELECT * FROM memories WHERE id=?", (candidate["memory_id"],)).fetchone()
                if not existing:
                    raise ValueError("Принятая запись уже удалена")
                return dict(existing)
            if pinned is None and replace_id:
                previous = db.execute("SELECT pinned FROM memories WHERE id=?", (replace_id,)).fetchone()
                pinned = bool(previous[0]) if previous else False
            item = self._write_memory(db, content, category or candidate["category"], bool(pinned), candidate["source_message_id"], replace_id)
            if replace_id:
                db.execute("UPDATE memories SET source_message_id=? WHERE id=?", (candidate["source_message_id"], item["id"]))
                item["source_message_id"] = candidate["source_message_id"]
            db.execute("UPDATE memory_candidates SET status='accepted',memory_id=?,content='' WHERE id=?", (item["id"], candidate_id))
            return item

    def dismiss_memory(self, candidate_id: str):
        with self.db() as db:
            db.execute("UPDATE memory_candidates SET status='dismissed',content='' WHERE id=? AND status='pending'", (candidate_id,))

    def remove(self, table: str, item_id: str):
        if table not in {"memories", "aliases", "documents", "tasks", "notes"}:
            raise ValueError("Unknown table")
        with self.db() as db:
            db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            if table == "memories":
                db.execute("DELETE FROM memories_fts WHERE id=?", (item_id,))
                db.execute("DELETE FROM message_memories WHERE memory_id=?", (item_id,))
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
            db.execute("BEGIN IMMEDIATE")
            self._write_task(db, item)
            item = dict(db.execute("SELECT * FROM tasks WHERE id=?", (item["id"],)).fetchone())
        return item

    def _write_task(self, db, item):
        previous = db.execute("SELECT due FROM tasks WHERE id=?", (item["id"],)).fetchone()
        if previous and previous["due"] != item["due"]:
            db.execute("DELETE FROM notifications WHERE task_id=? AND delivered=0", (item["id"],))
        db.execute("INSERT INTO tasks (id,title,kind,due,done,created) VALUES (:id,:title,:kind,:due,:done,:created) ON CONFLICT(id) DO UPDATE SET title=excluded.title,kind=excluded.kind,due=excluded.due,done=excluded.done,notified=CASE WHEN tasks.due IS excluded.due THEN tasks.notified ELSE 0 END", item)
        if item["done"]:
            db.execute("UPDATE notifications SET delivered=1 WHERE task_id=?", (item["id"],))

    def task(self, item_id: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def revise_task(self, item_id: str, **changes) -> dict | None:
        if changes.keys() - {"title", "due", "done"}:
            raise ValueError("Недопустимое изменение задачи")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone()
            if not row:
                return None
            item = {**dict(row), **changes}
            self._write_task(db, item)
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone())

    def dialogue(self) -> dict:
        with self.db() as db:
            row = db.execute("SELECT value FROM dialogue_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def save_dialogue(self, value: dict):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO dialogue_state VALUES (1,?)", (json.dumps(value, ensure_ascii=False),))

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
