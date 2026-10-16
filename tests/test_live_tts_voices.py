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
