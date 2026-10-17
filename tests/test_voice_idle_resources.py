import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from core import voice_resources
from core.api import create_app
from core.backups import Backups
from core.config import Settings
from core.storage import Store
from core.voice import Voice


@pytest.mark.parametrize("profile,policy,expected", [
    ("eco", "profile", 60), ("balanced", "profile", 300), ("quality", "profile", 900),
    ("quality", "1m", 60), ("eco", "5m", 300), ("balanced", "15m", 900), ("eco", "never", None),
])
def test_policy_follows_profile_or_explicit_preference(profile, policy, expected):
    assert voice_resources.idle_seconds(Settings(profile=profile, voice_idle_timeout=policy)) == expected


def test_idle_time_is_independent_for_each_native_model(tmp_path):
    now = [1000]
    voice = Voice(tmp_path, clock=lambda: now[0])
    voice.models["small"] = object()
    voice.tts_model, voice.tts_version = object(), "v5_6_ru"
    voice.piper.model, voice.piper.selected = object(), "irina"
    voice.last_used.update(stt=1000, silero=900, piper=700)
    async def run():
        assert await voice.unload(idle_seconds=300) == ["Piper"]
        assert voice.models and voice.tts_model is not None
        now[0] = 1201
        assert await voice.unload(idle_seconds=300) == ["Silero 5.6"]
        assert voice.models
        now[0] = 1300
        assert await voice.unload(idle_seconds=300) == ["Whisper small"]
        assert await voice.unload(idle_seconds=300) == []
    asyncio.run(run())


def test_recognition_idle_starts_after_long_native_work_finishes(tmp_path, monkeypatch):
    now = [0]
    voice = Voice(tmp_path, clock=lambda: now[0])
    def transcribe(*args, **kwargs):
        now[0] = 120
        return [SimpleNamespace(text="Привет")], None
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=transcribe)}))
    assert voice.transcribe(b"fake-audio", "small") == "Привет"
    assert voice.last_used["stt"] == 120
    async def run():
        now[0] = 179
        assert await voice.unload(idle_seconds=60) == []
        now[0] = 180
        assert await voice.unload(idle_seconds=60) == ["Whisper small"]
    asyncio.run(run())


def test_preparation_protects_all_models_until_the_conversation_is_ready(tmp_path, monkeypatch):
    now, started, finish = [0], threading.Event(), threading.Event()
    voice = Voice(tmp_path, clock=lambda: now[0])
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: object()}))
    def piper_load(speaker):
        voice.piper.model = object()
        started.set()
        assert finish.wait(5)
    monkeypatch.setattr(voice.piper, "load", piper_load)
    with ThreadPoolExecutor() as pool:
        preparing = pool.submit(voice.prepare, "small", "piper", "irina")
        try:
            assert started.wait(5)
            now[0] = 120
            assert asyncio.run(voice.unload(idle_seconds=60)) is None
            assert voice.models and voice.piper.model is not None
        finally:
            finish.set()
        preparing.result(timeout=5)
    assert voice.last_used["stt"] == voice.last_used["piper"] == 120
    assert asyncio.run(voice.unload(idle_seconds=60)) == []


def test_failed_synthesis_releases_lock_and_updates_usage_time(tmp_path, monkeypatch):
    now = [0]
    voice = Voice(tmp_path, clock=lambda: now[0])
    def piper_load(speaker):
        voice.piper.model = object()
        now[0] = 120
        raise ValueError("Не удалось подготовить голос")
    monkeypatch.setattr(voice.piper, "load", piper_load)
    with pytest.raises(ValueError):
        voice.synthesize("Привет!", "irina", engine="piper")
    assert not voice.tts_lock.locked() and voice.last_used["piper"] == 120
    assert asyncio.run(voice.unload(idle_seconds=60)) == []


