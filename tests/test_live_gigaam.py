"""Opt-in real GigaAM test; synthesizes fixtures, never opens a microphone/speaker."""
import asyncio
import io
import json
import os
from pathlib import Path
import time
import wave

import pytest

from core import gigaam
from core.device_audio import AudioAction, resolve
from core.voice import Voice


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_GIGAAM") != "1", reason="Requires GigaAM v3 and Piper irina weights")
def test_russian_commands_webm_silence_long_turn_and_switch_back():
    import av
    import numpy as np
    root = Path(__file__).resolve().parents[1] / "data"
    voice = Voice(root)
    results = []
    phrases = [
        ("Прибавь громкость на десять.", AudioAction(action="change_volume", value=10)),
        ("Убавь громкость на двадцать процентов.", AudioAction(action="change_volume", value=-20)),
        ("Поставь музыку на паузу.", AudioAction(action="pause")),
    ]
    audio = None
    for phrase, action in phrases:
        audio = voice.synthesize(phrase, "irina", engine="piper")
        started = time.perf_counter()
        text = voice.transcribe(audio, gigaam.MODEL_ID)
        results.append({"phrase": phrase, "text": text, "seconds": round(time.perf_counter() - started, 3)})
        assert resolve(text) == action, results

    samples = gigaam.decode_audio(audio)
    out = io.BytesIO()
    with av.open(out, "w", format="webm") as container:
        stream = container.add_stream("libopus", rate=16000)
        frame = av.AudioFrame.from_ndarray(samples[None, :], format="fltp", layout="mono")
        frame.sample_rate = 16000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    assert resolve(voice.transcribe(out.getvalue(), gigaam.MODEL_ID)) == phrases[-1][1]
    silence = io.BytesIO()
    with wave.open(silence, "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b"\0" * 64000)
    assert voice.transcribe(silence.getvalue(), gigaam.MODEL_ID) == ""

    # A >25-second manual/continuous turn must retain the last phrase.
    long_turn = np.concatenate([np.concatenate([samples, np.zeros(16000, np.float32)]) for _ in range(12)])
    assert len(long_turn) / 16000 > 25
    model = voice.models[gigaam.MODEL_ID]
    text = model.transcribe(b"", long_turn)
    assert text.casefold().count("пауз") == 12, text
    # Same process switches between both recognizers and releases the old one.
    assert resolve(voice.transcribe(audio, "small")) == phrases[-1][1]
    assert list(voice.models) == ["small"]
    assert resolve(voice.transcribe(audio, gigaam.MODEL_ID)) == phrases[-1][1]
    assert asyncio.run(voice.unload()) == [gigaam.MODEL_NAME, "Piper"]
    print(json.dumps(results, ensure_ascii=False))
