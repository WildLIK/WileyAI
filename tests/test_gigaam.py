import asyncio
import hashlib
import io
import json
import sys
from types import SimpleNamespace
import wave

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from core import gigaam
from core.api import create_app
from core.config import Settings
from core.voice import Voice


def wav(samples=None, rate=16000, channels=1):
    samples = np.zeros(rate, dtype="<i2") if samples is None else samples
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples.tobytes())
    return out.getvalue()


@pytest.fixture
def manifest(monkeypatch):
    content = {"config.json": b'{"version":"v3"}', "encoder.onnx": b"encoder", "vad/silero_vad.onnx": b"vad"}
    monkeypatch.setattr(gigaam, "FILES", {
        path: ("test/gigaam", gigaam.REVISION, path, len(data), hashlib.sha256(data).hexdigest())
        for path, data in content.items()
    })
    return content


def downloader(root, content, fail=None):
    calls = []
    def handle(request):
        name = str(request.url).split(gigaam.REVISION + "/")[1]
        calls.append(name)
        return httpx.Response(200, content=(fail if name == "encoder.onnx" and fail is not None else content[name]))
    gigaam.download(root, transport=httpx.MockTransport(handle))
    return calls


def test_verified_download_resumes_and_publishes_complete_set(tmp_path, manifest):
    assert not gigaam.installed(tmp_path)
    assert downloader(tmp_path, manifest) == list(manifest)
    assert gigaam.installed(tmp_path)
    assert downloader(tmp_path, manifest) == []
    # Correct size alone cannot skip a corrupt file during an explicit repair.
    target = gigaam.folder(tmp_path) / "encoder.onnx"
    target.write_bytes(b"invalid")
    assert downloader(tmp_path, manifest) == ["encoder.onnx"]
    assert target.read_bytes() == manifest["encoder.onnx"]


@pytest.mark.parametrize("bad", [b"wrong!!", b"too short", b"far too long for the expected file"])
def test_invalid_download_never_marks_ready_and_keeps_verified_files(tmp_path, manifest, bad):
    with pytest.raises(ValueError, match="GigaAM"):
        downloader(tmp_path, manifest, bad)
    assert not gigaam.installed(tmp_path)
    assert not list(gigaam.folder(tmp_path).rglob("*.part"))
    assert (gigaam.folder(tmp_path) / "config.json").read_bytes() == manifest["config.json"]
    assert downloader(tmp_path, manifest) == ["encoder.onnx", "vad/silero_vad.onnx"]
    assert gigaam.installed(tmp_path)


def test_truncated_or_wrong_revision_is_not_installed(tmp_path, manifest):
    downloader(tmp_path, manifest)
    (gigaam.folder(tmp_path) / "ready.json").write_text(json.dumps({"model": "old", "vad": gigaam.VAD_REVISION}))
    assert not gigaam.installed(tmp_path)
    downloader(tmp_path, manifest)
    (gigaam.folder(tmp_path) / "encoder.onnx").write_bytes(b"truncated")
    assert not gigaam.installed(tmp_path)


def test_decoder_resamples_stereo_wav_to_mono_float32():
    samples = np.tile(np.array([8192, 8192], dtype="<i2"), 4800)
    decoded = gigaam.decode_audio(wav(samples, rate=48000, channels=2))
    assert decoded.dtype == np.float32 and decoded.ndim == 1
    assert len(decoded) == 1600
    # FFmpeg's stereo downmix uses equal-power coefficients (1/sqrt(2)).
    assert np.allclose(decoded, 0.25 * np.sqrt(2), atol=0.002)


def test_decoder_reads_real_webm_opus_in_memory():
    import av
    out = io.BytesIO()
    with av.open(out, "w", format="webm") as container:
        stream = container.add_stream("libopus", rate=48000)
        samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)).astype(np.float32)[None, :]
        frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="mono")
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    decoded = gigaam.decode_audio(out.getvalue())
    assert len(decoded) == 1600 and np.max(np.abs(decoded)) > 0.1


def test_bad_audio_and_duration_limits_have_actionable_errors(monkeypatch):
    with pytest.raises(ValueError, match="прочитать запись"):
        gigaam.decode_audio(b"broken file")
    monkeypatch.setattr(gigaam, "MAX_SAMPLES", 100)
    with pytest.raises(ValueError, match="пяти минут"):
        gigaam.decode_audio(wav())