@pytest.mark.parametrize("busy", ["prepare", "stt", "tts", "queued", "sapi", "qwen"])
def test_idle_release_defers_active_work_without_clearing_any_model(tmp_path, busy):
    voice = Voice(tmp_path, clock=lambda: 1000)
    voice.last_used["stt"] = 0
    model = voice.models["small"] = object()
    lock = {"prepare": voice.prepare_lock, "stt": voice.lock, "tts": voice.tts_lock}.get(busy)
    if lock:
        lock.acquire()
    elif busy == "queued":
        voice.synthesis_jobs["pending"] = threading.Event()
    elif busy == "sapi":
        voice.speech = SimpleNamespace(returncode=None)
    else:
        voice.qwen.sessions["busy"] = SimpleNamespace(active_id="request")
    try:
        assert asyncio.run(voice.unload(idle_seconds=60)) is None
        assert voice.models["small"] is model
    finally:
        if lock:
            lock.release()


def test_automatic_release_keeps_workers_under_their_own_session_lifecycle(tmp_path):
    voice = Voice(tmp_path, clock=lambda: 1000)
    voice.last_used["stt"] = 0
    voice.models["small"] = object()
    session = SimpleNamespace(active_id=None)
    voice.qwen.sessions["answer"] = session
    voice.openvoice.sessions["answer"] = session
    assert asyncio.run(voice.unload(idle_seconds=60)) == ["Whisper small"]
    assert voice.qwen.sessions["answer"] is session and voice.openvoice.sessions["answer"] is session


def test_no_models_does_not_read_settings_or_trigger_collection(tmp_path, monkeypatch):
    voice = Voice(tmp_path)
    def unexpected():
        pytest.fail("No settings reads or collection needed without resident models")
    monkeypatch.setattr("core.voice.gc.collect", unexpected)
    assert asyncio.run(voice_resources.release_idle(SimpleNamespace(settings=unexpected), voice)) == []
    assert asyncio.run(voice.unload(idle_seconds=60)) == []


def test_saved_policy_is_reread_and_only_actual_unloads_are_audited(tmp_path):
    store = Store(tmp_path)
    voice = Voice(tmp_path, clock=lambda: 1000)
    voice.models["small"] = object()
    voice.last_used["stt"] = 900
    async def run():
        store.save_settings(Settings(voice_idle_timeout="never"))
        assert await voice_resources.release_idle(store, voice) == []
        store.save_settings(Settings(profile="quality"))
        assert await voice_resources.release_idle(store, voice) == []
        store.save_settings(Settings(profile="eco"))
        assert await voice_resources.release_idle(store, voice) == ["Whisper small"]
        assert await voice_resources.release_idle(store, voice) == []
        actions = store.list("actions")
        assert [(item["kind"], item["target"], item["status"]) for item in actions] == [("voice.idle_unload", "Whisper small", "unloaded")]
    asyncio.run(run())


def test_background_service_survives_failure_and_propagates_cancellation(monkeypatch, caplog):
    calls = []
    async def release(*args):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("Transient failure")
        if len(calls) == 3:
            raise asyncio.CancelledError
        return []
    monkeypatch.setattr(voice_resources, "release_idle", release)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(voice_resources.run_idle_resources(None, None, interval=0.001))
    assert len(calls) == 3 and "Cannot release idle speech models" in caplog.text


def test_service_starts_and_stops_with_app_lifespan(tmp_path, monkeypatch):
    started, stopped = threading.Event(), threading.Event()
    async def service(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr("core.api.run_idle_resources", service)
    with TestClient(create_app(tmp_path, "voice-idle-lifecycle-0123456789")):
        assert started.wait(5)
    assert stopped.wait(5)


def test_preference_survives_restart_and_old_backups_default_to_profile(tmp_path):
    store = Store(tmp_path / "original")
    store.save_settings(Settings(voice_idle_timeout="never"))
    assert Store(store.root).settings().voice_idle_timeout == "never"
    archive = Backups(store).export()
    target = Store(tmp_path / "restored")
    backups = Backups(target)
    backups.restore(backups.preview(archive)["ticket"], connections=True)
    assert target.settings().voice_idle_timeout == "never"
    old = json.loads(archive)
    del old["settings"]["voice_idle_timeout"]
    backups.restore(backups.preview(json.dumps(old))["ticket"], connections=True)
    assert target.settings().voice_idle_timeout == "profile"
