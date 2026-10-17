import asyncio
import json
import threading
import pytest

from core.qwen import QwenSpeech


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
            wav = b"RIFF" + b"0" * 4 + b"WAVE" + b"0" * 32
            self.stdout.feed_data(json.dumps({"size": len(wav), "device": "cpu"}).encode() + b"\n" + wav)

    async def drain(self): pass

    def kill(self):
        self.returncode = -9
        self.kills += 1
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self): return self.returncode


def runner(tmp_path, monkeypatch, worker):
    qwen = QwenSpeech(tmp_path)
    monkeypatch.setattr(qwen, "prepare", lambda speaker: None)
    launches = []
    async def spawn(*args, **kwargs):
        assert args[-1] == "--session"
        launches.append(args)
        return worker
    monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
    return qwen, launches


def test_model_reused_for_sentences_and_closed_with_answer(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        qwen, launches = runner(tmp_path, monkeypatch, worker)
        for index, text in enumerate(["Первая фраза.", "Вторая фраза."]):
            await qwen.stop(preserve_session="answer")
            audio = await qwen.render_session(text, "serena", "auto", str(index), threading.Event(), "answer")
            assert audio.startswith(b"RIFF") and audio.device == "cpu"
        assert len(launches) == 1
        assert [p["speaker"] for p in worker.payloads] == ["serena", "serena"]
        await qwen.stop("old-request")
        assert worker.kills == 0
        await qwen.close_session("answer")
        assert worker.kills == 1 and not qwen.sessions and not qwen.processes
    asyncio.run(scenario())


def test_stop_active_session_kills_worker_and_pending_audio(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker(block=True)
        qwen, _ = runner(tmp_path, monkeypatch, worker)
        cancelled = threading.Event()
        task = asyncio.create_task(qwen.render_session("Приватная фраза", "serena", "cpu", "request", cancelled, "answer"))
        await worker.started.wait()
        cancelled.set()
        await qwen.stop("request")
        with pytest.raises(ValueError): await task
        assert worker.kills == 1 and not qwen.sessions and not qwen.processes
    asyncio.run(scenario())


def test_close_during_spawn_cannot_leave_an_unregistered_worker(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        qwen, _ = runner(tmp_path, monkeypatch, worker)
        started, release = asyncio.Event(), asyncio.Event()
        async def spawn(*args, **kwargs):
            started.set()
            await release.wait()
            return worker
        monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
        task = asyncio.create_task(qwen.render_session("Не читать", "serena", "cpu", "request", threading.Event(), "answer"))
        await started.wait()
        await qwen.close_session("answer")
        release.set()
        with pytest.raises(ValueError, match="остановлена"): await task
        assert worker.kills == 1 and not worker.payloads and not qwen.processes and not qwen.sessions
    asyncio.run(scenario())


def test_idle_session_expires_and_later_stop_never_kills_another_answer(tmp_path, monkeypatch):
    async def scenario():
        worker = Worker()
        qwen, _ = runner(tmp_path, monkeypatch, worker)
        await qwen.render_session("Привет", "serena", "cpu", "request", threading.Event(), "answer")
        session = qwen.sessions["answer"]
        async def short_sleep(seconds): assert seconds == 30
        monkeypatch.setattr("core.qwen.asyncio.sleep", short_sleep)
        await session.idle
        assert worker.kills == 1 and not qwen.sessions
        await qwen.close_session("answer")
        assert worker.kills == 1
    asyncio.run(scenario())


def test_native_windows_crash_retries_once_with_same_voice_and_no_duplicate_audio(tmp_path, monkeypatch):
    async def scenario():
        failed, healthy = Worker(block=True), Worker()
        failed.returncode = 3221225477
        failed.stdout.feed_eof()
        failed.stderr.feed_eof()
        qwen, _ = runner(tmp_path, monkeypatch, failed)
        workers = iter([failed, healthy])
        async def spawn(*args, **kwargs): return next(workers)
        monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
        audio = await qwen.render_session("Привет!", "serena", "auto", "request", threading.Event(), "answer")
        assert audio.startswith(b"RIFF")
        assert [w.payloads[0]["speaker"] for w in [failed, healthy]] == ["serena", "serena"]
        assert qwen.error_log.is_file()
        await qwen.stop()
        assert healthy.kills == 1
    asyncio.run(scenario())


def test_second_native_crash_is_reported_and_no_workers_are_kept(tmp_path, monkeypatch):
    async def scenario():
        workers = [Worker(block=True), Worker(block=True)]
        for worker in workers:
            worker.returncode = 3221225477
            worker.stdout.feed_eof(); worker.stderr.feed_eof()
        qwen, _ = runner(tmp_path, monkeypatch, workers[0])
        launches = []
        async def spawn(*args, **kwargs):
            worker = workers[len(launches)]
            launches.append(worker)
            return worker
        monkeypatch.setattr("core.qwen.asyncio.create_subprocess_exec", spawn)
        with pytest.raises(ValueError, match="3221225477"):
            await qwen.render_session("Привет!", "serena", "cpu", "request", threading.Event(), "answer")
        assert len(launches) == 2 and not qwen.sessions and not qwen.processes
    asyncio.run(scenario())
