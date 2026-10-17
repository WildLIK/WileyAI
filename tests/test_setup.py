import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

from core.api import create_app
from core import providers
from core.config import Settings
from core.setup import Setup, ProgressUpdate, model_present, speech_readiness
from core.storage import Store

TOKEN = "setup-test-session-0123456789abcdef"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_TEST", "1")
    monkeypatch.setattr(providers, "get_key", lambda settings: "")
    with TestClient(create_app(tmp_path, TOKEN), headers=HEADERS) as client:
        yield client


def test_only_fresh_packaged_installations_start_automatically(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_PACKAGED", "1")
    fresh = Setup(tmp_path / "fresh", True)
    assert fresh.state()["active"]
    existing = Setup(tmp_path / "existing", False)
    assert not existing.state()["active"]
    monkeypatch.delenv("WILEYAI_PACKAGED")
    assert not Setup(tmp_path / "source", True).state()["active"]


def test_progress_resume_pause_complete_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_PACKAGED", "1")
    original = Setup(tmp_path, True)
    original.update(ProgressUpdate(step=2, mode="cloud", voice_mode="piper", microphone=True))
    resumed = Setup(tmp_path, False)
    assert resumed.state()["active"] and resumed.state()["step"] == 2
    resumed.update(ProgressUpdate(active=False))
    assert not Setup(tmp_path, False).state()["active"]
    resumed.update(ProgressUpdate(completed=True, step=3))
    assert Setup(tmp_path, False).state()["completed"]
    assert set(json.loads(resumed.path.read_text(encoding="utf-8"))) == {"active", "completed", "step", "mode", "voice_mode", "microphone"}


def test_existing_database_is_never_treated_as_new(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_PACKAGED", "1")
    monkeypatch.setenv("WILEYAI_TEST", "1")
    Store(tmp_path).save_settings(Settings(name="Мой персонаж"))
    with TestClient(create_app(tmp_path, TOKEN), headers=HEADERS) as client:
        assert client.get("/setup").json()["active"] is False


def test_sparse_setup_edits_preserve_personality_permissions_and_keys(api, monkeypatch):
    initial = api.get("/settings").json()
    initial.update(name="Знакомая", personality="Мой характер", allow_app_open=False, tts_engine="cloud", tts_cloud_voice="mita-voice")
    api.put("/settings", json=initial).raise_for_status()
    calls = []
    monkeypatch.setattr(providers, "set_key", lambda settings, value: calls.append((settings.base_url, value)))
    response = api.patch("/setup/settings", json={"model": "my-model", "audio_input_device_id": "usb-mic"})
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Знакомая" and updated["personality"] == "Мой характер"
    assert not updated["allow_app_open"] and updated["tts_cloud_voice"] == "mita-voice"
    assert updated["model"] == "my-model" and updated["audio_input_device_id"] == "usb-mic"
    assert not calls
    response = api.patch("/setup/settings", json={"provider": "compatible", "base_url": "https://example.com/v1", "api_key": "TEST_NOT_A_REAL_KEY"})
    assert response.status_code == 200 and calls == [("https://example.com/v1", "TEST_NOT_A_REAL_KEY")]
    assert "TEST_NOT_A_REAL_KEY" not in response.text
    assert "TEST_NOT_A_REAL_KEY" not in api.get("/backups/export").text
    assert "TEST_NOT_A_REAL_KEY" not in api.get("/setup").text


def test_setup_patch_validation_auth_and_cors(api):
    assert api.patch("/setup/settings", json={"model": "x"}, headers={"Authorization": ""}).status_code == 401
    assert api.patch("/setup/settings", json={"personality": "overwrite"}).status_code == 422
    assert api.patch("/setup/settings", json={"base_url": "file:///C:/secrets"}).status_code == 400
    assert api.put("/setup", json={"api_key": "secret"}).status_code == 422
    assert api.put("/setup", json={"step": 100}).status_code == 422
    assert api.options("/setup/settings", headers={"Origin": "app://wileyai", "Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "authorization,content-type"}).status_code == 200


def test_readiness_does_not_generate_chat_or_record_voice(api, monkeypatch):
    calls = []
    async def list_models(config):
        calls.append("list")
        return [{"id": config.model, "size": 100}]
    async def forbidden(*args, **kwargs):
        raise AssertionError("Readiness must not generate a model reply")
    monkeypatch.setattr(providers, "list_models", list_models)
    monkeypatch.setattr(providers, "chat", forbidden)
    response = api.post("/setup/check")
    assert response.status_code == 200
    assert response.json()["brain"]["model_available"] and calls == ["list"]
    assert not response.json()["speech"]["recognition"]  # No weights in this data directory.


def test_offline_check_stays_recoverable(api, monkeypatch):
    async def unavailable(config):
        raise httpx.ConnectError("unavailable")
    monkeypatch.setattr(providers, "list_models", unavailable)
    check = api.post("/setup/check").json()
    assert not check["brain"]["connected"] and check["brain"]["error"]
    assert api.put("/setup", json={"active": False, "step": 1}).status_code == 200


def test_local_latest_alias_and_exact_cloud_model_matching():
    assert model_present(Settings(model="local"), [{"id": "local:latest"}])
    assert not model_present(Settings(model="local"), [{"id": "other:latest"}])
    assert not model_present(Settings(provider="compatible", base_url="https://example.com/v1", model="local"), [{"id": "local:latest"}])


def test_model_pull_and_cancel_run_in_the_event_loop(api, monkeypatch):
    started = []
    cancelled = []
    from core.models import ModelJobs
    async def run(self, config, item, path):
        started.append(item["model"])
        try:
            item["status"] = "running"
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            item["status"] = "cancelled"
            cancelled.append(item["model"])
    monkeypatch.setattr(ModelJobs, "run", run)
    response = api.post("/models/pull", json={"model": "test-local"})
    assert response.status_code == 200
    job = response.json()
    api.delete("/jobs/" + job["id"]).raise_for_status()
    assert api.get("/jobs").json()[0]["status"] == "cancelled"
    assert started == cancelled == ["test-local"]


def test_speech_readiness_respects_weights_and_system_voice(tmp_path):
    voice = SimpleNamespace(root=tmp_path, available=lambda: True,
        piper=SimpleNamespace(available=lambda: True, installed=lambda name: name == "irina"))
    config = Settings(tts_engine="piper", tts_voice="irina")
    assert speech_readiness(config, voice, [])["synthesis"]
    assert not speech_readiness(config, voice, [])["recognition"]
    model = tmp_path / "models/whisper/small/model.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"test")
    assert speech_readiness(config, voice, [])["recognition"]
    config = Settings(tts_engine="sapi", tts_voice="missing")
    assert not speech_readiness(config, voice, [{"name": "other"}])["synthesis"]
