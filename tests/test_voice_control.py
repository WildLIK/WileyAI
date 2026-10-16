import asyncio
import hashlib
import threading
from types import SimpleNamespace

import pytest

from core.piper import Piper, VOICES
from core.voice import Voice, SpeechCancelled


def test_cancelled_synthesis_does_not_wait_for_busy_model(tmp_path):
    voice = Voice(tmp_path)
    cancel = threading.Event()
    cancel.set()
    voice.tts_lock.acquire()
    try:
        with pytest.raises(SpeechCancelled):
            voice.synthesize("Привет", "irina", cancel, "piper")
    finally:
        voice.tts_lock.release()


def test_cancelled_piper_does_not_generate_next_chunk_or_return_audio(tmp_path, monkeypatch):
    voice = Voice(tmp_path)
    cancel = threading.Event()
    calls = []
    class Model:
        def synthesize(self, text):
            calls.append(text)
            cancel.set()
            yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=b"00")
    monkeypatch.setattr(voice.piper, "load", lambda name: Model())
    with pytest.raises(SpeechCancelled):
        voice.synthesize("Привет. " * 200, "irina", cancel, "piper")
    assert len(calls) == 1
    assert voice.tts_lock.acquire(blocking=False)
    voice.tts_lock.release()


def test_scoped_stop_handles_early_and_late_cancellation(tmp_path, monkeypatch):
    async def scenario():
        voice = Voice(tmp_path)
        await voice.stop("early")
        with pytest.raises(SpeechCancelled):
            await voice.render("test", "", "piper", "early")
        started = threading.Event()
        finish = threading.Event()
        def synthesize(text, speaker, cancel, engine):
            started.set()
            while not finish.wait(0.01):
                if cancel.is_set():
                    raise SpeechCancelled("Остановлено")
            assert not cancel.is_set()
            return b"RIFFaudio"
        monkeypatch.setattr(voice, "synthesize", synthesize)
        task = asyncio.create_task(voice.render("text", "", "piper", "current"))
        assert await asyncio.to_thread(started.wait, 2)
        await voice.stop("previous")
        assert not voice.synthesis_jobs["current"].is_set()
        finish.set()
        assert await task == b"RIFFaudio"
        assert not voice.synthesis_jobs
    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["scoped", "global", "disconnect"])
def test_stop_cancels_worker_and_releases_request(tmp_path, monkeypatch, method):
    async def scenario():
        voice = Voice(tmp_path)
        started, stopped = threading.Event(), threading.Event()
        def synthesize(text, speaker, cancel, engine):
            started.set()
            assert cancel.wait(3)
            stopped.set()
            raise SpeechCancelled("Остановлено")
        monkeypatch.setattr(voice, "synthesize", synthesize)
        task = asyncio.create_task(voice.render("text", "", "piper", "current"))
        assert await asyncio.to_thread(started.wait, 2)
        if method == "disconnect":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await voice.stop("current" if method == "scoped" else None)
            with pytest.raises(SpeechCancelled):
                await task
        assert await asyncio.to_thread(stopped.wait, 2)
        assert not voice.synthesis_jobs
    asyncio.run(scenario())


def test_starting_new_render_cancels_previous_worker(tmp_path, monkeypatch):
    async def scenario():
        voice = Voice(tmp_path)
        started = threading.Event()
        def synthesize(text, speaker, cancel, engine):
            if text == "old":
                started.set()
                assert cancel.wait(3)
                raise SpeechCancelled("Остановлено")
            return b"RIFFnew"
        monkeypatch.setattr(voice, "synthesize", synthesize)
        old = asyncio.create_task(voice.render("old", "", "piper", "old"))
        assert await asyncio.to_thread(started.wait, 2)
        assert await voice.render("new", "", "piper", "new") == b"RIFFnew"
        with pytest.raises(SpeechCancelled):
            await old
    asyncio.run(scenario())


def test_sapi_cancelled_during_process_start_never_speaks(tmp_path, monkeypatch):
    async def scenario():
        voice = Voice(tmp_path)
        starting, release = asyncio.Event(), asyncio.Event()
        class Process:
            returncode = None
            killed = 0
            async def communicate(self, *args):
                raise AssertionError("Cancelled synthesis must not submit text to SAPI")
            def kill(self):
                self.killed += 1
                self.returncode = -9
            async def wait(self):
                return self.returncode
        process = Process()
        async def spawn(*args, **kwargs):
            starting.set()
            await release.wait()
            return process
        monkeypatch.setattr("core.voice.os", SimpleNamespace(name="nt"))
        monkeypatch.setattr("core.voice.asyncio.create_subprocess_exec", spawn)
        task = asyncio.create_task(voice.render("test", "", "sapi", "starting"))
        await starting.wait()
        await voice.stop("starting")
        release.set()
        with pytest.raises(SpeechCancelled):
            await task
        assert process.killed == 1
        assert voice.speech is None
    asyncio.run(scenario())


def test_piper_download_verifies_both_files_and_installs_atomically(tmp_path, monkeypatch):
    piper = Piper(tmp_path)
    monkeypatch.setattr(piper, "available", lambda: True)
    payloads = [b"onnx data", b'{"sample_rate":22050}']
    monkeypatch.setitem(VOICES, "irina", ("Ирина", *(hashlib.sha256(x).hexdigest() for x in payloads), "test"))
    class Stream:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self): yield self.payload
    def stream(method, url, **kwargs):
        assert "c10ece1" in url
        return Stream(payloads[1] if url.endswith(".json") else payloads[0])
    monkeypatch.setattr("core.piper.httpx.stream", stream)
    piper.download("irina")
    assert piper.installed("irina")
    assert sorted(x.name for x in piper.root.iterdir()) == ["irina"]
    assert (piper.folder("irina") / "ru_RU-irina-medium.onnx").read_bytes() == payloads[0]
    # Failed integrity checks never leave a voice that the UI considers installed.
    monkeypatch.setitem(VOICES, "denis", VOICES["irina"][:1] + ("0" * 64, "0" * 64, "test"))
    with pytest.raises(ValueError, match="Контрольная сумма"):
        piper.download("denis")
    assert not piper.installed("denis")
    assert sorted(x.name for x in piper.root.iterdir()) == ["irina"]


@pytest.mark.parametrize("name", ["../irina", "C:/Windows", "unknown"])
def test_piper_rejects_voices_outside_catalog(tmp_path, name):
    with pytest.raises(ValueError):
        Piper(tmp_path).folder(name)
