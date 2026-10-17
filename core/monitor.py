"""Bounded, read-only sampling. Never loads models or sends inference requests."""
from collections import deque
from contextlib import contextmanager
import asyncio
import csv
import ctypes
import io
import os
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

import httpx
import psutil


INTERVAL = 2
HISTORY = 300


def runs_module(command, module):
    return any(part == "-m" and command[index + 1] == module for index, part in enumerate(command[:-1]))


def row_state(busy, meta, group, unavailable=False):
    if busy:
        return "Работает"
    if meta.get("location") == "cloud":
        return "Удалённо"
    if meta.get("location") == "server":
        return "Внешний сервер"
    if meta.get("loaded") or group["items"]:
        return "Простой"
    return "Нет данных" if unavailable else "Не загружена"


def commit_memory():
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class Performance(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable",
            "SystemCache", "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize",
        )] + [(name, wintypes.DWORD) for name in ("HandleCount", "ProcessCount", "ThreadCount")]

    info = Performance()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        return None
    return {"used": info.CommitTotal * info.PageSize, "total": info.CommitLimit * info.PageSize}


def gpu_snapshot():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"devices": [], "processes": {}, "note": "Метрики NVIDIA недоступны; мониторинг CPU и ОЗУ работает."}
    options = {"capture_output": True, "text": True, "timeout": 2, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run([executable, "--query-gpu=index,name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"], **options)
        devices = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) == 5:
                devices.append({"name": row[1].strip(), "percent": float(row[2]),
                                "used": int(float(row[3]) * 1024**2), "total": int(float(row[4]) * 1024**2)})
        processes = {}
        result = subprocess.run([executable, "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"], **options)
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) == 2 and row[0].strip().isdigit() and row[1].strip().replace(".", "", 1).isdigit():
                pid = int(row[0])
                processes[pid] = processes.get(pid, 0) + int(float(row[1]) * 1024**2)
        return {"devices": devices, "processes": processes,
                "note": "GPU — весь компьютер. В Windows драйвер может не сообщать видеопамять отдельных процессов."}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"devices": [], "processes": {}, "note": "Драйвер не предоставил метрики GPU."}


def process_metrics(process, previous, now, cores):
    """PID + creation time prevents attributing an exited process's CPU to a new one."""
    with process.oneshot():
        identity = (process.pid, process.create_time())
        times = process.cpu_times()
        cpu = times.user + times.system
        memory = process.memory_info()
    old = previous.get(identity)
    percent = None if not old or now <= old[0] else max(0, min(100, (cpu - old[1]) / (now - old[0]) * 100 / cores))
    return identity, (now, cpu), {"cpu": percent, "ram": memory.rss, "private": getattr(memory, "private", None)}


def add_metrics(items):
    return {key: sum(item[key] for item in items) if items and all(item[key] is not None for item in items) else None
            for key in ("cpu", "ram", "private", "vram")}


