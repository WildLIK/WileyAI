"""Opt-in real TTS footprint check; isolated settings, shared read-only weights."""
import asyncio
import os
import io
import wave
from pathlib import Path
import time

import pytest

from core.monitor import Monitor
from core.storage import Store
from core.voice import Voice


@pytest.mark.skipif(os.environ.get("WILEYAI_QWEN_TESTS") != "1", reason="Requires installed Qwen runtime and weights")
def test_real_qwen_memory_is_in_model_row_during_work_and_idle(tmp_path):
    async def scenario():
        voice = Voice(tmp_path)
        voice.qwen.root = Path(__file__).resolve().parents[1] / "data/models/qwen3-tts"
        monitor = Monitor(Store(tmp_path), voice)
        async def render():
            with monitor.activity("tts:qwen3"):
                return await voice.render("Привет! Рада тебя слышать.", "serena", "qwen3", "monitor-live", device="cpu", session_id="monitor-live-session")
        task = asyncio.create_task(render())
        peak, measured_cpu = 0, []
        start = time.monotonic()
        try:
            while not task.done():
                snapshot = await asyncio.to_thread(monitor.sample)
                row = next((row for row in snapshot["rows"] if row["id"] == "tts:qwen3"), None)
                if row:
                    peak = max(peak, row["ram"] or 0)
                    if row["cpu"] is not None:
                        measured_cpu.append(row["cpu"])
                await asyncio.wait({task}, timeout=.5)
            assert (await task).startswith(b"RIFF")
            warm = await asyncio.to_thread(monitor.sample)
            row = next(row for row in warm["rows"] if row["id"] == "tts:qwen3")
            assert peak > 700 * 1024**2 and row["ram"] > 700 * 1024**2
            assert row["state"] == "Простой" and not row["active"]
            assert measured_cpu and max(measured_cpu) > 0
            print({"seconds": round(time.monotonic() - start, 2), "peak_ram_mib": round(peak / 1024**2),
                   "warm_ram_mib": round(row["ram"] / 1024**2), "max_cpu_percent": round(max(measured_cpu), 2), "pids": row["pids"]})
        finally:
            await voice.stop()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        snapshot = await asyncio.to_thread(monitor.sample)
        row = next(row for row in snapshot["rows"] if row["id"] == "tts:qwen3")
        assert row["ram"] is None and not row["pids"]
    asyncio.run(scenario())


@pytest.mark.skipif(os.environ.get("WILEYAI_QWEN_TESTS") != "1", reason="Requires installed Qwen runtime and weights")
def test_qwen_speech_duration_against_synthesis_time(tmp_path):
    async def scenario():
        voice = Voice(tmp_path)
        voice.qwen.root = Path(__file__).resolve().parents[1] / "data/models/qwen3-tts"
        rows = []
        try:
            for index, text in enumerate(["Привет!", "Рада тебя слышать.", "Рада тебя слышать. Давай спокойно обсудим твои планы."]):
                start = time.perf_counter()
                audio = await voice.render(text, "serena", "qwen3", "timing-" + str(index), device=os.environ.get("WILEYAI_QWEN_DEVICE", "auto"), session_id="timing-session")
                elapsed = time.perf_counter() - start
                with wave.open(io.BytesIO(audio), "rb") as sound:
                    duration = sound.getnframes() / sound.getframerate()
                assert duration > .1
                row = {"phrase": index + 1, "device": audio.device, "synthesis_seconds": round(elapsed, 2), "audio_seconds": round(duration, 2), "ratio": round(elapsed / duration, 2)}
                rows.append(row)
                print(row, flush=True)
            target = Path(__file__).resolve().parents[1] / "local/qwen-timing.json"
            import json
            target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            await voice.stop()
    asyncio.run(scenario())
