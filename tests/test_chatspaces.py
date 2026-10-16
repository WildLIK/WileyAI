from datetime import datetime, timezone, timedelta
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core import providers
from core.backups import Backups, encode
from core.chatspaces import Spaces, migrate
from core.memory import fingerprint
from core.storage import Store
from core.workflows import Workflows


def setup(root):
    store = Store(root)
    spaces = Spaces(store)
    project = spaces.create_project("Проект Альтаир")
    other = spaces.create_project("Проект Кедр")
    a = spaces.create_chat(project["id"], "Первый чат")
    b = spaces.create_chat(project["id"], "Второй чат")
    c = spaces.create_chat(other["id"], "Чужой чат")
    return store, spaces, project, other, a, b, c


def test_history_documents_memory_and_duplicates_are_partitioned(tmp_path):
    store, spaces, project, other, a, b, c = setup(tmp_path)
    common = store.for_chat()
    first, second, outsider = (store.for_chat(chat["id"]) for chat in (a, b, c))
    common.add_memory("Код проекта СЕКРЕТ-ОБЩИЙ", pinned=True)
    source = first.add_message("user", "Я предпочитаю короткие ответы")
    proposal, = first.suggest_memories(source["id"])
    accepted = first.accept_memory(proposal["id"], proposal["content"], None)
    first.add_message("assistant", "Отвечаю", [accepted])
    doc = first.add_document("private.txt", "ПРОЕКТ-СЕКРЕТ")
    assert len(first.messages()) == 2 and second.messages() == [] and outsider.messages() == []
    assert second.list("documents") == [] and outsider.list("documents") == []
    assert first.list("documents")[0]["id"] == doc["id"]
    assert second.memory_context("Короткие ответы")[0]["id"] == accepted["id"]
    assert outsider.memories() == []
    assert "СЕКРЕТ-ОБЩИЙ" not in str(first.memory_context("Код проекта"))
    same = outsider.add_message("user", source["content"])
    assert len(outsider.suggest_memories(same["id"])) == 1
    outsider.add_memory(proposal["content"])
    assert len(outsider.memories()) == 1


def test_mutating_other_project_records_by_id_is_rejected(tmp_path):
    store, _, _, _, a, _, c = setup(tmp_path)
    own, other = store.for_chat(a["id"]), store.for_chat(c["id"])
    fact = own.add_memory("Только первый проект")
    note = own.save_note("Приватная", "Содержание")
    task = own.save_task("Задача проекта", "todo", None)
    source = own.add_message("user", "Я предпочитаю краткие ответы")
    proposal, = own.suggest_memories(source["id"])
    for operation in [lambda: other.edit_memory(fact["id"], "Переписано", None, False), lambda: other.accept_memory(proposal["id"], proposal["content"], None), lambda: other.save_note("Новое", "", note["id"]), lambda: other.save_task("Новое", "todo", None, item_id=task["id"]), lambda: other.add_memory("Неверный источник", source_message_id=source["id"])]:
        with pytest.raises(ValueError): operation()
    other.remove("memories", fact["id"])
    other.remove("tasks", task["id"])
    other.dismiss_memory(proposal["id"])
    assert own.memories()[0]["content"] == fact["content"]
    assert own.task(task["id"]) is not None and len(own.memory_candidates()) == 1


def test_moving_chat_transfers_history_and_files_without_copying_memory(tmp_path):
    store, spaces, _, other, a, _, _ = setup(tmp_path)
    first = store.for_chat(a["id"])
    source = first.add_message("user", "Я предпочитаю Python")
    candidate, = first.suggest_memories(source["id"])
    fact = first.accept_memory(candidate["id"], candidate["content"], None)
    first.add_message("assistant", "Принято", [fact])
    first.add_document("Код.txt", "Файл следует за чатом")
    first.save_dialogue({"pending": "черновик"})
    spaces.update_chat(a["id"], "Перенесённый чат", other["id"])
    moved = store.for_chat(a["id"])
    assert moved.scope_id == other["id"] and len(moved.messages()) == 2
    assert moved.messages()[-1]["memory_context"] == []
    assert len(moved.list("documents")) == 1 and moved.memories() == []
    assert moved.memory_candidates() == [] and moved.dialogue() == {}
    assert first.memories()[0]["id"] == fact["id"] and first.memories()[0]["source_text"] is None
    with pytest.raises(ValueError): first.save_dialogue({"pending": "late old scope"})
    Backups(store).export()  # No broken source links after moving.