class Monitor:
    def __init__(self, store, voice):
        self.store, self.voice = store, voice
        self.lock = threading.Lock()
        self.active = {}
        self.touched = set()
        self.calls = {}
        self.metadata = {}
        self.previous = {}
        self.history = deque(maxlen=HISTORY)
        self.statistics = {}
        self.started = time.time()
        self.latest = None
        self.system_cpu = None
        self.sampled_at = None
        self.gpu = {"devices": [], "processes": {}, "note": "Ожидаю данные драйвера…"}
        self.ollama = {"models": [], "error": None, "local": True, "url": ""}
        self.optional_at = 0
        self.external = []
        self.external_url = ""
        self.cores = psutil.cpu_count() or 1
        self.core = psutil.Process()
        self.desktop = None
        try:
            pid = int(os.environ.get("WILEYAI_DESKTOP_PID", "0"))
            if pid and pid in {p.pid for p in self.core.parents()}:
                self.desktop = psutil.Process(pid)
        except (ValueError, psutil.Error):
            pass

    @contextmanager
    def activity(self, key, metadata=None):
        began = time.monotonic()
        with self.lock:
            self.active[key] = self.active.get(key, 0) + 1
            self.touched.add(key)
            if metadata:
                self.metadata[key] = metadata
                if len(self.metadata) > 64:
                    self.metadata.pop(next(iter(self.metadata)))
        try:
            yield
        finally:
            with self.lock:
                self.touched.add(key)
                self.active[key] -= 1
                if not self.active[key]:
                    del self.active[key]
                old = self.calls.get(key, {"count": 0, "seconds": 0})
                self.calls[key] = {"count": old["count"] + 1, "seconds": old["seconds"] + time.monotonic() - began}
                if len(self.calls) > 64:
                    self.calls.pop(next(iter(self.calls)))

    def call(self, key, function, *args):
        # Enclose the actual native work even if its HTTP caller disconnects.
        with self.activity(key):
            return function(*args)

    async def ollama_snapshot(self):
        config = self.store.settings()
        local = urlparse(config.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
        result = {"models": [], "local": local, "error": None, "url": config.base_url}
        if config.provider == "ollama" and local:
            try:
                async with httpx.AsyncClient(timeout=1, trust_env=False) as http:
                    response = await http.get(config.base_url + "/api/ps")
                    response.raise_for_status()
                    payload = response.json()
                    models = payload.get("models", []) if isinstance(payload, dict) else []
                    if not isinstance(models, list):
                        raise ValueError("Invalid model list")
                    result["models"] = [item for item in models[:32] if isinstance(item, dict) and isinstance(item.get("name"), str)]
            except (httpx.HTTPError, ValueError, TypeError):
                result["error"] = "Список загруженных моделей Ollama недоступен."
        self.ollama = result

    def owned_processes(self):
        root = self.desktop or self.core
        try:
            return [root, *root.children(recursive=True)]
        except psutil.Error:
            return [self.core]

    def external_ollama(self):
        """Inspect only the listener at the configured loopback port and its children."""
        config = self.store.settings()
        if config.provider != "ollama" or not self.ollama["local"] or self.ollama["error"]:
            return []
        url = urlparse(config.base_url)
        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            for connection in psutil.net_connections(kind="tcp"):
                if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port and connection.pid:
                    process = psutil.Process(connection.pid)
                    # A custom reverse proxy is not an Ollama process tree.
                    if process.name().lower() in {"ollama.exe", "ollama"}:
                        return [process, *process.children(recursive=True)]
        except (psutil.Error, OSError):
            pass
        return []

    def record_statistics(self, row, working, duration):
        key = row["id"]
        if key not in self.statistics and len(self.statistics) >= 64:
            self.statistics.pop(next(iter(self.statistics)))
        stats = self.statistics.setdefault(key, {})
        phase = "work" if working else "idle"
        summary = stats.setdefault(phase, {"seconds": 0, "cpu_seconds": 0, "cpu_sum": 0, "ram_peak": None, "private_peak": None})
        summary["seconds"] += duration
        if row["cpu"] is not None:
            summary["cpu_seconds"] += duration
            summary["cpu_sum"] += row["cpu"] * duration
        for metric in ("ram", "private"):
            if row[metric] is not None:
                summary[metric + "_peak"] = max(summary[metric + "_peak"] or 0, row[metric])
        return {phase: {"seconds": values["seconds"],
                        "cpu": values["cpu_sum"] / values["cpu_seconds"] if values["cpu_seconds"] else None,
                        "ram_peak": values["ram_peak"], "private_peak": values["private_peak"]}
                for phase, values in stats.items()}

    def sample(self):
        now = time.monotonic()
        duration = now - self.sampled_at if self.sampled_at is not None else 0
        self.sampled_at = now
        config = self.store.settings()
        with self.lock:
            active, calls = dict(self.active), dict(self.calls)
            metadata = dict(self.metadata)
            touched = self.touched | active.keys()
            self.touched.clear()
        qwen_pids = {p.pid for p in list(self.voice.qwen.processes.values()) if p.returncode is None}
        qwen_pids.update(s.process.pid for s in list(self.voice.qwen.sessions.values()) if s.process and s.process.returncode is None)
        sapi_pid = self.voice.speech.pid if self.voice.speech and self.voice.speech.returncode is None else None
        owned = self.owned_processes()
        owned_ids = {p.pid for p in owned}
        # /api/ps describes all models on a possibly shared Ollama server.
        loaded = self.ollama["models"] if config.provider == "ollama" and self.ollama["url"] == config.base_url else []
        groups = {}
        new_previous = {}
        app_items = []
        desktop_name = self.desktop.name().lower() if self.desktop else ""
        external = self.external if config.provider == "ollama" and config.base_url == self.external_url else []
        for process in {p.pid: p for p in [*owned, *external]}.values():
            try:
                if hasattr(process, "is_running") and not process.is_running():
                    continue
                name = process.name().lower()
                command = process.cmdline()
                key = "core" if process.pid == self.core.pid else "desktop" if desktop_name and name == desktop_name else "services"
                if process.pid in qwen_pids or runs_module(command, "core.qwen_worker"):
                    key = "tts:qwen3"
                elif process.pid == sapi_pid:
                    key = "tts:sapi"
                elif name in {"ollama.exe", "ollama", "llama-server.exe", "llama-server"}:
                    key = "ollama"
                    for model in loaded:
                        digest = str(model.get("digest", "")).split(":")[-1]
                        if len(digest) >= 12 and any(digest in arg for arg in command):
                            key = "brain:" + model["name"]
                            break
                elif key == "services" and not (
                    runs_module(command, "core.process_guard") or runs_module(command, "core")
                    or any(part.startswith("--type=crashpad-handler") for part in command)
                    or (name in {"powershell.exe", "pwsh.exe"} and "-NonInteractive" in command)
                ):
                    # Opening an application does not make it part of WileyAI.
                    continue
                if process.pid not in owned_ids and key not in {"ollama", *("brain:" + m["name"] for m in loaded)}:
                    continue
                identity, previous, metrics = process_metrics(process, self.previous, now, self.cores)
                new_previous[identity] = previous
                metrics["vram"] = self.gpu["processes"].get(process.pid)
                if process.pid in owned_ids:
                    app_items.append(metrics)
                group = groups.setdefault(key, {"items": [], "pids": [], "external": False})
                group["items"].append(metrics)
                group["pids"].append(process.pid)
                group["external"] |= process.pid not in owned_ids
            except (psutil.Error, OSError):
                continue
        self.previous = new_previous
        local = urlparse(config.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
        models = {"brain:" + config.model: {"name": config.model, "category": "Мозг", "loaded": False,
                  "location": "cloud" if not local else "server" if config.provider == "compatible" else "local"}}
        for item in loaded:
            models["brain:" + item["name"]] = {"name": item["name"], "category": "Мозг", "loaded": True,
                                                "location": "local", "allocation": item.get("size_vram")}
        tts_names = {"silero": "Silero v5", "silero_v5_6": "Silero v5.6", "piper": "Piper", "sapi": "Голос Windows", "qwen3": "Qwen3-TTS"}
        tts_loaded = {"qwen3": bool(qwen_pids or groups.get("tts:qwen3")), "sapi": bool(sapi_pid)}
        if self.voice.tts_model is not None:
            tts_loaded["silero_v5_6" if self.voice.tts_version == "v5_6_ru" else "silero"] = True
        if self.voice.piper.model is not None:
            tts_loaded["piper"] = True
        used_tts = {key[4:] for key in calls.keys() | active.keys() if key.startswith("tts:")}
        for engine in {*(key for key, value in tts_loaded.items() if value), config.tts_engine, *used_tts}:
            if engine == "cloud":
                continue
            models["tts:" + engine] = {"name": tts_names[engine], "category": "Озвучка", "loaded": tts_loaded.get(engine, False),
                                       "shared": "core" if engine.startswith("silero") or engine == "piper" else None}
        used_stt = {key[4:] for key in calls.keys() | active.keys() if key.startswith("stt:")}
        for model in {*self.voice.models, config.stt_model, *used_stt}:
            models["stt:" + model] = {"name": "Whisper " + model, "category": "Распознавание голоса", "loaded": model in self.voice.models, "shared": "core"}
        if config.tts_engine == "cloud":
            models["cloud_tts:" + config.tts_service + ":" + config.tts_model] = {"name": config.tts_model, "category": "Озвучка", "location": "cloud"}
        models.update(metadata)
        rows = []
        for key in dict.fromkeys(["desktop", "core", "services", "ollama", *models, *active]):
            group = groups.get(key, {"items": [], "pids": [], "external": False})
            if key not in models and not group["items"] and key not in active:
                continue
            meta = models.get(key, {"name": {"desktop": "Интерфейс и аватар", "core": "Ядро и общие модели", "services": "Службы WileyAI", "ollama": "Сервер Ollama"}.get(key, key), "category": "Программа"})
            if key in models:
                busy, working = key in active, key in touched
            elif key == "ollama":
                busy = any(k.startswith("brain:") for k in active)
                working = any(k.startswith("brain:") for k in touched)
            else:
                busy, working = bool(active), bool(touched)
            row = {"id": key, **meta, **add_metrics(group["items"]), "pids": group["pids"], "external": group["external"],
                   "active": busy, "calls": calls.get(key), "state": row_state(busy, meta, group, key.startswith("brain:") and self.ollama["error"])}
            row["statistics"] = self.record_statistics(row, working, duration)
            rows.append(row)
        total = {"id": "app", "active": bool(active), **add_metrics(app_items)}
        total["statistics"] = self.record_statistics(total, bool(touched), duration)
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_times()
        times = (sum(cpu), cpu.idle + getattr(cpu, "iowait", 0))
        system_cpu = None
        if self.system_cpu and times[0] > self.system_cpu[0]:
            system_cpu = max(0, min(100, (1 - (times[1] - self.system_cpu[1]) / (times[0] - self.system_cpu[0])) * 100))
        self.system_cpu = times
        point = {"time": time.time(), "cpu": total["cpu"], "ram": total["ram"], "active": bool(touched)}
        self.history.append(point)
        while self.history and self.history[0]["time"] < point["time"] - 600:
            self.history.popleft()
        return {"time": point["time"], "started": self.started, "interval": INTERVAL, "cores": self.cores,
                "app": total, "system": {"cpu": system_cpu, "ram_used": memory.total - memory.available, "ram_total": memory.total, "commit": commit_memory()},
                "gpu": {"devices": self.gpu["devices"], "note": self.gpu["note"]}, "rows": rows,
                "history": list(self.history), "ollama_note": self.ollama["error"]}

    async def run(self):
        while True:
            began = time.monotonic()
            if began - self.optional_at >= 6:
                self.optional_at = began
                gpu, _ = await asyncio.gather(asyncio.to_thread(gpu_snapshot), self.ollama_snapshot())
                self.gpu = gpu
                self.external = await asyncio.to_thread(self.external_ollama)
                self.external_url = self.ollama["url"]
            try:
                self.latest = await asyncio.to_thread(self.sample)
            except (psutil.Error, OSError):
                pass  # A process may disappear during a sample; retain the last good snapshot.
            await asyncio.sleep(max(.1, INTERVAL - (time.monotonic() - began)))
