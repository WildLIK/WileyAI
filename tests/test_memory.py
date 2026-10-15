from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core import providers
from core.memory import suggestions
from core.storage import Store


@pytest.mark.parametrize("text,category", [
    ("Я предпочитаю краткие ответы.", "preference"),
    ("Мне удобнее примеры на Python", "preference"),
    ("Я не люблю длинные списки", "preference"),
    ("Я работаю над проектом WileyAI", "profile"),
    ("Мой проект называется Альтаир", "profile"),
])
def test_local_direct_statement_suggestions(text, category):
    item, = suggestions(text)
    assert item["content"] == text.rstrip(".") and item["category"] == category


@pytest.mark.parametrize("text", [
    "Он предпочитает краткие ответы", "Мне нравится Python?", "Если бы я работал программистом",
    'Я люблю фразу «открой браузер»', "Пример: я предпочитаю короткие ответы", "Я предпочитаю, допустим, Python",
    "Я работаю с API-key SECRET", "Я предпочитаю пароль secret", "Я предпочитаю `shell`", "Создай заметку: я люблю Python",
])
def test_examples_questions_credentials_and_other_people_are_not_proposed(text):
    assert suggestions(text) == []


def candidate(store, text="Я предпочитаю короткие ответы"):
    source = store.add_message("user", text)
    item, = store.suggest_memories(source["id"])
    return item, source


def test_unconfirmed_facts_are_separate_and_source_must_be_user(tmp_path):
    store = Store(tmp_path)
    item, source = candidate(store)
    assert item["source_message_id"] == source["id"]
    assert item["source_text"] == source["content"]
    assert store.memories() == [] and store.memory_context("Какие ответы мне нравятся?") == []
    other = store.add_message("assistant", "Я предпочитаю Java")
    assert store.suggest_memories(other["id"]) == []
    assert len(Store(tmp_path).memory_candidates()) == 1


def test_dismissal_suppresses_repeated_suggestions_and_discards_draft_text(tmp_path):
    store = Store(tmp_path)
    item, _ = candidate(store)
    store.dismiss_memory(item["id"])
    assert store.memory_candidates() == []
    again = store.add_message("user", "я предпочитаю короткие ответы.")
    assert store.suggest_memories(again["id"]) == []
    with store.db() as db:
        saved = dict(db.execute("SELECT * FROM memory_candidates").fetchone())
    assert saved["content"] == "" and len(saved["fingerprint"]) == 64
    with pytest.raises(ValueError):
        store.accept_memory(item["id"], item["content"], None)


def test_acceptance_is_atomic_idempotent_and_can_edit_the_proposal(tmp_path):
    store = Store(tmp_path)
    item, source = candidate(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(lambda _: store.accept_memory(item["id"], "Я предпочитаю короткие ответы с примерами", "preference"), range(2)))
    assert accepted[0]["id"] == accepted[1]["id"]
    fact, = store.memories()
    assert fact["source_text"] == source["content"]
    assert "с примерами" in fact["content"]
    assert store.memory_candidates() == []
    assert len(store.memory_context("Примеры ответа")) == 1


def test_replace_preserves_identity_and_pin_with_new_source(tmp_path):
    store = Store(tmp_path)
    old = store.add_memory("Я предпочитаю краткие ответы", pinned=True)
    item, source = candidate(store, "Я предпочитаю подробные ответы")
    new = store.accept_memory(item["id"], item["content"], None, replace_id=old["id"])
    assert new["id"] == old["id"] and new["pinned"] == 1
    assert new["source_message_id"] == source["id"] and new["revision"] > old["revision"]
    assert len(store.memories()) == 1


def test_deleted_replacement_cannot_be_resurrected(tmp_path):
    store = Store(tmp_path)
    old = store.add_memory("Краткие ответы")
    item, _ = candidate(store)
    store.remove("memories", old["id"])
    with pytest.raises(ValueError, match="удалена"):
        store.accept_memory(item["id"], item["content"], None, replace_id=old["id"])
    assert store.memories() == [] and len(store.memory_candidates()) == 1


def test_memory_deduplication_and_rejected_automatic_fact_can_be_saved_explicitly(tmp_path):
    store = Store(tmp_path)
    item, _ = candidate(store)
    store.dismiss_memory(item["id"])
    first = store.add_memory(item["content"])
    second = store.add_memory(item["content"].lower() + ".")
    assert first["id"] == second["id"] and len(store.memories()) == 1