def test_delete_chat_and_project_clean_links_without_erasing_general_memory(tmp_path):
    store, spaces, project, _, a, b, _ = setup(tmp_path)
    common = store.add_memory("Общая память остаётся")
    scoped = store.for_chat(a["id"])
    source = scoped.add_message("user", "Я предпочитаю Python")
    candidate, = scoped.suggest_memories(source["id"])
    fact = scoped.accept_memory(candidate["id"], candidate["content"], None)
    scoped.add_document("План.txt", "Текст")
    scoped.save_note("Заметка проекта", "Текст")
    scoped.save_task("Просрочено", "reminder", (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    scoped.queue_due_notifications()
    spaces.delete_chat(a["id"])
    survivor = store.for_chat(b["id"])
    assert survivor.memories()[0]["id"] == fact["id"] and survivor.memories()[0]["source_text"] is None
    with pytest.raises(ValueError): store.for_chat(a["id"])
    spaces.delete_project(project["id"])
    assert store.memories()[0]["id"] == common["id"]
    assert not [row for row in spaces.conversations() if row["project_id"] == project["id"]]
    assert store.list("notifications") == []
    with pytest.raises(ValueError): scoped.add_memory("Не воскрешать проект")
    with pytest.raises(ValueError): scoped.add_document("late.txt", "Late")
    with pytest.raises(ValueError): scoped.save_dialogue({"pending": "late"})
    Backups(store).export()


def test_last_chat_can_be_deleted_without_reappearing_after_restart(tmp_path):
    store = Store(tmp_path)
    first = store.conversation_id
    Spaces(store).delete_chat(first)
    chats = Spaces(Store(tmp_path)).conversations()
    assert len(chats) == 1 and chats[0]["id"] != first


def test_dialogue_drafts_are_separate_even_for_two_chats_in_one_project(tmp_path):
    store, _, _, _, a, b, _ = setup(tmp_path)
    first, second = store.for_chat(a["id"]), store.for_chat(b["id"])
    assert "Когда" in Workflows(first).handle("Напомни проверить проект", "Asia/Yekaterinburg").text
    assert second.dialogue() == {}
    assert Workflows(second).handle("завтра в 11", "Asia/Yekaterinburg") is None
    assert second.list("tasks") == []
    assert "создано" in Workflows(first).handle("завтра в 11", "Asia/Yekaterinburg").text.casefold()


@pytest.mark.parametrize("interrupted", [False, True])
def test_existing_single_chat_and_draft_migrate_without_deletion(tmp_path, interrupted):
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE messages(id TEXT PRIMARY KEY,role TEXT NOT NULL,content TEXT NOT NULL,created TEXT NOT NULL)")
        db.execute("INSERT INTO messages VALUES ('old-user','user','Старая переписка','2026-10-01T10:00:00+00:00')")
        db.execute("CREATE TABLE dialogue_state(id INTEGER PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT INTO dialogue_state VALUES (1,?)", (json.dumps({"last_task": "old-task"}),))
        db.execute("CREATE TABLE memory_candidates(id TEXT PRIMARY KEY,content TEXT NOT NULL,category TEXT NOT NULL,fingerprint TEXT NOT NULL UNIQUE,source_message_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',memory_id TEXT,created TEXT NOT NULL)")
        db.execute("INSERT INTO memory_candidates VALUES ('old-candidate','Я предпочитаю Python','preference',?,'old-user','pending',NULL,'2026-10-01T10:00:00+00:00')", (fingerprint("Я предпочитаю Python"),))
        for table, columns in {"memories": "content TEXT,fingerprint TEXT", "documents": "name TEXT,content TEXT", "notes": "title TEXT,content TEXT", "tasks": "title TEXT"}.items():
            db.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,created TEXT,{columns})")
    if interrupted:
        with sqlite3.connect(tmp_path / "wileyai.db") as db:
            db.row_factory = sqlite3.Row
            db.set_authorizer(lambda action, name, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_INDEX and name == "messages_chat" else sqlite3.SQLITE_OK)
            with pytest.raises(sqlite3.DatabaseError):
                with db:
                    migrate(db)
            db.set_authorizer(None)
            assert "scope_id" not in {row["name"] for row in db.execute("PRAGMA table_info(memory_candidates)")}
            assert db.execute("SELECT content FROM memory_candidates").fetchone()[0] == "Я предпочитаю Python"
            assert db.execute("SELECT 1 FROM dialogue_state").fetchone() is not None
            assert db.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone() is None
    store = Store(tmp_path)
    assert store.messages()[0]["content"] == "Старая переписка"
    assert Spaces(store).conversations()[0]["title"] == "Переписка до обновления"
    assert store.dialogue()["last_task"] == "old-task"
    assert store.memory_candidates()[0]["id"] == "old-candidate"
    assert Store(tmp_path).messages() == store.messages()


def test_backup_current_roundtrip_scopes_and_v1_conversion(tmp_path):
    source, _, _, _, a, _, c = setup(tmp_path / "source")
    source.for_chat(a["id"]).add_message("user", "Только первый проект")
    source.for_chat(a["id"]).add_memory("Первый факт")
    source.for_chat(c["id"]).add_memory("Другой факт")
    archive = Backups(source).export()
    assert json.loads(archive)["version"] == 6
    target = Store(tmp_path / "target")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.for_chat(a["id"]).memories()[0]["content"] == "Первый факт"
    assert target.for_chat(c["id"]).memories()[0]["content"] == "Другой факт"
    assert target.for_chat(c["id"]).messages() == []
    value = json.loads(archive)
    value["data"]["conversations"][0]["project_id"] = "missing"
    with pytest.raises(ValueError): manager.preview(encode(value))
    old = json.loads(Backups(Store(tmp_path / "old")).export())
    old["version"] = 1
    del old["data"]["projects"]
    del old["data"]["conversations"]
    manager.restore(manager.preview(encode(old))["ticket"])
    assert len(Spaces(target).conversations()) == 1


def test_api_model_never_receives_other_chat_history_or_general_memory_in_project(tmp_path, monkeypatch):
    captured = []
    async def chat(config, messages):
        captured.append(messages)
        yield "Ответ"
    monkeypatch.setattr(providers, "chat", chat)
    monkeypatch.setattr(providers, "get_key", lambda settings: "")
    token = "chat-spaces-test-0123456789abcdef"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        general = api.get("/conversations").json()[0]
        api.post("/chat", json={"text": "Запомни: СЕКРЕТ-ОБЩИЙ", "conversation_id": general["id"]})
        project = api.post("/projects", json={"name": "Собственная память"}).json()
        first = api.post("/conversations", json={"project_id": project["id"]}).json()
        second = api.post("/conversations", json={"project_id": project["id"]}).json()
        api.post("/chat", json={"text": "Запомни: КОД-ПРОЕКТА", "conversation_id": first["id"]})
        api.post("/chat", json={"text": "СЕКРЕТ-ИСТОРИИ-ПЕРВОГО-ЧАТА", "conversation_id": first["id"]})
        doc = api.post("/documents?conversation_id=" + first["id"], files={"file": ("secret.txt", b"PRIVATE-FIRST-DOC")}).json()
        assert api.post("/chat", json={"text": "Что помнишь?", "conversation_id": second["id"], "document_ids": [doc["id"]]}).status_code == 400
        api.post("/chat", json={"text": "Что помнишь?", "conversation_id": second["id"]})
        payload = str(captured[-1])
        assert "КОД-ПРОЕКТА" in payload
        assert "СЕКРЕТ-ОБЩИЙ" not in payload and "СЕКРЕТ-ИСТОРИИ" not in payload and "PRIVATE-FIRST-DOC" not in payload
        assert len(api.get("/messages?conversation_id=" + second["id"]).json()) == 2
        api.post("/chat", json={"text": "Обычный разговор", "conversation_id": general["id"]})
        assert "КОД-ПРОЕКТА" not in str(captured[-1]) and "СЕКРЕТ-ОБЩИЙ" in str(captured[-1])
