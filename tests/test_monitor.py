import asyncio
from contextlib import nullcontext
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient
import httpx
import psutil
import pytest

from core.api import create_app
from core.config import Settings
from core.monitor import Monitor, HISTORY, process_metrics, gpu_snapshot
from core.storage import Store
from core.voice import Voice


class Process:
    def __init__(self, pid, name="python.exe", command=(), created=1, cpu=0, rss=100, private=60):
        self.pid, self.title, self.command = pid, name, command
        self.created, self.cpu, self.rss, self.private = created, cpu, rss, private

    def oneshot(self): return nullcontext()
    def create_time(self): return self.created
    def cpu_times(self): return NS(user=self.cpu, system=0)
    def memory_info(self): return NS(rss=self.rss, private=self.private)
    def name(self): return self.title
    def cmdline(self): return self.command


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monitor = Monitor(store, Voice(tmp_path))
    core = Process(monitor.core.pid)
    monkeypatch.setattr(monitor, "owned_processes", lambda: [core])
    return monitor


def test_cpu_uses_machine_capacity_and_pid_creation_time():
    process = Process(10, cpu=2)
    identity, baseline, first = process_metrics(process, {}, 10, 4)
    assert first["cpu"] is None
    process.cpu = 4
    _, _, measured = process_metrics(process, {identity: baseline}, 12, 4)
    assert measured["cpu"] == 25
    process.created = 2
    assert process_metrics(process, {identity: baseline}, 12, 4)[2]["cpu"] is None


def test_activity_finally_keeps_work_and_idle_distinct_and_shared_memory_honest(monitor):
    monitor.voice.models["small"] = object()
    monitor.voice.tts_model = object()
    monitor.voice.tts_version = "v5_ru"
    with pytest.raises(ValueError), monitor.activity("tts:silero"):
        first = monitor.sample()
        assert first["app"]["active"]
        row = next(row for row in first["rows"] if row["id"] == "tts:silero")
        assert row["state"] == "Работает" and row["shared"] == "core"
        assert row["ram"] is None and row["cpu"] is None
        raise ValueError("cancelled")
    result = monitor.sample()
    assert not result["app"]["active"]
    # An interval containing the end of an operation still belongs to work.
    result = monitor.sample()
    assert set(result["app"]["statistics"]) == {"work", "idle"}
    row = next(row for row in result["rows"] if row["id"] == "tts:silero")
    assert row["calls"]["count"] == 1 and row["state"] == "Простой"
    assert not monitor.active


def test_qwen_and_external_llm_measured_once_without_counting_shared_server_as_app(monitor, monkeypatch):
    qwen = Process(221, rss=700, private=600)
    core = Process(monitor.core.pid, rss=100, private=60)
    runner = Process(222, name="llama-server.exe", command=["llama-server", "--model", "sha256-" + "a" * 64], rss=900)
    monitor.voice.qwen.processes["request"] = NS(pid=qwen.pid, returncode=None)
    monitor.store.save_settings(Settings(model="test-model"))
    monitor.ollama.update(url=monitor.store.settings().base_url, models=[{"name": "test-model", "digest": "sha256:" + "a" * 64, "size_vram": 1000}])
    monitor.external = [runner]
    monitor.external_url = monitor.store.settings().base_url
    monitor.gpu["processes"][qwen.pid] = 300
    monkeypatch.setattr(monitor, "owned_processes", lambda: [core, qwen])
    snapshot = monitor.sample()
    assert snapshot["app"]["ram"] == 800
    assert snapshot["app"]["private"] == 660
    rows = {row["id"]: row for row in snapshot["rows"]}
    assert rows["tts:qwen3"]["ram"] == 700
    assert rows["tts:qwen3"]["vram"] == 300
    assert rows["brain:test-model"]["external"]
    assert rows["brain:test-model"]["ram"] == 900
    assert rows["brain:test-model"]["allocation"] == 1000
    # Stale cached processes must not follow a switch to another endpoint.
    monitor.store.save_settings(Settings(provider="compatible", base_url="https://example.com", model="cloud"))
    snapshot = monitor.sample()
    assert all(222 not in row["pids"] for row in snapshot["rows"])
    assert next(row for row in snapshot["rows"] if row["id"] == "brain:cloud")["state"] == "Удалённо"