def test_native_loader_uses_local_cpu_models_and_does_not_require_whisper(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gigaam, "available", lambda: True)
    monkeypatch.setattr(gigaam, "installed", lambda root: True)
    def load(name, path, **kwargs):
        calls.append((name, path, kwargs))
        return object()
    monkeypatch.setitem(sys.modules, "onnx_asr", SimpleNamespace(load_model=load, load_vad=load))
    voice = Voice(tmp_path)
    voice.models["small"] = object()
    voice._load_stt("gigaam-v3")
    voice._load_stt("gigaam-v3")
    assert list(voice.models) == ["gigaam-v3"]
    assert [(name, path) for name, path, _ in calls] == [
        ("gigaam-v3-e2e-rnnt", gigaam.folder(tmp_path)), ("silero", gigaam.folder(tmp_path) / "vad")]
    assert all(kwargs["providers"] == ["CPUExecutionProvider"] for _, _, kwargs in calls)
    assert all(1 <= kwargs["sess_options"].intra_op_num_threads <= 8 for _, _, kwargs in calls)


@pytest.mark.parametrize("available,installed,match", [(False, False, "компонент"), (True, False, "скачайте")])
def test_missing_runtime_or_weights_do_not_trigger_downloads(tmp_path, monkeypatch, available, installed, match):
    monkeypatch.setattr(gigaam, "available", lambda: available)
    monkeypatch.setattr(gigaam, "installed", lambda root: installed)
    with pytest.raises(ValueError, match=match):
        Voice(tmp_path)._load_stt("gigaam-v3")


@pytest.mark.parametrize("environment,threshold", [("normal", 0.5), ("music", 0.65)])
def test_voice_routes_gigaam_through_bounded_vad_and_not_whisper(tmp_path, monkeypatch, environment, threshold):
    calls = []
    model = gigaam.GigaAM.__new__(gigaam.GigaAM)
    model.vad = object()
    def with_vad(vad, **options):
        assert vad is model.vad
        calls.append(options)
        def recognize(audio, **kwargs):
            assert len(audio) == 16000 and kwargs == {"sample_rate": 16000}
            yield SimpleNamespace(text=" Открой браузер. ")
            yield SimpleNamespace(text="")
            yield SimpleNamespace(text="Поставь музыку.")
        return SimpleNamespace(recognize=recognize)
    model.model = SimpleNamespace(with_vad=with_vad)
    voice = Voice(tmp_path)
    monkeypatch.setattr(voice, "_load_stt", lambda name: voice.models.update({name: model}))
    assert voice.transcribe(wav(), "gigaam-v3", "Уайли", "fast", environment) == "Открой браузер. Поставь музыку."
    assert calls == [dict(batch_size=1, threshold=threshold, min_speech_duration_ms=200,
                         min_silence_duration_ms=300, speech_pad_ms=250, max_speech_duration_s=20)]
    assert asyncio.run(voice.unload()) == [gigaam.MODEL_NAME]


def test_gigaam_empty_and_nonfinite_samples_do_not_reach_native_decoder():
    model = gigaam.GigaAM.__new__(gigaam.GigaAM)
    assert model.transcribe(b"", np.empty(0, np.float32)) == ""
    with pytest.raises(ValueError, match="повреждённые"):
        model.transcribe(b"", np.array([np.nan], np.float32))


def test_api_persists_selection_dispatches_audio_and_reports_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_TEST", "1")
    from core import providers
    monkeypatch.setattr(providers, "get_key", lambda settings: "")
    async def models(settings):
        return []
    monkeypatch.setattr(providers, "list_models", models)
    monkeypatch.setattr(gigaam, "available", lambda: True)
    monkeypatch.setattr(gigaam, "installed", lambda root: root == tmp_path)
    seen = []
    def recognize(self, data, model, hint, quality, environment):
        seen.append((data, model, quality, environment))
        return "Открой браузер."
    monkeypatch.setattr(Voice, "transcribe", recognize)
    monkeypatch.setattr(Voice, "download", lambda self, model: seen.append(model))
    token = "gigaam-test-0123456789abcdef"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        config = api.get("/settings").json()
        config.update(stt_model="gigaam-v3", stt_environment="music")
        assert api.put("/settings", json=config).json()["stt_model"] == "gigaam-v3"
        assert api.get("/voice").json()["gigaam_available"]
        assert "gigaam-v3" in api.get("/voice").json()["installed_stt"]
        assert api.post("/voice/download", json={"model": "gigaam-v3"}).status_code == 200
        assert api.post("/voice/transcribe", files={"file": ("voice.webm", b"audio", "audio/webm")}).json() == {"text": "Открой браузер."}
        assert api.post("/voice/download", json={"model": "gigaam-other"}).status_code == 400
        assert api.patch("/setup/settings", json={"stt_model": "gigaam-v3"}).status_code == 200
        assert api.post("/setup/check").json()["speech"]["recognition"]
        assert seen == ["gigaam-v3", (b"audio", "gigaam-v3", "accurate", "music")]
    assert Settings(stt_model="small").stt_model == "small"
