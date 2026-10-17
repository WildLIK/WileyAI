import asyncio
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from core.qwen import QwenSpeech
from core.qwen_worker import select_device


def test_runtime_and_model_checks_are_local_and_explicit(tmp_path):
    qwen = QwenSpeech(tmp_path)
    qwen.python = tmp_path / "runtime" / "python.exe"
    qwen.package = tmp_path / "runtime" / "qwen_tts"
    with pytest.raises(ValueError, match="setup:qwen"):
        qwen.prepare()
    qwen.python.parent.mkdir()
    qwen.python.touch()
    qwen.package.mkdir()
    (qwen.package / "__init__.py").touch()
    with pytest.raises(ValueError, match="Скачайте"):
        qwen.prepare()


def test_download_is_pinned_verified_and_resumes_complete_files(tmp_path, monkeypatch):
    payloads = {"config.json": b'{}', "model.safetensors": b"model"}
    manifest = {"repo": "Qwen/test", "revision": "pinned", "files": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in payloads.items()]}
    monkeypatch.setattr("core.qwen.MANIFEST", manifest)
    qwen = QwenSpeech(tmp_path)
    qwen.root.mkdir(parents=True)
    (qwen.root / "config.json").write_bytes(payloads["config.json"])
    calls = []
    class Stream:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self, *args): yield self.data
    def stream(method, url, **kwargs):
        calls.append(url)
        assert "/resolve/pinned/" in url
        return Stream(payloads[url.rsplit("/", 1)[-1]])
    monkeypatch.setattr("core.qwen.httpx.stream", stream)
    qwen.download()
    assert len(calls) == 1 and qwen.installed()
    (qwen.root / "model.safetensors").write_bytes(b"truncated")
    payloads["model.safetensors"] = b"bad"
    with pytest.raises(ValueError, match="Контрольная сумма"):
        qwen.download()
    assert not qwen.installed()
    assert not list(qwen.root.glob("*.part"))


class FakeProcess:
    returncode = None
    def __init__(self, audio=b"RIFF1234WAVEaudio", error=b"", code=0, wait=False):
        self.audio, self.error, self.code = audio, error, code
        self.pending = wait
        self.kills = 0
        self.payload = None
        self.started = asyncio.Event()
        self.released = asyncio.Event()
    async def communicate(self, data):
        self.payload = json.loads(data)
        self.started.set()
        if self.pending:
            await self.released.wait()
        if self.returncode is None:
            self.returncode = self.code
        return self.audio, self.error
    def kill(self):
        self.kills += 1
        self.returncode = -9
        self.released.set()
    async def wait(self): return self.returncode


def setup_runner(tmp_path, monkeypatch, process):
    qwen = QwenSpeech(tmp_path)
    monkeypatch.setattr(qwen, "prepare", lambda speaker: None)
    async def spawn(*args, **kwargs):
        assert args[1:3] == ("-m", "core.qwen_worker")
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["stdin"] == asyncio.subprocess.PIPE
        return process
    monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
    return qwen


def test_worker_receives_json_and_returns_wav_without_network(tmp_path, monkeypatch):
    async def scenario():
        process = FakeProcess(error=b"WILEY_DEVICE:cpu\n")
        qwen = setup_runner(tmp_path, monkeypatch, process)
        audio = await qwen.render("Привет", "serena", "cpu", "test", threading.Event())
        assert audio == process.audio and audio.device == "cpu"
        assert process.payload == {"text": "Привет", "speaker": "serena"}
        assert not qwen.processes and not process.kills
    asyncio.run(scenario())


@pytest.mark.parametrize("audio,error,code,expected", [
    (b"not-wav", b"", 0, "WAV"),
    (b"", "WILEY_ERROR:Недостаточно видеопамяти\ntraceback".encode(), 1, "Недостаточно видеопамяти"),
    (b"", b"private-diagnostic-trace", 1, "завершился с кодом 1"),
    (b"", b"native error", -1073741819, "-1073741819"),
])
def test_worker_errors_are_reported_without_corrupt_audio(tmp_path, monkeypatch, audio, error, code, expected):
    async def scenario():
        process = FakeProcess(audio, error, code)
        qwen = setup_runner(tmp_path, monkeypatch, process)
        with pytest.raises(ValueError, match=expected):
            await qwen.render("Привет", "", "auto", "test", threading.Event())
        assert not qwen.processes
        if code:
            diagnostic = json.loads(qwen.error_log.read_text(encoding="utf-8"))
            assert diagnostic["exit_code"] == code
            assert diagnostic["device"] == "auto"
            assert "Привет" not in diagnostic["stderr"]
    asyncio.run(scenario())


