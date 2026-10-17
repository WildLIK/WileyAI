import asyncio
import io
import json
import os
from pathlib import Path
import threading
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.openvoice import OpenVoice
from core.voice import Voice


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 32000)
    return output.getvalue()


class Worker:
    def __init__(self, block=False):
        self.returncode = None
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdin = self
        self.payloads = []
        self.kills = 0
        self.block = block
        self.started = asyncio.Event()

    def write(self, data):
        self.payloads.append(json.loads(data))
        self.started.set()
        if not self.block:
            audio = wav()
            self.stdout.feed_data(json.dumps({"size": len(audio), "device": "cpu"}).encode() + b"\n" + audio)

    async def drain(self): pass
    def kill(self):
        self.returncode = -9
        self.kills += 1
        self.stdout.feed_eof()
        self.stderr.feed_eof()
    async def wait(self): return self.returncode


def runner(tmp_path, monkeypatch, worker):
    converter = OpenVoice(tmp_path)
    monkeypatch.setattr(converter, "validate", lambda key: tmp_path / "reference.wav")
    monkeypatch.setattr(converter, "verify", lambda: None)
    launches = []
    async def spawn(*args, **kwargs):
        assert args[1:3] == ("-m", "core.openvoice_worker")
        launches.append(args)
        return worker
    monkeypatch.setattr("core.openvoice.asyncio.create_subprocess_exec", spawn)
    return converter, launches


