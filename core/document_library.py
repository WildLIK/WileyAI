"""Scoped document library and derived local text index. No model calls."""
from datetime import datetime, timezone
import re
import unicodedata
import uuid


def expression(query):
    tokens = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", query).casefold().replace("ё", "е"))
    terms = list(dict.fromkeys(word[:6] if re.fullmatch(r"[а-я]+", word) else word for word in tokens if len(word) >= 2))
    if len(terms) > 12:
        raise ValueError("Для поиска укажите до 12 слов")
    return " AND ".join('"' + word + '"*' for word in terms)


def rebuild_index(db):
    db.execute("DELETE FROM document_search")
    for table in ("documents", "project_documents"):
        db.execute(f"INSERT INTO document_search(doc_id,name,content) SELECT id,replace(replace(name,'ё','е'),'Ё','Е'),replace(replace(content,'ё','е'),'Ё','Е') FROM {table}")


def migrate(db):
    db.execute("SAVEPOINT migrate_document_library")
    fresh = not db.execute("SELECT 1 FROM sqlite_master WHERE name='document_search'").fetchone()
    db.execute("CREATE TABLE IF NOT EXISTS project_documents (id TEXT PRIMARY KEY,name TEXT NOT NULL,content TEXT NOT NULL,created TEXT NOT NULL,project_id TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS project_documents_scope ON project_documents(project_id,created)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS document_search USING fts5(doc_id UNINDEXED,name,content)")
    for table in ("documents", "project_documents"):
        for action in ("insert", "update", "delete"):
            sql = ""
            if action in {"update", "delete"}:
                sql += "DELETE FROM document_search WHERE doc_id=old.id;"
            if action in {"insert", "update"}:
                sql += "INSERT INTO document_search(doc_id,name,content) VALUES (new.id,replace(replace(new.name,'ё','е'),'Ё','Е'),replace(replace(new.content,'ё','е'),'Ё','Е'));"
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_search_{action} AFTER {action.upper()} ON {table} BEGIN {sql} END")
        if fresh:
            db.execute(f"INSERT INTO document_search(doc_id,name,content) SELECT id,replace(replace(name,'ё','е'),'Ё','Е'),replace(replace(content,'ё','е'),'Ё','Е') FROM {table}")
    db.execute("""CREATE VIEW IF NOT EXISTS document_library AS
        SELECT id,name,content,created,conversation_id,NULL AS project_id,'chat' AS scope FROM documents
        UNION ALL SELECT id,name,content,created,NULL,project_id,'project' FROM project_documents""")
    db.execute("RELEASE migrate_document_library")