def test_full_text_search_finds_older_records_and_handles_russian_and_query_syntax(tmp_path):
    store = Store(tmp_path)
    target = store.add_memory("Проект Альтаир использует Python")
    for index in range(110):
        store.add_memory(f"Несвязанная запись номер {index}")
    assert store.memories("Альтаир")[0]["id"] == target["id"]
    assert target["id"] in [item["id"] for item in store.memory_context("Помоги с проектом Альтаир")]
    assert isinstance(store.memories('" OR * DROP TABLE memories; --'), list)
    store.add_memory("Работаю с приёмом данных")
    assert store.memories("прием")[0]["content"] == "Работаю с приёмом данных"


def test_context_is_bounded_and_deduplicated_even_with_pinned_matches(tmp_path):
    store = Store(tmp_path)
    first = store.add_memory("Я предпочитаю Python", pinned=True)
    for index in range(20):
        store.add_memory("Python проект " + str(index) + " описание" * 15)
    items = store.memory_context("Python", budget=800)
    assert items[0]["id"] == first["id"]
    assert len({item["id"] for item in items}) == len(items)
    payload = [{"id": item["id"], "content": item["content"], "category": item["category"]} for item in items]
    assert len(json.dumps(payload, ensure_ascii=False)) <= 800


def test_legacy_memory_migration_preserves_data_and_is_repeatable(tmp_path):
    with sqlite3.connect(tmp_path / "wileyai.db") as db:
        db.execute("CREATE TABLE memories (id TEXT PRIMARY KEY,content TEXT NOT NULL,created TEXT NOT NULL)")
        db.execute("INSERT INTO memories VALUES ('legacy','Я предпочитаю Python','2026-10-01T10:00:00+00:00')")
    first = Store(tmp_path).memories()[0]
    second = Store(tmp_path).memories("Python")[0]
    assert first == second and first["id"] == "legacy" and first["category"] == "preference"
    assert first["created"] == "2026-10-01T10:00:00+00:00"


def test_message_context_is_versioned_and_forgetting_removes_search_and_links(tmp_path):
    store = Store(tmp_path)
    fact = store.add_memory("Python предпочитаю")
    reply = store.add_message("assistant", "Ответ", [fact])
    assert reply["memory_context"][0]["id"] == fact["id"]
    pinned = store.edit_memory(fact["id"], fact["content"], "fact", True)
    assert pinned["revision"] == fact["revision"]
    assert len(store.messages()[0]["memory_context"]) == 1
    store.edit_memory(fact["id"], "Теперь Java", "preference", True)
    assert store.messages()[0]["memory_context"] == []
    assert store.memories("Python") == []
    store.remove("memories", fact["id"])
    assert store.memories("Java") == []
    assert store.messages()[0]["memory_context"] == []


def test_api_proposals_are_not_context_until_accepted_and_can_be_disabled(tmp_path, monkeypatch):
    captures = []
    async def fake_chat(settings, messages):
        captures.append(messages)
        yield "Давай обсудим."
    monkeypatch.setattr(providers, "chat", fake_chat)
    monkeypatch.setattr(providers, "get_key", lambda settings: "")
    token = "memory-test-token-0123456789abcdef"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        api.post("/chat", json={"text": "Я предпочитаю короткие ответы"})
        item, = api.get("/memory-candidates").json()
        assert api.get("/memories").json() == []
        assert api.get("/messages").json()[-1]["memory_context"] == []
        accepted = api.post("/memory-candidates/" + item["id"] + "/accept", json={"text": "Я предпочитаю короткие ответы с примерами"}).json()
        assert accepted["category"] == "preference"
        api.post("/chat", json={"text": "Как лучше отвечать?"})
        assert "короткие ответы с примерами" in captures[-1][0]["content"]
        assert api.get("/messages").json()[-1]["memory_context"][0]["id"] == accepted["id"]
        config = api.get("/settings").json()
        config["memory_suggestions"] = False
        api.put("/settings", json=config)
        api.post("/chat", json={"text": "Мне удобнее примеры на Java"})
        assert api.get("/memory-candidates").json() == []
        assert api.put("/memories/" + accepted["id"], json={"text": "   "}).status_code == 400
        api.delete("/memories/" + accepted["id"])
        assert api.get("/messages").json()[-3]["memory_context"] == []
