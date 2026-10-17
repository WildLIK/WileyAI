import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.backups import Backups, encode, parse
from core.chatspaces import Spaces
from core.document_library import Library
from core.document_context import DocumentFragment
from core.documents import selected_context
from core.storage import Store
from core import providers

TOKEN = "document-context-tests-0123456789"


@pytest.mark.parametrize("budget", [0, 40, 100, 300, 2000, 6000])
def test_snapshots_match_exactly_the_fragment_and_range_sent_in_context(budget):
    docs = [
        {"id": "first", "name": "Первый " * 20 + ".txt", "content": "пусто " * 190 + " ФЕНИКС=7351 😺 " + "хвост " * 1000},
        {"id": "second", "name": "Второй.txt", "content": "начало " * 500 + " ФЕНИКС=8420 " + "другое " * 800},
    ]
    result = selected_context("ФЕНИКС", docs, budget)
    assert len(result["text"]) <= budget
    by_id = {doc["id"]: doc for doc in docs}
    rebuilt = []
    for source in result["sources"]:
        DocumentFragment.model_validate(source)
        document = by_id[source["document_id"]]
        assert source["name"] == document["name"]
        assert source["total"] == len(document["content"])
        assert source["text"] == document["content"][source["offset"]:source["offset"] + len(source["text"])]
        rebuilt.append(f'Источник: {source["name"][:80]}, фрагмент с символа {source["offset"] + 1}\n' + source["text"])
    assert result["text"] == "\n\n".join(rebuilt)
    assert len(result["sources"]) <= 4
    if budget >= 300:
        assert {row["document_id"] for row in result["sources"]} == {"first", "second"}
        assert any(row["offset"] > 1000 for row in result["sources"])


def test_snapshots_survive_document_changes_deletion_restart_and_backup(tmp_path):
    root = tmp_path / "source"
    store = Store(root)
    doc = Library(store).add("План.txt", "Контрольный код 7351. Исходные данные.")
    prepared = selected_context("Какой код?", [Library(store).selected([doc["id"]])[0]], 500)
    message = store.add_message("assistant", "Код 7351", document_context=prepared["sources"])
    with store.db() as db:
        db.execute("UPDATE documents SET content='Другая редакция' WHERE id=?", (doc["id"],))
    Library(store).remove(doc["id"])
    assert Store(root).messages()[-1]["document_context"] == message["document_context"]
    archive = Backups(store).export()
    assert json.loads(archive)["version"] == 7
    target = Store(tmp_path / "target")
    backup = Backups(target)
    backup.restore(backup.preview(archive)["ticket"])
    assert target.messages()[-1]["document_context"] == prepared["sources"]
    assert target.list("documents") == []


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_preexisting_message_table_migrates_without_rewriting_history(tmp_path, role):
    tmp_path.mkdir(exist_ok=True)
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE messages (id TEXT PRIMARY KEY,role TEXT,content TEXT,created TEXT)")
        db.execute("INSERT INTO messages VALUES ('old',?,'Прежний текст','2026-10-17T10:00:00+00:00')", (role,))
    store = Store(tmp_path)
    message, = store.messages()
    assert message["content"] == "Прежний текст" and "document_context" not in message
    assert Store(tmp_path).messages() == [message]


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_old_backup_versions_default_to_empty_document_context(tmp_path, version):
    store = Store(tmp_path)
    store.add_message("assistant", "Ранее источники не сохранялись")
    raw = json.loads(Backups(store).export())
    raw["version"] = version
    for message in raw["data"]["messages"]:
        del message["document_context"]
    if version == 1:
        del raw["data"]["projects"]
        del raw["data"]["conversations"]
        for message in raw["data"]["messages"]:
            del message["conversation_id"]
    assert parse(encode(raw)).data.messages[0].document_context == []