def test_history_is_bounded_and_missing_gpu_is_not_zero(monitor, monkeypatch):
    monkeypatch.setattr("core.monitor.shutil.which", lambda _: None)
    assert gpu_snapshot()["devices"] == []
    for _ in range(HISTORY + 5):
        snapshot = monitor.sample()
    assert len(snapshot["history"]) == HISTORY
    assert snapshot["app"]["vram"] is None


def test_short_work_between_samples_is_not_misclassified_as_idle(monitor):
    monitor.sample()
    with monitor.activity("stt:tiny"):
        pass
    snapshot = monitor.sample()
    assert not snapshot["app"]["active"]
    assert snapshot["history"][-1]["active"]
    row = next(row for row in snapshot["rows"] if row["id"] == "stt:tiny")
    # Windows monotonic time can return the same tick for these instant fake
    # samples. Classification must remain work even for a zero-duration tick.
    assert "work" in row["statistics"] and "idle" not in row["statistics"]
    assert row["calls"]["count"] == 1
    assert not monitor.sample()["history"][-1]["active"]


def test_exiting_process_does_not_break_sampling(monitor, monkeypatch):
    class Exited(Process):
        def name(self): raise psutil.NoSuchProcess(self.pid)
    monkeypatch.setattr(monitor, "owned_processes", lambda: [Process(monitor.core.pid), Exited(213)])
    assert monitor.sample()["app"]["ram"] == 100


def test_qwen_interpreter_child_belongs_to_model_and_opened_apps_are_excluded(monitor, monkeypatch):
    wrapper = Process(211, rss=20, command=["python", "-m", "core.qwen_worker"])
    worker = Process(212, rss=2500, command=["python", "-m", "core.qwen_worker", "--session"])
    opened_app = Process(213, name="notepad.exe", rss=150)
    core = Process(monitor.core.pid, rss=100)
    monitor.voice.qwen.processes["active"] = NS(pid=wrapper.pid, returncode=None)
    monkeypatch.setattr(monitor, "owned_processes", lambda: [core, wrapper, worker, opened_app])
    snapshot = monitor.sample()
    row = next(row for row in snapshot["rows"] if row["id"] == "tts:qwen3")
    assert row["ram"] == 2520 and set(row["pids"]) == {211, 212}
    assert snapshot["app"]["ram"] == 2620
    assert all(213 not in row["pids"] for row in snapshot["rows"])


def test_monitor_queries_only_loopback_ollama_ps_and_never_inference(monitor, monkeypatch):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "resident", "size_vram": 123}]})
    original = httpx.AsyncClient
    monkeypatch.setattr("core.monitor.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    asyncio.run(monitor.ollama_snapshot())
    assert requests == ["http://127.0.0.1:11434/api/ps"]
    assert monitor.ollama["models"][0]["name"] == "resident"
    monitor.store.save_settings(Settings(base_url="https://example.com"))
    asyncio.run(monitor.ollama_snapshot())
    assert len(requests) == 1


def test_monitor_api_auth_cache_and_compact_payload(tmp_path, monkeypatch):
    token = "test-monitor-session-0123456789abcdef"
    async def run(self):
        self.latest = {"time": 1, "app": {"ram": 123}, "rows": [], "history": []}
    monkeypatch.setattr(Monitor, "run", run)
    with TestClient(create_app(tmp_path, token)) as api:
        assert api.get("/monitor").status_code == 401
        result = api.get("/monitor", headers={"Authorization": "Bearer " + token})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        compact = api.get("/monitor?compact=true", headers={"Authorization": "Bearer " + token}).json()
        assert "rows" not in compact and "history" not in compact
        assert compact["app"]["ram"] == 123


def test_cancelled_native_tts_remains_active_until_thread_finishes(tmp_path, monkeypatch):
    import threading
    monitor = Monitor(Store(tmp_path), Voice(tmp_path))
    monitor.voice.monitor = monitor
    entered, finish = threading.Event(), threading.Event()
    def synthesize(*args):
        entered.set()
        finish.wait(3)
        return b"RIFF"
    monkeypatch.setattr(monitor.voice, "synthesize", synthesize)
    async def scenario():
        task = asyncio.create_task(monitor.voice.render("hello", "baya", "silero"))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert monitor.active == {"tts:silero": 1}
        finally:
            finish.set()
        for _ in range(100):
            if not monitor.active: break
            await asyncio.sleep(.01)
        assert not monitor.active
        assert monitor.calls["tts:silero"]["count"] == 1
    asyncio.run(scenario())
