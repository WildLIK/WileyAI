from datetime import datetime, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.backups import Backups
from core.chatspaces import Spaces
from core.history import History
from core.storage import Store

TOKEN = "history-search-token-0123456789"


def setup(root):
    store = Store(root)
    spaces = Spaces(store)
    project = spaces.create_project("Работа")
    first = spaces.create_chat(project["id"], "Первый")
    second = spaces.create_chat(project["id"], "Второй")
    common = spaces.create_chat(title="Общий")
    return store, spaces, project, first, second, common


def test_search_scopes_roles_prefixes_and_explicit_all(tmp_path):
    store, _, project, first, second, common = setup(tmp_path)
    own = store.for_chat(first["id"]).add_message("user", "Обсудим архитектуру и поведение ёжика")
    peer = store.for_chat(second["id"]).add_message("assistant", "Архитектура системы для ежика готова")
    outside = store.for_chat(common["id"]).add_message("user", "Архитектура проекта ЕЖИКА")
    history = History(store.for_chat(first["id"]))
    result = history.search("архитектура ежика")
    assert {item["id"] for item in result["items"]} == {own["id"], peer["id"]}
    assert result["terms"] == ["архите", "ежика"]
    assert all(item["project_name"] == "Работа" and item["project_id"] == project["id"] for item in result["items"])
    assert history.search("архитектура ежика", "chat")["items"][0]["id"] == own["id"]
    assert history.search("архитектура ежика", role="assistant")["items"][0]["id"] == peer["id"]
    assert history.search("архитектура ежика", "all")["total"] == 3
    assert History(store.for_chat(common["id"])).search("архитектура")["items"][0]["id"] == outside["id"]


def test_pagination_numeric_codes_escaping_and_preview_bound(tmp_path):
    store = Store(tmp_path)
    for index in range(47):
        store.add_message("user", ("Нейтральные слова " * 200) + f"Номер СОКОЛ-7351 вариант {index}")
    history = History(store)
    pages = [history.search("7351", offset=offset) for offset in [0, 20, 40]]
    assert [len(page["items"]) for page in pages] == [20, 20, 7]
    assert len({row["id"] for page in pages for row in page["items"]}) == 47
    assert all("7351" in row["preview"] and len(row["preview"]) <= 600 for page in pages for row in page["items"])
    assert history.search('"7351" OR \"missing\"')["total"] == 0
    assert history.search("***")["total"] == 0
    with pytest.raises(ValueError): history.search(" ".join("слово" + str(i) for i in range(13)))
    with pytest.raises(ValueError): history.search("код", scope="unknown")


def test_index_updates_deletes_moves_and_restores_without_stale_hits(tmp_path):
    store, spaces, _, first, _, common = setup(tmp_path / "source")
    chat = store.for_chat(first["id"])
    message = chat.add_message("assistant", "Проверка ФЕНИКС")
    with store.db() as db:
        db.execute("UPDATE messages SET content='Проверка СОКОЛ' WHERE id=?", (message["id"],))
    assert History(chat).search("ФЕНИКС")["total"] == 0
    assert History(chat).search("СОКОЛ")["total"] == 1
    spaces.update_chat(first["id"], "Переименованный", None)
    with pytest.raises(ValueError, match="перемещён"): History(chat).search("СОКОЛ")
    assert History(store.for_chat(common["id"])).search("СОКОЛ")["items"][0]["title"] == "Переименованный"
    target = Store(tmp_path / "target")
    target.add_message("user", "НЕНУЖНЫЙ код до импорта")
    backup = Backups(target)
    backup.restore(backup.preview(Backups(store).export())["ticket"])
    assert History(target.for_chat(first["id"])).search("СОКОЛ")["total"] == 1
    assert History(target.for_chat(first["id"])).search("НЕНУЖНЫЙ", "all")["total"] == 0
    assert "message_search" not in json.loads(Backups(target).export())["data"]
    Spaces(target).delete_chat(first["id"])
    assert History(target.for_chat(common["id"])).search("СОКОЛ", "all")["total"] == 0


def test_old_history_is_indexed_once_without_rewriting_it(tmp_path):
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE messages(id TEXT PRIMARY KEY,role TEXT,content TEXT,created TEXT)")
        db.execute("INSERT INTO messages VALUES ('old','assistant','Прежнее решение ТАЙФУН','2026-10-17T10:00:00+00:00')")
    store = Store(tmp_path)
    before = store.messages()
    assert History(store).search("ТАЙФУН")["items"][0]["id"] == "old"
    again = Store(tmp_path)
    assert again.messages() == before
    assert History(again).search("ТАЙФУН")["total"] == 1


def test_message_window_uses_stable_order_and_preserves_document_memory_and_web_refs(tmp_path):
    store = Store(tmp_path)
    user = store.add_message("user", "Начало")
    memory = store.add_memory("Важный факт")
    source = {"document_id": "doc", "name": "План.txt", "offset": 0, "text": "Текст", "total": 5}
    web = {"query": "пример", "provider": "searxng", "checked_at": datetime.now(timezone.utc).isoformat(), "results": [], "partial": False}
    target = store.add_message("assistant", "СОКОЛ-7351", [memory], web, [source])
    for index in range(400): store.add_message("user", "Реплика " + str(index))
    with store.db() as db:
        db.execute("UPDATE messages SET created='2026-10-17T10:00:00+00:00'")
    window = store.messages(around=target["id"])
    assert len(window) == 42 and [row["id"] for row in window[:2]] == [user["id"], target["id"]]
    assert window[1]["document_context"] == [source]
    assert window[1]["memory_context"][0]["id"] == memory["id"]
    assert window[1]["web_search"]["query"] == "пример"
    assert all(row["id"] != target["id"] for row in store.messages())
    middle = store.list("messages", 402)[200]
    assert len(store.messages(around=middle["id"])) == 81
    other = Spaces(store).create_chat()
    with pytest.raises(ValueError, match="недоступно"): store.for_chat(other["id"]).messages(around=target["id"])


def test_api_validates_scope_and_does_not_call_models_or_change_data(tmp_path, monkeypatch):
    from core import providers
    monkeypatch.setattr(providers, "chat", lambda *args: pytest.fail("Search must not call a model"))
    app = create_app(tmp_path, TOKEN)
    with TestClient(app) as api:
        assert api.get("/history/search?q=код").status_code == 401
        api.headers["Authorization"] = "Bearer " + TOKEN
        store = app.state.store
        message = store.add_message("user", "Контрольный код 7351")
        original = api.get("/messages").json()
        result = api.get("/history/search", params={"q": "7351"})
        assert result.status_code == 200 and result.json()["items"][0]["id"] == message["id"]
        for params in [{"q": "x"}, {"q": "x" * 201}, {"q": "код", "scope": "unknown"}, {"q": "код", "offset": -1}, {"q": "код", "role": "bad"}]:
            assert api.get("/history/search", params=params).status_code == 422
        assert api.get("/messages", params={"around": "../../secret"}).status_code == 422
        assert api.get("/messages", params={"around": "missing"}).status_code == 400
        assert api.get("/messages").json() == original
