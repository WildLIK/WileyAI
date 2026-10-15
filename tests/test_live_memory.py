"""Optional installed-model check; isolated user data, no downloads or audio."""
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.storage import Store


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TESTS") != "1", reason="Requires local Ollama qwen3.5:4b")
def test_local_model_uses_retrieved_old_memory_with_context_reference(tmp_path):
    store = Store(tmp_path)
    target = store.add_memory("Контрольный код проекта Лиственница — СОКОЛ-73")
    for number in range(110):
        store.add_memory(f"Несвязанная запись о тестовом справочнике номер {number}")
    assert target["id"] not in {item["id"] for item in store.memories(limit=100)}
    token = "live-memory-test-0123456789abcdef"
    with patch("core.providers.get_key", return_value=""):
        with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
            response = api.post("/chat", json={"text": "Какой контрольный код проекта Лиственница сохранён в памяти? Ответь только кодом."})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert not any(item["type"] == "error" for item in events), events
            answer = next(item["message"] for item in events if item["type"] == "done")
            assert "СОКОЛ-73" in answer["content"], answer
            assert target["id"] in {item["id"] for item in answer["memory_context"]}
            assert target["id"] in {item["id"] for item in api.get("/messages").json()[-1]["memory_context"]}
