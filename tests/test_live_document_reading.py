"""Optional real-model regression for free-form document reading; temporary data only."""
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core import providers, document_summary
from core.api import create_app
from core.config import Settings
from core.document_library import Library
from core.storage import Store


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TESTS") != "1", reason="Requires local Ollama qwen3.5:4b")
def test_qwen_reads_all_parts_after_natural_read_request(tmp_path):
    store = Store(tmp_path)
    store.save_settings(Settings(base_url=os.environ.get("WILEYAI_LIVE_DOCUMENT_URL", "http://127.0.0.1:11434"), temperature=0))
    content = ("Глава 1. Рейдж обнаружил пропажу книги из городской библиотеки.\n" +
               "В пути Рейдж опрашивал свидетелей, сравнивал показания и искал следы похитителя.\n" * 120 +
               "Финал. Рейдж нашёл книгу у старого моста и вернул её в библиотеку. После этого он уехал на север.")
    doc = Library(store).add("Проверка.txt", content)
    store.add_message("user", "Мне нужен краткий пересказ от начала до конца")
    store.add_message("assistant", "Ранее были доступны только отдельные отрывки.")
    real_chat, requests = providers.chat, []
    async def observed(settings, messages, output_schema=None):
        requests.append((messages, output_schema))
        async for delta in real_chat(settings, messages, output_schema=output_schema):
            yield delta
    token = "live-document-reading-0123456789"
    with patch("core.providers.get_key", return_value=""), patch("core.providers.chat", observed):
        with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
            response = api.post("/chat", json={"text": "прочитай", "document_ids": [doc["id"]]})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert not any(item["type"] == "error" for item in events), events
            answer = next(item["message"] for item in events if item["type"] == "done")
            assert "обработан весь извлечённый текст" in answer["content"], answer
            assert '"mode"' not in answer["content"] and "wiley_document_action" not in answer["content"]
            assert requests[0][1] == document_summary.MODE_SCHEMA
            chunks = [messages[1]["content"].split("\n", 1)[1] for messages, _ in requests if messages[0]["content"] == document_summary.READ_PROMPT]
            assert len(chunks) >= 2 and "".join(chunks) == content
            assert any(item.get("phase") == "reading" for item in events)
            assert "document_context" not in answer