@pytest.mark.parametrize("field,value", [("offset", -1), ("offset", True), ("total", 1), ("text", "x" * 1201), ("document_id", "../../file"), ("extra", "unknown")])
def test_invalid_snapshot_in_backup_is_rejected(tmp_path, field, value):
    store = Store(tmp_path)
    fragment = {"document_id": "source", "name": "Файл.txt", "offset": 0, "text": "Данные", "total": 6}
    store.add_message("assistant", "Ответ", document_context=[fragment])
    raw = json.loads(Backups(store).export())
    raw["data"]["messages"][0]["document_context"][0][field] = value
    with pytest.raises(ValueError, match="проверить копию"):
        parse(encode(raw))


def test_backup_snapshot_requires_current_version_and_assistant_role(tmp_path):
    store = Store(tmp_path)
    store.add_message("assistant", "Ответ", document_context=[{"document_id": "source", "name": "Файл.txt", "offset": 0, "text": "Данные", "total": 6}])
    raw = json.loads(Backups(store).export())
    raw["version"] = 6
    with pytest.raises(ValueError): parse(encode(raw))
    raw["version"] = 7
    raw["data"]["messages"][0]["role"] = "user"
    with pytest.raises(ValueError): parse(encode(raw))


@pytest.mark.parametrize("finish", ["normal", "limit", "broken"])
def test_api_saves_only_selected_visible_sources_and_not_as_future_memory(tmp_path, monkeypatch, finish):
    captured = []
    async def model(settings, messages):
        captured.append(messages)
        yield "Ответ по файлу."
        if finish == "limit": raise providers.ResponseLimitReached("Лимит")
        if finish == "broken": raise ValueError("fixture failure")
    monkeypatch.setattr(providers, "chat", model)
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        spaces = Spaces(store)
        project = spaces.create_project("Работа")
        first, second = spaces.create_chat(project["id"]), spaces.create_chat(project["id"])
        outsider = spaces.create_chat()
        selected = Library(store.for_chat(first["id"])).add("Общий.txt", "Уникальный отрывок СОВА-7351.", "project")
        private = Library(store.for_chat(first["id"])).add("Частный.txt", "ЛИЧНЫЙ-КОД-8420")
        response = api.post("/chat", json={"text": "Что в файле?", "conversation_id": second["id"], "document_ids": [selected["id"]]})
        events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]
        done, = [event["message"] for event in events if event["type"] == "done"]
        source, = done["document_context"]
        assert source["document_id"] == selected["id"] and source["text"] in captured[0][0]["content"]
        assert "ЛИЧНЫЙ-КОД-8420" not in str(done)
        assert api.get("/messages", params={"conversation_id": outsider["id"]}).json() == []
        assert "document_context" not in api.get("/messages", params={"conversation_id": second["id"]}).json()[0]
        assert api.post("/chat", json={"text": "Вопрос", "conversation_id": second["id"], "document_ids": [private["id"]]}).status_code == 400
        api.post("/chat", json={"text": "Поговорим о другом", "conversation_id": second["id"]})
        assert "Уникальный отрывок" not in str(captured[-1])
        assert "document_context" not in api.get("/messages", params={"conversation_id": second["id"]}).json()[-1]
        assert store.for_chat(second["id"]).memories() == []


def test_local_command_does_not_claim_it_read_an_attached_document(tmp_path):
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        store = app.state.store
        doc = Library(store).add("Файл.txt", "Данные документа")
        api.post("/chat", json={"text": "Запомни: предпочитаю короткие ответы", "document_ids": [doc["id"]]})
        assert "document_context" not in api.get("/messages").json()[-1]


def test_summary_evidence_keeps_its_purpose_after_source_deletion_and_backup_restore(tmp_path):
    store = Store(tmp_path / "original")
    doc = Library(store).add("Книга.txt", "Рейдж вернулся домой.")
    source = {"document_id": doc["id"], "name": doc["name"], "offset": 0,
              "text": "Рейдж вернулся домой.", "total": doc["characters"], "purpose": "summary_evidence"}
    store.add_message("assistant", "Рейдж вернулся домой. [1]", document_context=[source])
    Library(store).remove(doc["id"])
    backup = Backups(Store(tmp_path / "restored"))
    backup.restore(backup.preview(Backups(store).export())["ticket"])
    assert backup.store.messages()[-1]["document_context"] == [source]
