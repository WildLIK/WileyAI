"""Optional model integration test. Never records or plays the physical microphone/speakers."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.voice import Voice


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TESTS") != "1", reason="Requires installed Whisper small, Silero and local Ollama qwen3.5:4b")
def test_local_voice_conversation_pipeline(tmp_path):
    models_root = Path(__file__).resolve().parents[1] / "data"
    voice = Voice(models_root)
    headers = {"Authorization": "Bearer live-voice-test-0123456789abcdef"}
    # Only the model cache is shared. History, settings and commands stay in a temporary directory.
    with patch("core.api.Voice", return_value=voice), patch("core.providers.get_key", return_value=""):
        with TestClient(create_app(tmp_path, "live-voice-test-0123456789abcdef"), headers=headers) as api:
            prepared = api.post("/voice/prepare")
            assert prepared.status_code == 200, prepared.text
            speech = api.post("/voice/synthesize", json={"text": "Привет. Давай поговорим о космосе."})
            assert speech.status_code == 200, speech.text[:200]
            recognized = api.post("/voice/transcribe", files={"file": ("input.wav", speech.content, "audio/wav")})
            assert recognized.status_code == 200, recognized.text
            text = recognized.json()["text"]
            assert "космос" in text.casefold(), text
            response = api.post("/chat", json={"text": text, "mode": "conversation"})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert not any(event["type"] == "error" for event in events), events
            answer = next(event["message"]["content"] for event in events if event["type"] == "done")
            assert len(answer.strip()) > 5
            spoken = api.post("/voice/synthesize", json={"text": answer})
            assert spoken.status_code == 200, spoken.text[:200]
            assert spoken.content.startswith(b"RIFF") and len(spoken.content) > 10000
            assert len(api.get("/messages").json()) == 2
