"""Optional local model evaluation in an isolated project; no personal task writes."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from zoneinfo import ZoneInfo
from unittest.mock import patch

import httpx
import psutil
import pytest

from core.storage import Store
from core import task_intents


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TASKS") != "1", reason="Requires the installed local conversation model")
def test_real_local_model_task_dates_and_catalog_selection(tmp_path):
    root = Path(__file__).resolve().parents[1]
    settings = Store(root / "data").settings()
    if settings.provider != "ollama": pytest.skip("This evaluation never uses a paid cloud model")
    executable = root / "local/ollama/ollama.exe"
    if not executable.is_file(): pytest.skip("No portable local Ollama engine installed")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
    settings = settings.model_copy(update={"base_url": f"http://127.0.0.1:{port}"})
    process = subprocess.Popen([str(executable), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(root / "data/models/ollama"), "OLLAMA_NO_CLOUD": "1", "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        with httpx.Client(trust_env=False, timeout=1) as http:
            for _ in range(50):
                try:
                    if http.get(settings.base_url + "/api/version").is_success: break
                except httpx.HTTPError: pass
                time.sleep(.1)
        _evaluate(tmp_path, settings)
    finally:
        parent = psutil.Process(process.pid)
        assert Path(parent.exe()).resolve() == executable.resolve()
        children = parent.children(recursive=True)
        for child in [*children, parent]:
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs([*children, parent], timeout=4)
        process.wait(timeout=5)


def _evaluate(tmp_path, settings):
    store = Store(tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    zone = "Asia/Yekaterinburg"
    original = store.save_task("оплатить интернет", "reminder", "2026-10-20T05:00:00+00:00")
    cases = [
        ("Не забудь напомнить мне завтра к полудню оплатить интернет", "create", "2026-10-19", 12),
        ("Отложи задачу про оплату интернета на следующую среду к полудню", "move", "2026-10-21", 12),
    ]
    results = []
    structured_call = task_intents.providers.structured
    async def observed(*args, **kwargs):
        raw = await structured_call(*args, **kwargs)
        print("Isolated model decision:", raw, flush=True)
        return raw
    for phrase, action, day, hour in cases:
        with patch.object(task_intents.providers, "structured", observed):
            outcome = asyncio.run(task_intents.propose(store, settings, phrase, zone, now))
        results.append({"request": phrase, "answer": outcome.text, "plan": outcome.plan.model_dump() if outcome.plan else None})
        assert outcome.plan is not None and outcome.plan.decision.action == action, results
        due = datetime.fromisoformat(outcome.plan.due).astimezone(ZoneInfo(zone))
        assert due.date().isoformat() == day and due.hour == hour and due.minute == 0, results
        if action == "move": assert outcome.plan.decision.candidates == [original["id"]], results
    assert len(store.list("tasks")) == 1 and store.task(original["id"])["due"] == original["due"]
    print(json.dumps({"model": settings.model, "results": results}, ensure_ascii=False))
