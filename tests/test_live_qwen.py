"""Opt-in isolated Qwen runtime checks. No microphone or physical speaker use."""
import asyncio
import io
import json
import os
from pathlib import Path
import time
import wave

import pytest

from core.voice import Voice


pytestmark = pytest.mark.skipif(os.environ.get("WILEYAI_QWEN_TESTS") != "1", reason="Requires isolated Qwen runtime and downloaded weights")


def test_qwen_russian_voice_and_owned_process_cleanup():
    async def scenario():
        root = Path(__file__).resolve().parents[1]
        voice = Voice(root / "data")
        start = time.monotonic()
        device = os.environ.get("WILEYAI_QWEN_DEVICE", "cpu")
        audio = await voice.render("Привет! Я рядом. Давай спокойно обсудим твои планы.", "serena", "qwen3", "live-sample", device=device)
        elapsed = time.monotonic() - start
        with wave.open(io.BytesIO(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
            assert 1 < duration < 30
        assert not voice.qwen.processes and not voice.synthesis_jobs
        samples = root / "local" / "voice-samples"
        samples.mkdir(parents=True, exist_ok=True)
        (samples / "qwen3-serena.wav").write_bytes(audio)
        (samples / "qwen3-serena.json").write_text(json.dumps({"device": device, "elapsed": elapsed, "duration": duration}, indent=2), encoding="utf-8")
    asyncio.run(scenario())


def test_qwen_can_be_killed_while_loading_without_leaving_a_worker():
    async def scenario():
        voice = Voice(Path(__file__).resolve().parents[1] / "data")
        task = asyncio.create_task(voice.render("Привет! Как твои дела?", "serena", "qwen3", "cancel-loading", device="cpu"))
        for _ in range(100):
            if voice.qwen.processes: break
            await asyncio.sleep(0.05)
        assert voice.qwen.processes
        process = voice.qwen.processes["cancel-loading"]
        await voice.stop("cancel-loading")
        with pytest.raises(ValueError, match="остановлена"):
            await task
        assert process.returncode is not None
        assert not voice.qwen.processes and not voice.synthesis_jobs
    asyncio.run(scenario())


def test_qwen_sentence_session_reuses_real_model_and_frees_memory():
    async def scenario():
        root = Path(__file__).resolve().parents[1]
        voice = Voice(root / "data")
        device = os.environ.get("WILEYAI_QWEN_DEVICE", "cpu")
        session = "live-sentence-session"
        processes, timings = [], []
        try:
            for index, text in enumerate(["Привет!", "Рада тебя слышать."]):
                start = time.monotonic()
                audio = await voice.render(text, "serena", "qwen3", f"sentence-{index}", device=device, session_id=session)
                timings.append(time.monotonic() - start)
                with wave.open(io.BytesIO(audio), "rb") as wav:
                    assert wav.getnframes() > 1000 and wav.getnchannels() == 1
                processes.append(voice.qwen.sessions[session].process)
                assert audio.device in {"cpu", "cuda"}
            assert processes[0] is processes[1] and processes[0].returncode is None
            assert not voice.synthesis_jobs and not voice.qwen.processes
            print("Qwen sentence timings:", timings)
        finally:
            await voice.stop()
        assert processes[0].returncode is not None and not voice.qwen.sessions
    asyncio.run(scenario())
