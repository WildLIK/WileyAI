import asyncio
import io
import json
import wave

from fastapi.testclient import TestClient
import httpx
import pytest

from core.api import create_app
from core.config import Settings
from core.cloud_speech import CloudSpeech, pcm_wave
from core import cloud_speech


def wav(seconds=1):
    return pcm_wave(b"\x01\x00" * 24000 * seconds)


@pytest.fixture
def api(tmp_path, monkeypatch):
    keys = {}
    monkeypatch.setattr(cloud_speech, "get_key", lambda url: keys.get(url, ""))
    monkeypatch.setattr(cloud_speech, "set_key", lambda url, value: keys.update({url: value}))
    with TestClient(create_app(tmp_path, "test-cloud-speech-token-0123456789")) as api:
        api.headers["Authorization"] = "Bearer test-cloud-speech-token-0123456789"
        yield api, keys


def transport(monkeypatch, handler):
    monkeypatch.setattr(cloud_speech, "client", lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_connections_are_separate_secrets_and_settings_changes_do_not_call_provider(api, monkeypatch):
    api, keys = api
    transport(monkeypatch, lambda request: pytest.fail("Saving preferences must not call a cloud service"))
    key = "private-speech-secret"
    result = api.put("/voice/cloud/key", json={"base_url": "https://openrouter.ai/api/v1/", "api_key": key})
    assert result.json() == {"has_key": True}
    saved = api.put("/settings/speech", json={"tts_engine": "cloud", "tts_model": "fish-audio/s2.1-pro-free:free"})
    assert saved.status_code == 200
    assert saved.json()["provider"] == "ollama"
    assert key not in api.get("/settings").text
    assert key not in api.get("/backups/export").text
    assert key not in api.get("/voice/cloud/connections").text
    assert keys["https://openrouter.ai/api/v1"] == key
    assert api.put("/voice/cloud/key", json={"base_url": "http://example.com", "api_key": "key"}).status_code == 422
    assert api.put("/settings/speech", json={"tts_base_url": "https://key@example.com"}).status_code == 400


@pytest.mark.parametrize("model,service,voice,format", [
    ("fish-audio/s2.1-pro-free:free", "openrouter", "fish-id", "mp3"),
    ("google/gemini-3.8-flash-tts", "routerai", "Sulafat", "pcm"),
    ("x-ai/grok-voice-tts-1.0", "routerai", "ara", "mp3"),
])
def test_all_three_models_use_independent_connection_and_correct_audio_contract(api, monkeypatch, model, service, voice, format):
    api, keys = api
    url = cloud_speech.SERVICES[service]
    keys[url] = "speech-key"
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        assert str(request.url) == url + "/audio/speech"
        assert request.headers["authorization"] == "Bearer speech-key"
        return httpx.Response(200, content=b"\0\0" * 24000 if format == "pcm" else b"ID3valid-test", headers={"content-type": "audio/pcm" if format == "pcm" else "audio/mpeg"})
    transport(monkeypatch, handler)
    response = api.post("/voice/synthesize", json={"text": "**Привет!**", "engine": "cloud", "cloud": {
        "tts_base_url": url, "tts_service": service, "tts_model": model, "tts_cloud_voice": voice, "tts_style": "warm"}})
    assert response.status_code == 200
    assert sent[0]["input"] == "Привет!" and sent[0]["response_format"] == format
    assert sent[0]["voice"] == voice
    assert "messages" not in sent[0]
    if model.startswith("google/"):
        assert "instructions" not in sent[0]
        assert sent[0]["provider"]["options"]["google-ai-studio"]["speech_metadata"]["style"] == "warm"
        with wave.open(io.BytesIO(response.content), "rb") as audio:
            assert audio.getnchannels() == 1 and audio.getframerate() == 24000
            assert audio.getnframes() == 24000
        assert response.headers["content-type"] == "audio/wav"
    else:
        assert response.headers["content-type"] == "audio/mpeg"
    # Comparison overrides do not silently change the selected engine/model.
    assert api.get("/settings").json()["tts_engine"] == "silero"
    rows = api.app.state.monitor.sample()["rows"]
    measured = next(row for row in rows if row["name"] == model)
    assert measured["location"] == "cloud" and measured["ram"] is None


def test_reference_validation_sending_and_removal_are_explicit(api, monkeypatch):
    api, keys = api
    assert api.post("/voice/cloud/reference", files={"file": ("fake.wav", b"invalid")}).status_code == 400
    result = api.post("/voice/cloud/reference", files={"file": ("my-voice.wav", wav(2))})
    assert result.json()["reference"] == {"name": "my-voice.wav", "seconds": 2}
    keys[cloud_speech.SERVICES["openrouter"]] = "speech-key"
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav"})
    transport(monkeypatch, handler)
    payload = {"text": "Hello", "engine": "cloud", "cloud": {"tts_use_reference": False}}
    assert api.post("/voice/synthesize", json=payload).status_code == 200
    assert "input_references" not in bodies[0]
    payload["cloud"]["tts_use_reference"] = True
    assert api.post("/voice/synthesize", json=payload).status_code == 200
    assert bodies[1]["input_references"][0]["input_audio"]["data"].startswith("data:audio/wav;base64,")
    assert "voice" not in bodies[1]
    assert api.delete("/voice/cloud/reference").status_code == 200
    assert api.get("/voice/cloud/connections").json()["reference"] is None
    assert api.post("/voice/synthesize", json=payload).status_code == 400
    assert len(bodies) == 2


@pytest.mark.parametrize("code", [400, 401, 402, 403, 404, 429, 500])
def test_provider_errors_never_echo_keys_or_spoken_text_or_fall_back(api, monkeypatch, code):
    api, keys = api
    keys[cloud_speech.SERVICES["openrouter"]] = "private-secret"
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(code, json={"error": "private-secret private-spoken-text"})
    transport(monkeypatch, handler)
    response = api.post("/voice/synthesize", json={"text": "private-spoken-text", "engine": "cloud"})
    assert response.status_code == 400 and str(code) in response.text
    assert "private-secret" not in response.text and "private-spoken-text" not in response.text
    assert len(sent) == 1


def test_cloud_stop_cancels_pending_http_and_does_not_cancel_a_new_request(tmp_path, monkeypatch):
    cloud = CloudSpeech(tmp_path)
    monkeypatch.setattr(cloud_speech, "get_key", lambda _: "key")
    entered = asyncio.Event()
    async def handler(request):
        entered.set()
        await asyncio.Event().wait()
    transport(monkeypatch, handler)
    async def scenario():
        task = asyncio.create_task(cloud.render("hello", Settings(), "old"))
        await entered.wait()
        await cloud.stop("other")
        assert not task.done()
        await cloud.stop("old")
        with pytest.raises(ValueError, match="остановлена"):
            await task
        assert not cloud.requests
    asyncio.run(scenario())


def test_catalog_does_not_generate_audio_and_filters_text_only_models(api, monkeypatch):
    api, keys = api
    keys[cloud_speech.SERVICES["openrouter"]] = "key"
    def handler(request):
        assert request.method == "GET" and request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [
            {"id": "tts", "supported_voices": ["warm"], "architecture": {"output_modalities": ["speech"]}},
            {"id": "chat", "architecture": {"output_modalities": ["text"]}},
        ]})
    transport(monkeypatch, handler)
    result = api.get("/voice/cloud/catalog")
    assert result.status_code == 200 and result.json()[0]["voices"] == ["warm"]
    assert len(result.json()) == 1


def test_reference_preference_does_not_send_sample_to_grok_or_gemini(api, monkeypatch):
    api, keys = api
    keys[cloud_speech.SERVICES["routerai"]] = "key"
    def handler(request):
        assert "input_references" not in json.loads(request.content)
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav"})
    transport(monkeypatch, handler)
    response = api.post("/voice/synthesize", json={"text": "hello", "engine": "cloud", "cloud": {
        "tts_base_url": cloud_speech.SERVICES["routerai"], "tts_service": "routerai", "tts_model": "x-ai/grok-voice-tts-1.0", "tts_use_reference": True}})
    assert response.status_code == 200


@pytest.mark.parametrize("data,content_type", [(b"", "audio/mpeg"), (b'{"message":"private"}', "application/json"), (b"not audio", "audio/mpeg")])
def test_invalid_successful_audio_is_rejected(api, monkeypatch, data, content_type):
    api, keys = api
    keys[cloud_speech.SERVICES["openrouter"]] = "key"
    transport(monkeypatch, lambda _: httpx.Response(200, content=data, headers={"content-type": content_type}))
    result = api.post("/voice/synthesize", json={"text": "hello", "engine": "cloud"})
    assert result.status_code == 400 and "private" not in result.text