def test_worker_diagnostics_redact_spoken_text_fragments(tmp_path, monkeypatch):
    from core.speech_text import speech_chunks
    async def scenario():
        text = "Личный факт владельца. " * 30
        fragment = speech_chunks(text)[0]
        process = FakeProcess(error=("diagnostic: " + fragment).encode("utf-8"), code=1)
        qwen = setup_runner(tmp_path, monkeypatch, process)
        with pytest.raises(ValueError):
            await qwen.render(text, "serena", "cpu", "test", threading.Event())
        saved = qwen.error_log.read_text(encoding="utf-8")
        assert "Личный факт" not in saved and "[текст скрыт]" in saved
    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["button", "disconnect"])
def test_interrupt_kills_owned_worker_and_releases_it(tmp_path, monkeypatch, stop):
    async def scenario():
        process = FakeProcess(wait=True)
        qwen = setup_runner(tmp_path, monkeypatch, process)
        cancel = threading.Event()
        task = asyncio.create_task(qwen.render("Привет", "", "cpu", "current", cancel))
        await process.started.wait()
        await qwen.stop("old")
        assert process.kills == 0
        if stop == "button":
            cancel.set()
            await qwen.stop("current")
            with pytest.raises(ValueError, match="остановлена"):
                await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert process.kills == 1
        assert not qwen.processes
    asyncio.run(scenario())


def test_stop_while_spawning_never_submits_text(tmp_path, monkeypatch):
    async def scenario():
        process = FakeProcess()
        qwen = setup_runner(tmp_path, monkeypatch, process)
        started, release = asyncio.Event(), asyncio.Event()
        async def spawn(*args, **kwargs):
            started.set()
            await release.wait()
            return process
        monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
        cancel = threading.Event()
        task = asyncio.create_task(qwen.render("Привет", "", "auto", "test", cancel))
        await started.wait()
        cancel.set()
        release.set()
        with pytest.raises(ValueError, match="остановлена"): await task
        assert process.payload is None and process.kills == 1
    asyncio.run(scenario())


def test_worker_timeout_kills_process_and_releases_registry(tmp_path, monkeypatch):
    async def scenario():
        process = FakeProcess(wait=True)
        qwen = setup_runner(tmp_path, monkeypatch, process)
        original_wait = asyncio.wait_for
        async def fast_timeout(awaitable, timeout):
            assert timeout == 300
            return await original_wait(awaitable, timeout=0.01)
        monkeypatch.setattr("core.qwen.asyncio.wait_for", fast_timeout)
        with pytest.raises(ValueError, match="5 минут"):
            await qwen.render("Привет", "serena", "cpu", "test", threading.Event())
        assert process.kills == 1 and not qwen.processes
    asyncio.run(scenario())


@pytest.mark.parametrize("available,free,requested,expected", [
    (True, 5_000_000_000, "auto", "cuda"),
    (False, 0, "auto", "cpu"),
    (True, 1_000_000_000, "cpu", "cpu"),
    (True, 1_000_000_000, "cuda", "3,5 ГБ"),
    (True, 1_000_000_000, "auto", "cpu"),
    (False, 0, "cuda", "CUDA недоступна"),
])
def test_auto_uses_available_resources_but_explicit_cuda_reports_insufficient_memory(available, free, requested, expected):
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available, mem_get_info=lambda: (free, 8_000_000_000)))
    if expected in {"cpu", "cuda"}:
        assert select_device(torch, requested) == expected
    else:
        with pytest.raises(ValueError, match=expected):
            select_device(torch, requested)


@pytest.mark.parametrize("device", ["auto", "cuda"])
def test_cuda_initialization_failure_falls_back_only_for_auto(device):
    def failed():
        raise RuntimeError("CUDA initialization failed")
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, mem_get_info=failed))
    if device == "auto":
        assert select_device(torch, device) == "cpu"
    else:
        with pytest.raises(ValueError, match="Не удалось подготовить CUDA"):
            select_device(torch, device)
