import asyncio
import json

import httpx
import pytest

from core.config import Settings
from core.semantic import SemanticIndex, vector
from core.storage import Store
from core.document_library import Library


def setup(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save_settings(Settings(embedding_enabled=True))
    index = SemanticIndex(store)
    calls = []
    real = httpx.AsyncClient
    weights = ["weights-1"]
    def handler(req):
        calls.append(req)
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "embeddinggemma:300m", "digest": weights[0]}]})
        body = json.loads(req.content)
        assert body["truncate"] is False
        def embed(text):
            return [1, 0, .01] if any(word in text for word in ("автомобиль", "машина", "колёса")) else [0, 1, .01]
        return httpx.Response(200, json={"embeddings": [embed(text) for text in body["input"]]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(handler)))
    return store, index, calls, weights


def test_synonyms_sources_and_lexical_fallback(tmp_path, monkeypatch):
    store, index, calls, _ = setup(tmp_path, monkeypatch)
    original = store.add_message("user", "Мой автомобиль красный")
    memory = store.add_memory("Мой автомобиль красный", source_message_id=original["id"])
    Library(store).add("Транспорт", "Автомобиль: четыре колёса и двигатель")
    Library(store).add("Сад", "Цветы растут в саду")
    async def scenario():
        found, notice = await index.search(store, "машина", "memory")
        assert found is None and "обновления" in notice
        await index.rebuild(store)
        assert index.job["state"] == "done"
        found, notice = await index.search(store, "машина", "memory")
        assert len(found) == 1 and found[0]["id"] == memory["id"] and not notice
        assert found[0]["item"]["source_text"] == original["content"]
        docs, _ = await index.search(store, "машина", "document")
        assert len(docs) == 1 and docs[0]["item"]["name"] == "Транспорт" and docs[0]["offset"] == 0
    asyncio.run(scenario())
    assert store.memories("машина") == []  # This really differs from lexical search.
    assert all(req.url.host == "127.0.0.1" for req in calls)
    assert "Мой автомобиль".encode() not in index.path.read_bytes()


def test_scopes_edits_deletes_model_switch_and_cache_restart(tmp_path, monkeypatch):
    store, index, _, weights = setup(tmp_path, monkeypatch)
    a = store.add_memory("Мой автомобиль красный")
    doc = Library(store).add("Транспорт", "Мой автомобиль красный")
    # A second general chat shares confirmed memory, but not chat files.
    from core.chatspaces import Spaces
    spaces = Spaces(store)
    other_chat = spaces.create_chat(title="Другой")
    other = store.for_chat(other_chat["id"])
    async def scenario():
        await index.rebuild(store)
        reopened = SemanticIndex(store)
        assert reopened.status(store)["complete"]
        docs, _ = await reopened.search(other, "машина", "document")
        assert docs == []
        store.edit_memory(a["id"], "Цветы в саду", "fact", False)
        found, notice = await index.search(store, "машина", "memory")
        assert found is None and notice
        await index.rebuild(store)
        found, _ = await index.search(store, "машина", "memory")
        assert found == []
        Library(store).remove(doc["id"])
        found, _ = await index.search(store, "машина", "document")
        assert found == []
        weights[0] = "weights-2"
        found, notice = await index.search(store, "цветы", "memory")
        assert found is None and notice
        await index.rebuild(store)
        assert index.status(store)["complete"]
    asyncio.run(scenario())


def test_source_changed_during_query_is_not_returned(tmp_path, monkeypatch):
    store, index, _, _ = setup(tmp_path, monkeypatch)
    memory = store.add_memory("Мой автомобиль красный")
    async def scenario():
        await index.rebuild(store)
        real = index.embed
        async def changed(settings, texts):
            result = await real(settings, texts)
            store.remove("memories", memory["id"])
            return result
        monkeypatch.setattr(index, "embed", changed)
        found, _ = await index.search(store, "машина", "memory")
        assert found == []
    asyncio.run(scenario())


def test_cache_is_compact_and_bounded_without_evicting_current_sources(tmp_path, monkeypatch):
    store, index, _, _ = setup(tmp_path, monkeypatch)
    import core.semantic as module
    monkeypatch.setattr(module, "MAX_CACHE", 3)
    store.add_memory("Мой автомобиль красный")
    async def scenario():
        await index.rebuild(store)
        with index.db() as db:
            key = db.execute("SELECT model FROM meta").fetchone()[0]
            db.executemany("INSERT INTO vectors VALUES (?,?,?)", [(key, str(i), "[0,1,0]") for i in range(3)])
        store.add_memory("Цветы в саду")
        await index.rebuild(store)
        assert index.job["state"] == "done" and index.status(store)["complete"]
        with index.db() as db:
            assert db.execute("SELECT count(*) FROM vectors").fetchone()[0] == 3
            assert db.execute("SELECT count(*) FROM vectors WHERE typeof(value)='blob'").fetchone()[0] == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("value", [[], [0, 0], [float("nan"), 1], [float("inf"), 1], [True, 2], [1] * 4097])
def test_invalid_vectors_fail_closed(value):
    with pytest.raises(ValueError): vector(value)


@pytest.mark.parametrize("endpoint", ["https://example.org", "http://192.168.1.1", "http://127.0.0.1/path"])
def test_embeddings_cannot_silently_send_private_corpus_to_remote_host(endpoint):
    with pytest.raises(ValueError): Settings(embedding_base_url=endpoint)
