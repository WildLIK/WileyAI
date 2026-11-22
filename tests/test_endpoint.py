import asyncio
import hashlib
import io
import json
import threading
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core import smart_turn
from core.smart_turn_worker import features


def wav(samples=16000):
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(bytes(samples * 2))
    return data.getvalue()


def test_smart_turn_is_optional_offline_and_never_downloaded_by_status_or_check(tmp_path, monkeypatch):
    app = create_app(tmp_path, "endpoint-test-token-0123456789")
    def forbidden(*a, **kw): pytest.fail("No implicit model/network download")
    monkeypatch.setattr(smart_turn.SmartTurn, "download", forbidden)
    with TestClient(app, headers={"Authorization": "Bearer endpoint-test-token-0123456789"}) as client:
        settings = client.get("/settings").json()
        assert settings["conversation_endpoint_mode"] == "auto" and settings["conversation_vad"] == "auto"
        assert settings["conversation_smart_turn"] is False
        assert client.get("/voice/endpoint/status").json()["installed"] is False
        assert client.post("/voice/endpoint/check", files={"file": ("audio.wav", wav(), "audio/wav")}).json()["reason"] == "disabled"
        settings["conversation_smart_turn"] = True
        assert client.put("/settings", json=settings).status_code == 200
        assert client.post("/voice/endpoint/check", files={"file": ("audio.wav", wav(), "audio/wav")}).json()["available"] is False
        assert not (tmp_path / "models/smart-turn").exists()
        assert client.post("/voice/endpoint/release").json()["ok"]


@pytest.mark.parametrize("valid", [True, False])
def test_explicit_model_download_verifies_hash_before_marking_ready(tmp_path, monkeypatch, valid):
    content = b"verified ONNX model fixture"
    monkeypatch.setattr(smart_turn, "SIZE", len(content))
    monkeypatch.setattr(smart_turn, "SHA256", hashlib.sha256(content).hexdigest() if valid else "0" * 64)
    original = httpx.AsyncClient
    monkeypatch.setattr(smart_turn.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)), **kwargs))
    model = smart_turn.SmartTurn(tmp_path)
    if valid:
        assert asyncio.run(model.download())["installed"]
        assert model.path.read_bytes() == content
    else:
        with pytest.raises(ValueError, match="сумма"): asyncio.run(model.download())
        assert not model.path.exists()
    assert not list(tmp_path.rglob("*.part")) and not model.installing


def test_features_have_a_bounded_shape_and_match_whisper_reference():
    audio = np.random.default_rng(33).normal(0, .1, 16000 * 12).astype(np.float32)
    result = features(audio)
    assert result.shape == (1, 80, 800) and result.dtype == np.float32 and np.isfinite(result).all()
    # Optional reference package is present in the voice runtime; feature math
    # itself requires only NumPy, not Whisper, Torch, or Transformers.
    try: from faster_whisper.feature_extractor import FeatureExtractor
    except ImportError: return
    tail = audio[-128000:]; normalized = (tail - tail.mean()) / np.sqrt(tail.var() + 1e-7)
    np.testing.assert_allclose(result[0], FeatureExtractor(chunk_length=8)(normalized, padding=0), atol=1e-5)


def test_unreadable_optional_model_and_failed_install_do_not_leave_installing_state(tmp_path, monkeypatch):
    model = smart_turn.SmartTurn(tmp_path)
    model.path.parent.mkdir(parents=True)
    model.path.write_bytes(b"fixture")
    monkeypatch.setattr(smart_turn, "SIZE", 7)
    marker = model.path.with_suffix(".sha256")
    marker.write_text(smart_turn.SHA256)
    path_class = type(model.path)
    original_read = path_class.read_text
    def read_text(path, *args, **kwargs):
        if path == marker: raise PermissionError("Unavailable optional model")
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(path_class, "read_text", read_text)
    assert model.status()["installed"] is False
    def mkdir(*args, **kwargs): raise PermissionError("Unavailable model directory")
    monkeypatch.setattr(path_class, "mkdir", mkdir)
    with pytest.raises(PermissionError): asyncio.run(model.download())
    assert model.installing is False


def test_optional_worker_failures_and_bad_audio_do_not_hold_the_turn(tmp_path, monkeypatch):
    model = smart_turn.SmartTurn(tmp_path)
    async def unavailable(): return False
    monkeypatch.setattr(model, "warm", unavailable)
    async def run():
        assert not (await model.evaluate(b"broken"))["available"]
        assert not (await model.evaluate(wav()))["available"]
        assert not (await model.evaluate(wav(128001)))["available"]
        await model.lock.acquire()
        assert (await model.evaluate(wav()))["reason"] == "busy"
        model.lock.release()
        await model.close()
    asyncio.run(run())


def test_stt_cancellation_retains_ownership_of_native_job_and_prevents_duplicate_queue(tmp_path, monkeypatch):
    app = create_app(tmp_path, "endpoint-test-token-0123456789")
    entered, release = threading.Event(), threading.Event(); calls = []
    def transcribe(*args):
        calls.append(1); entered.set(); assert release.wait(3); return "Первая фраза"
    monkeypatch.setattr("core.api.Voice.transcribe", transcribe)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers={"Authorization": "Bearer endpoint-test-token-0123456789"}) as client:
            first = asyncio.create_task(client.post("/voice/transcribe", files={"file": ("audio.wav", wav())}))
            assert await asyncio.to_thread(entered.wait, 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError): await first
            second = await client.post("/voice/transcribe", files={"file": ("audio.wav", wav())})
            assert second.status_code == 409 and len(calls) == 1
            release.set()
            await asyncio.sleep(.05)
            third = await client.post("/voice/transcribe", files={"file": ("audio.wav", wav())})
            assert third.status_code == 200 and len(calls) == 2
    try: asyncio.run(run())
    finally: release.set()


def test_diagnostic_timings_separate_llm_and_local_command_without_extra_actions(tmp_path, monkeypatch):
    calls = []
    async def reply(*args, **kwargs):
        calls.append(1); await asyncio.sleep(.01); yield "Всё хорошо."
    monkeypatch.setattr("core.providers.chat", reply)
    app = create_app(tmp_path, "endpoint-test-token-0123456789")
    app.state.store.patch_settings({"voice_diagnostics": True})
    with TestClient(app, headers={"Authorization": "Bearer endpoint-test-token-0123456789"}) as client:
        def send(text):
            response = client.post("/chat", json={"text": text, "mode": "conversation"})
            assert response.status_code == 200
            return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        events = send("Как настроение?")
        timing = [event for event in events if event["type"] == "voice_timing"]
        assert len(timing) == 1 and timing[0]["llm_ms"] >= 5 and timing[0]["interpretation_ms"] >= 0
        events = send("Не открывай Блокнот")
        timing = [event for event in events if event["type"] == "voice_timing"]
        assert len(timing) == 1 and timing[0]["llm_ms"] == 0 and len(calls) == 1


def test_worker_cleanup_checks_its_process_birth_before_enumerating_descendants(tmp_path, monkeypatch):
    model = smart_turn.SmartTurn(tmp_path); killed = []
    async def wait(): pass
    model.process = SimpleNamespace(pid=42, returncode=None, kill=lambda: killed.append("owned_handle"), wait=wait)
    model.process_created = 12
    monkeypatch.setattr(smart_turn.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 13, children=lambda **kw: pytest.fail("PID was reused")))
    asyncio.run(model.close())
    assert killed == ["owned_handle"] and model.process is None
