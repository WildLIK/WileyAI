"""Optional local-model acceptance on synthetic records; no account or PC actions."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx
import psutil
import pytest

from core import action_plans
from core.config import Settings
from core.storage import Store


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_PLANS") != "1", reason="Requires installed local 4B model")
def test_real_local_model_mixed_plan_and_calendar(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    executable = root / "local/ollama/ollama.exe"
    manifest = root / "data/models/ollama/manifests/registry.ollama.ai/huihui_ai/qwen3.5-abliterated/4b"
    if not executable.is_file() or not manifest.is_file(): pytest.skip("Local engine and model not installed")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
    settings = Settings(provider="ollama", base_url=f"http://127.0.0.1:{port}", model="huihui_ai/qwen3.5-abliterated:4b", context_tokens=4096, response_tokens=2048, profile="eco")
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
        store = Store(tmp_path)
        structured = action_plans.providers.structured
        async def observed(*args, **kwargs):
            raw = await structured(*args, **kwargs)
            print(json.dumps({"model_decision": raw}, ensure_ascii=True), flush=True)
            return raw
        monkeypatch.setattr(action_plans.providers, "structured", observed)
        now = datetime(2026, 10, 20, 13, tzinfo=timezone.utc)
        phrase = "Напомни завтра в 10 оплатить интернет; запиши заметку Документы: забрать паспорт"
        outcome = asyncio.run(action_plans.propose(store, settings, phrase, "Asia/Yekaterinburg", now))
        print(json.dumps({"request": phrase, "answer": outcome.text}, ensure_ascii=True), flush=True)
        assert outcome.plan is not None and len(outcome.plan.steps) == 2, outcome.text
        assert [step.step.domain for step in outcome.plan.steps] == ["task", "note"]
        assert all(not action_plans.missing(step) for step in outcome.plan.steps)
        assert outcome.plan.steps[0].task.due == "2026-10-21T05:00:00+00:00"
        phrase = "Запланируй встречу Обзор завтра к полудню на 30 минут"
        outcome = asyncio.run(action_plans.propose(store, settings, phrase, "Asia/Yekaterinburg", now))
        print(json.dumps({"request": phrase, "answer": outcome.text}, ensure_ascii=True), flush=True)
        assert outcome.plan is not None and len(outcome.plan.steps) == 1, outcome.text
        assert outcome.plan.steps[0].event.starts_at == "2026-10-21T07:00:00.000000+00:00"
        assert not store.list("tasks") and not store.list("notes")
    finally:
        parent = psutil.Process(process.pid)
        assert Path(parent.exe()).resolve() == executable.resolve()
        children = parent.children(recursive=True)
        for child in [*children, parent]:
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs([*children, parent], timeout=4)
        process.wait(timeout=5)
