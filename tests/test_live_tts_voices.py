"""Uses already downloaded weights; never records or plays real audio."""
import io
import os
from pathlib import Path
import wave

import pytest

from core.voice import Voice


@pytest.fixture(scope="module")
def installed_voice():
    return Voice(Path(__file__).resolve().parents[1] / "data")


@pytest.mark.skipif(os.environ.get("WILEYAI_TTS_TESTS") != "1", reason="Requires downloaded Piper and Silero 5.6 weights")
@pytest.mark.parametrize("engine,speaker", [("piper", "irina"), ("piper", "denis"), ("piper", "dmitri"), ("silero_v5_6", "baya"), ("silero_v5_6", "xenia")])
def test_downloaded_voice_produces_audible_russian_wav(installed_voice, engine, speaker):
    import numpy as np
    data = installed_voice.synthesize("Привет! Я Уайли. Давай спокойно обсудим твои планы?", speaker, engine=engine)
    with wave.open(io.BytesIO(data), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert 1 < audio.getnframes() / audio.getframerate() < 30
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        assert np.max(np.abs(pcm.astype(np.int32))) > 1000


@pytest.mark.skipif(os.environ.get("WILEYAI_TTS_TESTS") != "1", reason="Requires downloaded Piper and Silero 5.6 weights")
@pytest.mark.parametrize("engine,speaker", [("silero_v5_6", "baya"), ("silero_v5_6", "xenia"), ("piper", "irina")])
def test_formatted_assistant_answer_can_be_spoken(installed_voice, engine, speaker):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from core.api import create_app
    from tempfile import TemporaryDirectory
    from core.storage import Store

    text = "Вот что я умею делать прямо сейчас:\n\n" + "\n".join([
        "* **Управление задачами:** Я могу создавать списки задач и помогать ничего не упускать.",
        "* **Работа с документами:** Я могу читать, анализировать и структурировать файлы.",
        "* **Календарь:** Я создаю встречи только по явной команде и показываю расписание.",
        "* **Память:** Я храню факты, которые ты мне сообщил. Что обсудим сейчас?",
    ])
    # This is longer than one TTS chunk and contains multi-word Markdown spans,
    # which used to trigger Silero's single-word emphasis parser.
    with TemporaryDirectory(prefix="wiley-tts-markdown-") as folder:
        root = Path(folder)
        with patch("core.api.Voice", return_value=installed_voice), patch("core.providers.get_key", return_value=""):
            token = "voice-markdown-test-0123456789abcdef"
            with TestClient(create_app(root, token), headers={"Authorization": "Bearer " + token}) as api:
                message = Store(root).add_message("assistant", text)
                result = api.post("/voice/synthesize", json={"text": text, "engine": engine, "voice": speaker})
                assert result.status_code == 200, result.text[:300] if result.status_code != 200 else ""
                with wave.open(io.BytesIO(result.content), "rb") as audio:
                    assert 5 < audio.getnframes() / audio.getframerate() < 120
                # Speech preparation must not rewrite the displayed or stored answer.
                assert any(item["id"] == message["id"] and item["content"] == text for item in api.get("/messages").json())