class Library:
    def __init__(self, store):
        self.store = store

    def check_chat(self, db):
        row = db.execute("SELECT project_id FROM conversations WHERE id=?", (self.store.conversation_id,)).fetchone()
        if row is None or (row[0] or "") != self.store.scope_id:
            raise ValueError("Чат удалён или перемещён. Выберите его заново")

    def visible(self, alias="d"):
        return f"(({alias}.scope='chat' AND {alias}.conversation_id=?) OR ({alias}.scope='project' AND {alias}.project_id=? AND ?!=''))", (self.store.conversation_id, self.store.scope_id, self.store.scope_id)

    def list(self, query="", scope="all", offset=0, limit=20):
        where, args = self.visible()
        if scope != "all":
            where += " AND d.scope=?"
            args += (scope,)
        source = "document_library d"
        preview = "substr(d.content,1,280)"
        ordering = "d.created DESC,d.id"
        if query.strip():
            term = expression(query)
            if not term:
                return {"items": [], "total": 0}
            source = "document_search JOIN document_library d ON d.id=document_search.doc_id"
            where += " AND document_search MATCH ?"
            args += (term,)
            preview = "snippet(document_search,2,'','',' … ',40)"
            ordering = "bm25(document_search,0,4,1),d.created DESC,d.id"
        with self.store.db() as db:
            db.execute("BEGIN")
            self.check_chat(db)
            total = db.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", args).fetchone()[0]
            rows = db.execute(f"SELECT d.id,d.name,d.created,d.scope,d.project_id,length(d.content) AS characters,{preview} AS preview FROM {source} WHERE {where} ORDER BY {ordering} LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return {"items": [dict(row) | {"preview": row["preview"][:600]} for row in rows], "total": total}

    def selected(self, ids, content=True, strict=True):
        if len(ids) > 10 or len(set(ids)) != len(ids):
            raise ValueError("Выберите до 10 разных документов")
        if not ids:
            return []
        where, args = self.visible()
        fields = "d.*" if content else "d.id,d.name,d.created,d.scope,d.project_id,length(d.content) AS characters"
        with self.store.db() as db:
            db.execute("BEGIN")
            self.check_chat(db)
            rows = db.execute(f"SELECT {fields} FROM document_library d WHERE {where} AND d.id IN ({','.join('?' for _ in ids)})", (*args, *ids)).fetchall()
        found = {row["id"]: dict(row) for row in rows}
        if strict and len(found) != len(ids):
            raise ValueError("Выбранный документ удалён или недоступен в этом чате. Выберите документы заново")
        return [found[key] for key in ids if key in found]

    def recent(self, include=()):
        items = self.list(limit=100)["items"]
        selected = self.selected(list(include), content=False, strict=False)
        return [{key: value for key, value in row.items() if key != "preview"} for row in {row["id"]: row for row in [*items, *selected]}.values()]

    def read(self, item_id, offset=0, limit=12000):
        item, = self.selected([item_id])
        text = item.pop("content")
        return {"document": item | {"characters": len(text)}, "text": text[offset:offset + limit], "offset": offset, "total": len(text)}

    def add(self, name, content, scope="chat"):
        if not 1 <= len(name) <= 4096 or not content.strip() or len(content) > 1_000_000:
            raise ValueError("Нужны название файла и текст до 1 миллиона символов")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_chat(db)
            if scope == "project":
                if not self.store.scope_id:
                    raise ValueError("Сначала выберите чат проекта")
                item = dict(id="p_" + uuid.uuid4().hex, name=name, content=content, created=datetime.now(timezone.utc).isoformat(), project_id=self.store.scope_id)
                db.execute("INSERT INTO project_documents VALUES (:id,:name,:content,:created,:project_id)", item)
            elif scope == "chat":
                item = dict(id=uuid.uuid4().hex, name=name, content=content, created=datetime.now(timezone.utc).isoformat(), conversation_id=self.store.conversation_id)
                db.execute("INSERT INTO documents (id,name,content,created,conversation_id) VALUES (:id,:name,:content,:created,:conversation_id)", item)
            else:
                raise ValueError("Неизвестное пространство документов")
        return {"id": item["id"], "name": name, "created": item["created"], "characters": len(content), "scope": scope, "project_id": self.store.scope_id if scope == "project" else None}

    def publish(self, item_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_chat(db)
            if not self.store.scope_id:
                raise ValueError("Сначала выберите чат проекта")
            source = db.execute("SELECT * FROM documents WHERE id=? AND conversation_id=?", (item_id, self.store.conversation_id)).fetchone()
            if source is None:
                raise ValueError("Документ чата удалён или недоступен")
            item = dict(id="p_" + uuid.uuid4().hex, name=source["name"], content=source["content"], created=datetime.now(timezone.utc).isoformat(), project_id=self.store.scope_id)
            db.execute("INSERT INTO project_documents VALUES (:id,:name,:content,:created,:project_id)", item)
        return {key: value for key, value in item.items() if key != "content"} | {"scope": "project", "characters": len(item["content"])}

    def remove(self, item_id):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_chat(db)
            deleted = db.execute("DELETE FROM documents WHERE id=? AND conversation_id=?", (item_id, self.store.conversation_id)).rowcount
            if not deleted and self.store.scope_id:
                deleted = db.execute("DELETE FROM project_documents WHERE id=? AND project_id=?", (item_id, self.store.scope_id)).rowcount
            if not deleted:
                raise ValueError("Документ уже удалён или недоступен в этом чате")
