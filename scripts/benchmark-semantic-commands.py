"""Fixture-only routing overhead, not real LLM/embedding speed or accuracy.

Never loads models or calls OS executors. Run from the project root.
"""
import asyncio
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["WILEYAI_TEST"] = "1"
from fastapi.testclient import TestClient
from core import commands, providers, semantic_commands as routing
from core.api import create_app
from core.launch_verification import ExecutionText
from core.tools import OpenTools


def summary(values):
    ordered = sorted(values)
    return {"n": len(values), "p50_ms": round(statistics.median(values), 3), "p95_ms": round(ordered[min(len(values)-1, int(len(values)*.95))], 3)}


def main():
    base = Path("local/review/stage34"); base.mkdir(parents=True, exist_ok=True)
    # Retain the isolated profile for evidence, never use an owner's data folder.
    root = Path(tempfile.mkdtemp(prefix="routing-benchmark-", dir=base)).resolve()
    exe = root / "Krita.exe"; exe.touch()
    app = create_app(root, "fixture-routing-benchmark-0123456789")
    scanner = app.state.applications
    rows = [dict(id="fixture", name="Krita", target=str(exe), category="work", source="fixture", aliases=[])]
    scanner.valid_items = lambda: rows
    scanner.find_matches = lambda name: rows if name.casefold() == "krita" else []
    scanner.suggest_matches = lambda name: []
    scanner.choice_label = lambda row: row["name"]
    counts = {"structured": 0, "chat": 0, "embedding": 0, "fake_dispatch": 0}
    prompts = []
    async def structured(settings, messages, schema, **kwargs):
        counts["structured"] += 1
        catalog = json.loads(messages[0]["content"].split("Недоверенный каталог целей:\n")[1])
        selected = next(item["id"] for item in catalog if item["name"] == "Krita")
        prompts.append(len(messages[0]["content"]))
        return json.dumps({"intent": "tools", "steps": [{"tool": "windows.app.open", "choices": [selected]}]})
    async def chat(*args, **kwargs):
        counts["chat"] += 1
        yield "Разговорный ответ фикстурной модели."
    def execute(command, **kwargs):
        counts["fake_dispatch"] += 1
        return ExecutionText("Фикстурный процесс подтверждён.", {"status": "process_started", "pid": 1})
    class Index:
        async def embed(self, settings, texts):
            counts["embedding"] += 1
            # Scripted vectors exercise the existing retrieval interface only.
            return [[1., 0., 0.], *[[1., 0., 0.] if "приложен" in text else [0., 1., 0.] for text in texts[1:]]]
    async def check(): pass
    report = {"environment": {"python": platform.python_version(), "platform": platform.platform()}, "fixture_only": True,
              "limitations": "No real model/embedding inference, OS action, microphone, network or human confirmation delay. Timings measure host code + SQLite + HTTP test transport.", "http": {}, "strategies": {}}
    with patch.object(providers, "structured", structured), patch.object(providers, "chat", chat), patch.object(commands, "execute", execute), patch.object(commands, "folders", lambda: {}), patch.dict(commands.APP_NAMES, {}, clear=True):
        with TestClient(app, headers={"Authorization": "Bearer fixture-routing-benchmark-0123456789"}) as client:
            def send(text):
                before = time.perf_counter()
                response = client.post("/chat", json={"text": text, "mode": "conversation"})
                response.raise_for_status()
                if '"type": "error"' in response.text: raise RuntimeError(response.text)
                return (time.perf_counter()-before)*1000
            for flag in [False, True]:
                app.state.store.patch_settings({"semantic_commands": flag})
                for _ in range(3): send("Открой Krita")
                initial = dict(counts)
                report["http"]["fast_flag_" + str(flag).lower()] = {**summary([send("Открой Krita") for _ in range(20)]), "calls": {key: counts[key]-initial[key] for key in counts}}
            app.state.store.patch_settings({"semantic_commands": True})
            proposal, confirmed = [], []
            for _ in range(20):
                proposal.append(send("Хочу порисовать")); confirmed.append(send("Да"))
            report["http"]["semantic_proposal"] = summary(proposal)
            report["http"]["confirmation_processing"] = summary(confirmed)
            tools = OpenTools(app.state.store, scanner)
            settings = app.state.store.settings().model_copy(update={"embedding_enabled": True})
            async def compare():
                for strategy in ["all", "retrieval"]:
                    initial = dict(counts); timings = []; selection = []; intent = []; proposals = []
                    for _ in range(20):
                        before = time.perf_counter()
                        result = await routing.route(settings, "Хочу порисовать", tools, check, index=Index(), strategy=strategy)
                        assert result.choices and result.choices[0]["label"] == "Krita"
                        timings.append((time.perf_counter()-before)*1000)
                        selection.append(result.timings["selection_ms"]); intent.append(result.timings["intent_ms"]); proposals.append(result.timings["proposal_ms"])
                    report["strategies"][strategy] = {"total": summary(timings), "tool_selection": summary(selection), "structured_decision": summary(intent), "proposal": summary(proposals), "calls": {key: counts[key]-initial[key] for key in counts}, "system_prompt_chars": prompts[-20:]}
            asyncio.run(compare())
    target = base / "semantic-command-benchmark.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