def test_converter_reuses_worker_and_closes_after_answer(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        converter, launches = runner(tmp_path, monkeypatch, worker)
        for number, key in enumerate(["mita", "kind-mita"]):
            await converter.stop(preserve_session="answer")
            result = await converter.render(wav(), key, str(number), threading.Event(), "answer")
            assert result == wav()
        assert len(launches) == 1 and len(worker.payloads) == 2
        await converter.stop("unrelated-request")
        assert not worker.kills
        await converter.close_session("answer")
        assert worker.kills == 1 and not converter.sessions
    asyncio.run(scenario())


def test_stop_active_conversion_discards_audio_and_worker(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker(block=True)
        converter, _ = runner(tmp_path, monkeypatch, worker)
        cancelled = threading.Event()
        task = asyncio.create_task(converter.render(wav(), "mita", "request", cancelled, "answer"))
        await worker.started.wait()
        cancelled.set()
        await converter.stop("request")
        with pytest.raises(ValueError): await task
        assert worker.kills == 1 and not converter.sessions
    asyncio.run(scenario())


def test_close_during_spawn_cannot_orphan_worker(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        converter, _ = runner(tmp_path, monkeypatch, worker)
        started, release = asyncio.Event(), asyncio.Event()
        async def spawn(*args, **kwargs):
            started.set()
            await release.wait()
            return worker
        monkeypatch.setattr("core.openvoice.asyncio.create_subprocess_exec", spawn)
        task = asyncio.create_task(converter.render(wav(), "mita", "request", threading.Event(), "answer"))
        await started.wait()
        await converter.close_session("answer")
        release.set()
        with pytest.raises(ValueError, match="остановлена"): await task
        assert worker.kills == 1 and not worker.payloads and not converter.sessions
    asyncio.run(scenario())


def test_task_cancellation_kills_conversion(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker(block=True)
        converter, _ = runner(tmp_path, monkeypatch, worker)
        task = asyncio.create_task(converter.render(wav(), "mita", "request", threading.Event(), "answer"))
        await worker.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert worker.kills == 1 and not converter.sessions
    asyncio.run(scenario())


def test_one_shot_releases_worker_immediately(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        converter, _ = runner(tmp_path, monkeypatch, worker)
        assert await converter.render(wav(), "custom", "request", threading.Event()) == wav()
        assert worker.kills == 1 and not converter.sessions
    asyncio.run(scenario())


def test_uploaded_reference_validated_and_cannot_write_arbitrary_path(tmp_path):
    converter = OpenVoice(tmp_path)
    for data in [b"invalid", wav()[:80], b"x" * (5 * 1024**2 + 1)]:
        with pytest.raises(ValueError): converter.save_reference(data)
    assert not converter.reference("custom").exists()
    converter.save_reference(wav())
    assert converter.reference("custom").read_bytes() == wav()
    assert next(row for row in converter.info()["references"] if row["id"] == "custom")["available"]
    with pytest.raises(ValueError): converter.reference("../../secrets")


def test_voice_settings_and_request_snapshot_select_converter(tmp_path, monkeypatch):
    instance = Voice(tmp_path)
    monkeypatch.setattr(instance.openvoice, "validate", lambda key: tmp_path / "reference.wav")
    monkeypatch.setattr(instance, "synthesize", lambda *args: wav())
    calls = []
    async def convert(audio, key, request_id, cancelled, session_id=None):
        calls.append((key, session_id))
        return audio
    monkeypatch.setattr(instance.openvoice, "render", convert)
    with patch("core.api.Voice", return_value=instance):
        with TestClient(create_app(tmp_path, "test-openvoice-token-0123456789"), headers={"Authorization": "Bearer test-openvoice-token-0123456789"}) as api:
            result = api.put("/settings/speech", json={"tts_engine": "piper", "openvoice_enabled": True, "openvoice_voice": "mita"})
            assert result.status_code == 200 and result.json()["openvoice_enabled"]
            payload = {"text": "Привет!", "session_id": "answer", "openvoice_voice": "kind-mita"}
            assert api.post("/voice/synthesize", json=payload).status_code == 200
            assert calls == [("kind-mita", "answer")]
            assert api.get("/settings").json()["openvoice_voice"] == "mita"
            assert api.post("/voice/synthesize", json=payload | {"openvoice_enabled": False}).status_code == 200
            assert len(calls) == 1
            assert api.delete("/voice/session/answer").status_code == 200
            assert api.post("/voice/openvoice/reference", files={"file": ("../custom.wav", wav(), "audio/wav")}).status_code == 200


@pytest.mark.skipif(os.environ.get("WILEYAI_OPENVOICE_TESTS") != "1", reason="Requires installed OpenVoice and local Piper/Silero weights")
def test_real_api_converts_both_local_engines_and_reuses_worker(tmp_path):
    instance = Voice(Path(__file__).resolve().parents[1] / "data")
    with patch("core.api.Voice", return_value=instance):
        with TestClient(create_app(tmp_path, "test-openvoice-native-0123456789"), headers={"Authorization": "Bearer test-openvoice-native-0123456789"}) as api:
            pids = []
            for index, (engine, key) in enumerate([("piper", "mita"), ("piper", "kind-mita"), ("silero_v5_6", "kind-mita")]):
                result = api.post("/voice/synthesize", json={"text": "Привет! Давай спокойно обсудим твои планы.", "engine": engine,
                    "voice": "irina" if engine == "piper" else "xenia", "openvoice_enabled": True, "openvoice_voice": key, "session_id": "native-answer"})
                assert result.status_code == 200, result.text[:200] if result.status_code != 200 else ""
                with wave.open(io.BytesIO(result.content), "rb") as audio:
                    assert audio.getframerate() == 22050 and audio.getsampwidth() == 2
                    assert 1 < audio.getnframes() / audio.getframerate() < 20
                    assert max(audio.readframes(audio.getnframes())) > 50
                pids.append(instance.openvoice.sessions["native-answer"].process.pid)
                output = Path(__file__).resolve().parents[1] / "local/voice-conversion"
                output.mkdir(parents=True, exist_ok=True)
                (output / f"app-{engine}-{key}.wav").write_bytes(result.content)
            assert len(set(pids)) == 1
            assert api.delete("/voice/session/native-answer").status_code == 200
            assert not instance.openvoice.sessions
