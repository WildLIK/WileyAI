"""Optional real model check; synthesizes files without touching microphones or speakers."""
import io
import json
import os
from pathlib import Path
import time
import wave

import pytest

from core.device_audio import AudioAction, resolve
from core.voice import Voice


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_RECOGNITION") != "1", reason="Requires installed Whisper small and Piper irina")
def test_russian_voice_commands_and_silence_with_real_models():
    voice = Voice(Path(__file__).resolve().parents[1] / "data")
    results = []
    for phrase, expected in [
        ("Прибавь громкость на десять.", AudioAction(action="change_volume", value=10)),
        ("Убавь громкость на двадцать процентов.", AudioAction(action="change_volume", value=-20)),
        ("Можешь прибавить громкость на пять процентов?", AudioAction(action="change_volume", value=5)),
    ]:
        audio = voice.synthesize(phrase, "irina", engine="piper")
        started = time.perf_counter()
        text = voice.transcribe(audio, "small", "Уайли", "accurate")
        results.append({"phrase": phrase, "recognized": text, "seconds": round(time.perf_counter() - started, 2)})
        assert resolve(text) == expected, results
    silence = io.BytesIO()
    with wave.open(silence, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0" * 64000)
    assert voice.transcribe(silence.getvalue(), "small", "Уайли", "accurate") == ""
    print(json.dumps(results, ensure_ascii=False))
