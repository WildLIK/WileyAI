"""Local full-text history index. Search results never become LLM context."""
import re

from .document_library import expression


def rebuild_index(db):
    db.execute("DELETE FROM message_search")
    db.execute("INSERT INTO message_search(rowid,message_id,content) SELECT rowid,id,replace(replace(content,'ё','е'),'Ё','Е') FROM messages")


def migrate(db):
    db.execute("SAVEPOINT migrate_history_search")
    fresh = not db.execute("SELECT 1 FROM sqlite_master WHERE name='message_search'").fetchone()
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(message_id UNINDEXED,content)")
    db.execute("""CREATE TRIGGER IF NOT EXISTS messages_search_insert AFTER INSERT ON messages BEGIN
        INSERT INTO message_search(rowid,message_id,content) VALUES (new.rowid,new.id,replace(replace(new.content,'ё','е'),'Ё','Е'));
    END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS messages_search_update AFTER UPDATE OF content,id ON messages BEGIN
        DELETE FROM message_search WHERE rowid=old.rowid;
        INSERT INTO message_search(rowid,message_id,content) VALUES (new.rowid,new.id,replace(replace(new.content,'ё','е'),'Ё','Е'));
    END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS messages_search_delete AFTER DELETE ON messages BEGIN
        DELETE FROM message_search WHERE rowid=old.rowid;
    END""")
    if fresh:
        rebuild_index(db)
    db.execute("RELEASE migrate_history_search")


class History:
    def __init__(self, store):
        self.store = store

    def search(self, query, scope="space", role="all", offset=0, limit=20):
        if scope not in {"chat", "space", "all"} or role not in {"all", "user", "assistant"}:
            raise ValueError("Неизвестная область поиска или автор")
        if len(query) > 200 or offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Некорректные параметры поиска")
        term = expression(query)
        terms = re.findall(r'"([^"]+)"\*', term)
        where, args = "message_search MATCH ?", (term,)
        if scope == "chat":
            where += " AND c.id=?"
            args += (self.store.conversation_id,)
        elif scope == "space":
            where += " AND COALESCE(c.project_id,'')=?"
            args += (self.store.scope_id,)
        if role != "all":
            where += " AND m.role=?"
            args += (role,)
        source = "message_search JOIN messages m ON m.id=message_search.message_id JOIN conversations c ON c.id=m.conversation_id LEFT JOIN projects p ON p.id=c.project_id"
        with self.store.db() as db:
            db.execute("BEGIN")
            current = db.execute("SELECT project_id FROM conversations WHERE id=?", (self.store.conversation_id,)).fetchone()
            if current is None or (current[0] or "") != self.store.scope_id:
                raise ValueError("Чат удалён или перемещён. Выберите его заново")
            if not term:
                return {"items": [], "total": 0, "terms": []}
            total = db.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", args).fetchone()[0]
            rows = db.execute(f"""SELECT m.id,m.conversation_id,m.role,m.created,c.title,c.project_id,p.name AS project_name,
                snippet(message_search,1,'','',' … ',36) AS preview FROM {source} WHERE {where}
                ORDER BY bm25(message_search),m.created DESC,m.rowid DESC LIMIT ? OFFSET ?""", (*args, limit, offset)).fetchall()
        return {"items": [dict(row) | {"preview": row["preview"][:600]} for row in rows], "total": total, "terms": terms}
