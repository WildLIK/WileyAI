"""Optional installed-model command selection; Windows dispatch is replaced."""
import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.config import Settings
from core.storage import Store


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TESTS") != "1", reason="Requires local Ollama qwen3.5:4b")
def test_local_model_selects_catalog_id_and_waits_for_voice_confirmation(tmp_path):
    store = Store(tmp_path)
    store.save_settings(Settings(command_understanding=True))
    target = tmp_path / "notes.exe"
    target.write_text("test placeholder, never executed")
    store.add_alias("текстовые заметки", "app", str(target))
    opened = []
    token = "live-intents-0123456789abcdef"
    def message(response):
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not any(item["type"] == "error" for item in events), events
        return next(item["message"] for item in events if item["type"] == "done")
    with patch("core.providers.get_key", return_value=""), patch("core.commands.execute", side_effect=lambda command, dry_run=False: opened.append(command) or "Передано Windows"):
        with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
            answer = message(api.post("/chat", json={"text": "Можешь запустить программу Текстовые заметки?", "mode": "conversation"}))
            assert "текстовые заметки" in answer["content"] and opened == [], answer
            pending = store.dialogue()["pending_open"]
            index = next(index for index, item in enumerate(pending["choices"], 1) if item["target"] == str(target))
            message(api.post("/chat", json={"text": str(index), "mode": "conversation"}))
            assert len(opened) == 1 and opened[0].target == str(target)
