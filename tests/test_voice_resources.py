import asyncio
import os
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.voice import Voice


def test_unload_clears_native_models_and_resets_piper_for_next_load(tmp_path):
    async def scenario():
        voice = Voice(tmp_path)
        voice.models["small"] = object()
        voice.tts_model, voice.tts_version = object(), "v5_6_ru"
        voice.piper.model, voice.piper.selected = object(), "irina"
        result = await voice.unload()
        assert result == ["Whisper small", "Silero 5.6", "Piper"]
        assert not voice.models and voice.tts_model is None
        assert voice.piper.model is None and voice.piper.selected == ""
        assert await voice.unload() == []
    asyncio.run(scenario())


def test_unload_refuses_active_native_work_without_waiting(tmp_path):
    async def scenario():
        voice = Voice(tmp_path)
        original = object()
        voice.models["small"] = original
        for lock in [voice.lock, voice.tts_lock]:
            lock.acquire()
            try:
                assert await asyncio.wait_for(voice.unload(), timeout=1) is None
                assert voice.models["small"] is original
            finally:
                lock.release()
        voice.synthesis_jobs["pending"] = threading.Event()
        assert await voice.unload() is None
        assert voice.models["small"] is original
    asyncio.run(scenario())


def test_idle_workers_close_without_stopping_an_active_worker(tmp_path):
    class Session:
        def __init__(self):
            self.active_id = None
            self.closed = False
        async def close(self): self.closed = True

    async def scenario():
        voice = Voice(tmp_path)
        qwen, converter = Session(), Session()
        voice.qwen.sessions["qwen"] = qwen
        voice.openvoice.sessions["converter"] = converter
        qwen.active_id = "request"
        assert await voice.unload() is None
        assert not qwen.closed and not converter.closed
        qwen.active_id = None
        assert await voice.unload() == ["Qwen3-TTS", "OpenVoice"]
        assert qwen.closed and converter.closed
        assert not voice.qwen.sessions and not voice.openvoice.sessions
    asyncio.run(scenario())


def test_unload_api_is_authenticated_preserves_settings_and_reports_conflicts(tmp_path):
    app = create_app(tmp_path, "test-voice-resources-0123456789")
    with TestClient(app) as api:
        assert api.post("/voice/unload").status_code == 401
        api.headers["Authorization"] = "Bearer test-voice-resources-0123456789"
        voice = app.state.monitor.voice
        config = api.get("/settings").json()
        voice.models["small"] = object()
        assert api.post("/voice/unload").json() == {"unloaded": ["Whisper small"]}
        assert api.get("/settings").json() == config
        voice.speech = SimpleNamespace(returncode=None)
        assert api.post("/voice/unload").status_code == 409
        voice.speech = None
        assert api.post("/voice/unload").json() == {"unloaded": []}


@pytest.mark.skipif(os.environ.get("WILEYAI_RESOURCE_TESTS") != "1", reason="Requires downloaded Whisper small, Piper and Silero 5.6")
def test_real_models_reload_after_idle_release():
    async def scenario():
        now = [0]
        voice = Voice(Path(__file__).resolve().parents[1] / "data", clock=lambda: now[0])
        try:
            await asyncio.to_thread(voice.prepare, "small", "piper", "irina")
            await asyncio.to_thread(voice.synthesize, "Привет! Продолжим работу.", "xenia", None, "silero_v5_6")
            now[0] = 61
            assert set(await voice.unload(idle_seconds=60)) == {"Whisper small", "Piper", "Silero 5.6"}
            assert not voice.models and voice.piper.model is None and voice.tts_model is None
            # Same voice selection must reload the native ONNX session, not return None.
            audio = await asyncio.to_thread(voice.synthesize, "Привет! Продолжим работу.", "irina", None, "piper")
            assert audio.startswith(b"RIFF")
            assert (await asyncio.to_thread(voice.synthesize, "Привет! Продолжим работу.", "xenia", None, "silero_v5_6")).startswith(b"RIFF")
            recognized = await asyncio.to_thread(voice.transcribe, audio, "small")
            assert "работ" in recognized.casefold(), recognized
            assert "small" in voice.models
        finally:
            await voice.unload()
    asyncio.run(scenario())
