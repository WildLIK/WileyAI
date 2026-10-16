"""Chat/project lifecycle and additive migration from the original single chat."""
import uuid
from datetime import datetime, timezone

LEGACY_CHAT = "legacy"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def migrate(db):
    # Keep the table rebuild and all scope columns atomic, including on an old DB.
    # executescript() implicitly commits, so use individual statements here.
    db.execute("SAVEPOINT migrate_chatspaces")
    for statement in (
        "CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY,name TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY,title TEXT NOT NULL,project_id TEXT,created TEXT NOT NULL,updated TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS chat_dialogue (conversation_id TEXT PRIMARY KEY,value TEXT NOT NULL)",
    ):
        db.execute(statement)
    if not db.execute("SELECT 1 FROM conversations LIMIT 1").fetchone():
        time = timestamp()
        existing = db.execute("SELECT 1 FROM messages LIMIT 1").fetchone()
        db.execute("INSERT INTO conversations VALUES (?,?,NULL,?,?)", (LEGACY_CHAT, "Переписка до обновления" if existing else "Новый чат", time, time))
    for table, column, definition in [
        ("messages", "conversation_id", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("documents", "conversation_id", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("memories", "scope_id", "TEXT NOT NULL DEFAULT ''"),
        ("notes", "scope_id", "TEXT NOT NULL DEFAULT ''"),
        ("tasks", "scope_id", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if column not in {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    if "scope_id" not in {row["name"] for row in db.execute("PRAGMA table_info(memory_candidates)")}:
        for statement in (
            "ALTER TABLE memory_candidates RENAME TO memory_candidates_old",
            "CREATE TABLE memory_candidates (id TEXT PRIMARY KEY,content TEXT NOT NULL,category TEXT NOT NULL,fingerprint TEXT NOT NULL,source_message_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',memory_id TEXT,created TEXT NOT NULL,scope_id TEXT NOT NULL DEFAULT '',UNIQUE(scope_id,fingerprint))",
            "INSERT INTO memory_candidates SELECT *,'' FROM memory_candidates_old",
            "DROP TABLE memory_candidates_old",
        ):
            db.execute(statement)
    old = db.execute("SELECT value FROM dialogue_state WHERE id=1").fetchone()
    if old:
        db.execute("INSERT OR IGNORE INTO chat_dialogue VALUES (?,?)", (LEGACY_CHAT, old[0]))
        db.execute("DELETE FROM dialogue_state")
    for statement in (
        "CREATE INDEX IF NOT EXISTS messages_chat ON messages(conversation_id,created)",
        "CREATE INDEX IF NOT EXISTS memories_scope ON memories(scope_id,fingerprint)",
        "CREATE INDEX IF NOT EXISTS documents_chat ON documents(conversation_id)",
    ):
        db.execute(statement)
    db.execute("RELEASE migrate_chatspaces")


class Spaces:
    def __init__(self, store):
        self.store = store

    def projects(self):
        with self.store.db() as db:
            return [dict(row) for row in db.execute("SELECT p.*,(SELECT COUNT(*) FROM conversations c WHERE c.project_id=p.id) AS chats FROM projects p ORDER BY updated DESC,id")]

    def conversations(self):
        with self.store.db() as db:
            return [dict(row) for row in db.execute("SELECT c.*,(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS messages FROM conversations c ORDER BY updated DESC,id")]

    @staticmethod
    def name(value):
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("Название должно содержать от 1 до 100 символов")
        return value

    def create_project(self, name):
        item = dict(id=uuid.uuid4().hex, name=self.name(name), created=timestamp(), updated=timestamp())
        with self.store.db() as db:
            db.execute("INSERT INTO projects VALUES (:id,:name,:created,:updated)", item)
        return item

    def rename_project(self, project_id, name):
        with self.store.db() as db:
            if not db.execute("UPDATE projects SET name=?,updated=? WHERE id=?", (self.name(name), timestamp(), project_id)).rowcount:
                raise ValueError("Проект уже удалён")

    def create_chat(self, project_id=None, title="Новый чат"):
        item = dict(id=uuid.uuid4().hex, title=self.name(title), project_id=project_id, created=timestamp(), updated=timestamp())
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._project_exists(db, project_id)
            db.execute("INSERT INTO conversations VALUES (:id,:title,:project_id,:created,:updated)", item)
        return item

    @staticmethod
    def _project_exists(db, project_id):
        if project_id is not None and not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("Проект уже удалён")

    def update_chat(self, chat_id, title, project_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM conversations WHERE id=?", (chat_id,)).fetchone()
            if not old:
                raise ValueError("Чат уже удалён")
            self._project_exists(db, project_id)
            if project_id != old["project_id"]:
                # Moving history is explicit; inferred/confirmed project memory is
                # never silently transferred to a different scope.
                db.execute("DELETE FROM memory_candidates WHERE source_message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
                db.execute("UPDATE memories SET source_message_id=NULL WHERE source_message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
                db.execute("DELETE FROM message_memories WHERE message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
                db.execute("DELETE FROM chat_dialogue WHERE conversation_id=?", (chat_id,))
            db.execute("UPDATE conversations SET title=?,project_id=?,updated=? WHERE id=?", (self.name(title), project_id, timestamp(), chat_id))

    @staticmethod
    def _delete_chat(db, chat_id):
        db.execute("DELETE FROM memory_candidates WHERE source_message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
        db.execute("UPDATE memories SET source_message_id=NULL WHERE source_message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
        for table in ("message_memories", "web_searches"):
            db.execute(f"DELETE FROM {table} WHERE message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (chat_id,))
        for table in ("messages", "documents", "chat_dialogue"):
            db.execute(f"DELETE FROM {table} WHERE conversation_id=?", (chat_id,))
        db.execute("DELETE FROM conversations WHERE id=?", (chat_id,))

    @staticmethod
    def _ensure_chat(db):
        if not db.execute("SELECT 1 FROM conversations LIMIT 1").fetchone():
            time = timestamp()
            db.execute("INSERT INTO conversations VALUES (?,'Новый чат',NULL,?,?)", (uuid.uuid4().hex, time, time))

    def delete_chat(self, chat_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._delete_chat(db, chat_id)
            self._ensure_chat(db)

    def delete_project(self, project_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id FROM conversations WHERE project_id=?", (project_id,)).fetchall():
                self._delete_chat(db, row[0])
            db.execute("DELETE FROM message_memories WHERE memory_id IN (SELECT id FROM memories WHERE scope_id=?)", (project_id,))
            db.execute("DELETE FROM memories_fts WHERE id IN (SELECT id FROM memories WHERE scope_id=?)", (project_id,))
            db.execute("DELETE FROM notifications WHERE task_id IN (SELECT id FROM tasks WHERE scope_id=?)", (project_id,))
            for table in ("memories", "memory_candidates", "tasks", "notes"):
                db.execute(f"DELETE FROM {table} WHERE scope_id=?", (project_id,))
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._ensure_chat(db)
