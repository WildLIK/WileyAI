"""Permanent ru-300 /chat benchmark: fake executors and scripted LLM only.

python scripts/benchmark-intent-suite.py --label before|after|current
No microphone, real inference, network, app launch or player control is measured.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402

from core import audio_sessions, commands, device_audio, media_manager, providers, semantic_commands, windows_media, windows_audio, intents  # noqa: E402
from core.api import create_app  # noqa: E402
from core.yandex_music import rank as base_rank  # noqa: E402
from scripts.semantic_test_safety import isolated_boundaries

DATASET = REPO / "tests/fixtures/intent-suite/ru300.json"
OUTPUT = REPO / "docs/benchmarks/intent-suite.json"
EXPECTED = frozenset({"open.app", "open.folder", "open.url", "open.proposal", "prohibit", "cancel", "inspect", "clarify", "chat", "no_mutation",
    "media.play", "media.pause", "media.next", "media.previous", "media.status", "media.wave", "media.search", "media.search_play", "media.select", "media.like", "media.unlike", "media.volume.down", "media.volume.up", "media.volume.set",
    "audio.volume.down", "audio.volume.up", "audio.volume.set", "audio.mute", "audio.unmute"})
CATEGORIES = frozenset({"base", "music_search", "asr_forms", "minpairs", "colloquial", "questions", "negations", "compound", "context", "stt_art", "foreign", "unknown", "clarify", "ambiguous", "translit"})


def load_dataset(path=DATASET):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict) or not isinstance(data.get("cases"), list) or len(data["cases"]) != 300:
        raise ValueError("ru300 requires metadata and exactly 300 cases")
    ids = set()
    for case in data["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].startswith("ru300-") or case["id"] in ids:
            raise ValueError("Each case requires a unique stable ID")
        ids.add(case["id"])
        if not isinstance(case.get("c"), str) or not isinstance(case.get("e"), str) or case["c"] not in CATEGORIES or case["e"] not in EXPECTED:
            raise ValueError("Invalid category or expected action: " + case["id"])
        if not isinstance(case.get("t"), str) or not case["t"].strip() or len(case["t"]) > 1000:
            raise ValueError("Invalid utterance: " + case["id"])
        if not isinstance(case.get("turns", []), list) or any(not isinstance(t, str) or not t.strip() for t in case.get("turns", [])):
            raise ValueError("Invalid dialogue turns: " + case["id"])
        for hint in ("th", "qh"):
            if hint in case and not isinstance(case[hint], str): raise ValueError("Invalid argument hint")
        if "qv" in case and (type(case["qv"]) is not int or not -100 <= case["qv"] <= 100): raise ValueError("Invalid expected volume")
    return data

CHAT_TEXT = "Обычный ответ без действий"
TOKEN = "research-bench-0123456789abcdef"
HEADERS = {"Authorization": "Bearer " + TOKEN}


class Rec:
    def __init__(self):
        self.open, self.audio, self.media, self.yandex = [], [], [], []
        self.chat_calls = 0
        self.structured_calls = 0
        self.proposals = []
        self.events = []


REC = Rec()


class FakeEndpoint:
    def __init__(self):
        self._state = {"volume": 50, "muted": False}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return dict(self._state)

    def set_volume(self, value):
        REC.audio.append(("set_volume", value))
        self._state["volume"] = value

    def set_mute(self, value):
        REC.audio.append(("set_mute", value))
        self._state["muted"] = value


class FakeYandex:
    def __init__(self, root, store, applications):
        self.store, self.applications = store, applications

    def status(self):
        return {"connected": True, "state": {"available": True, "playing": False, "id": "1", "position": 0.0}}

    def connect(self, restart=False):
        return {"connected": True, "restart_required": False}

    def executable(self):
        raise ValueError("No installed Yandex executable in fixture; music actions use the fake adapter")

    def execute(self, command, cancel=None):
        REC.yandex.append((command.action, command.query, getattr(command.selection, "title", None) if command.selection else None))
        if command.action == "search":
            query = (command.query or "").casefold()
            if "вояджер" in query:
                rows = [{"id": "1", "title": "Вояджер", "artists": "Noize MC"}]
            elif "numb" in query:
                rows = [{"id": "2", "title": "Numb", "artists": "Linkin Park"},
                        {"id": "4", "title": "Numb (Live)", "artists": "Linkin Park"},
                        {"id": "5", "title": "Numb / Encore", "artists": "Jay-Z, Linkin Park"}]
            else:
                rows = [{"id": "1", "title": command.query.title(), "artists": "Исполнитель"}]
            search_id = uuid.uuid4().hex
            candidates = [{**row, "search_id": search_id} for row in base_rank(command.query, rows)[:3]]
            return {"confirmed": False, "status": "needs_clarification", "candidates": candidates,
                    "query": command.query, "text": "Найдены песни в Яндекс Музыке."}
        if command.action == "select":
            return {"confirmed": True, "status": "confirmed", "text": "Включила выбранную песню.", "state": {"playing": True, "id": "1", "position": 0.3}}
        return {"confirmed": True, "status": "confirmed", "text": "Команда Яндекс Музыки подтверждена.", "state": {"playing": True, "id": "1", "position": 0.2}}


async def scripted_chat(settings, messages):
    REC.chat_calls += 1
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""
    if "Каталог:\n" in system:
        catalog = json.loads(system.split("Каталог:\n")[1])
        low = user.casefold()
        for needle, name in PROPOSAL_MAP.items():
            if needle in low:
                chosen = next((item for item in catalog if name in item["name"].casefold()), None)
                if chosen:
                    yield json.dumps({"candidates": [chosen["id"]]})
                    return
        yield json.dumps({"candidates": []})
        return
    yield CHAT_TEXT


def scripted_structured(settings, messages, schema, *, max_chars=2048):
    REC.structured_calls += 1
    return json.dumps({"intent": "conversation"})


async def scripted_route(current, text, open_tools, semantic_check, *, index=None, read_status=None, context=None):
    # Mirrors the model decision only for catalog app proposals; everything else is conversation.
    choices = open_tools.choices()
    low = text.casefold()
    picked = None
    for needle, name in PROPOSAL_MAP.items():
        if needle in low:
            picked = next((item for item in choices if name in item["label"].casefold()), None)
            if picked:
                break
    if picked:
        chosen = [picked]
        return semantic_commands.Prepared(text=intents.question(chosen), choices=chosen, status="needs_clarification", timings={"scripted": 0.0})
    REC.chat_calls += 1
    return semantic_commands.Prepared(text=CHAT_TEXT, status="conversation", timings={"scripted": 0.0})


PROPOSAL_MAP = {"рисова": "krita", "моделирован": "blender", "программу для текста": "word", "для таблиц": "excel", "интернет": "chrome", "браузер": "chrome", "калькулятор": "калькулятор"}


def setup_case(tmp_root):
    REC.open.clear(); REC.audio.clear(); REC.media.clear(); REC.yandex.clear()
    REC.chat_calls = 0; REC.structured_calls = 0; REC.proposals.clear()
    REC.events.clear()
    real_execute = commands.execute
    real_media_execute = media_manager.MediaManager.execute
    real_audio_execute = device_audio.AudioTools.execute

    def record_execute(command, dry_run=False):
        REC.open.append((command.kind, command.target, command.label))
        return f"Проверено: {command.label}. Запуск не выполнялся."

    def record_media(self, request, confirmed="", request_id=None, cancel=None, allow_launch=True):
        REC.media.append((request.action, request.scope, request.target, request.query, request.value))
        if request.action == "search":
            return FakeYandex(None, self.store, None).execute(type("M", (), {"action": "search", "query": request.query, "selection": None})())
        if request.action == "select":
            return {"confirmed": True, "status": "confirmed", "text": "Включила выбранную песню."}
        if request.action == "found":
            return {"text": "Нет актуального списка найденных песен. Сначала назовите песню и исполнителя для поиска.", "status": "unavailable"}
        if request.action == "search_play" and not (request.query or "").strip():
            return {"text": "Какую песню и в каком источнике включить?", "status": "needs_clarification"}
        return {"confirmed": True, "status": "confirmed", "text": "Медиа команда подтверждена."}

    def record_audio(self, command, dry_run=False, request_id=None):
        REC.audio.append((command.action, command.value))
        return {"text": f"Проверено: {command.action}"}

    device_audio.AudioTools.execute = record_audio
    media_manager.MediaManager.execute = record_media
    commands.execute = record_execute
    return real_execute, real_media_execute, real_audio_execute


@contextmanager
def build_case_app(tmp_path, monkey_patches=None):
    store_dir = tmp_path / "store"
    store_dir.mkdir(exist_ok=True)
    first = tmp_path / "blender.exe"; first.write_text("x")
    files = {}
    for name in ("krita", "word", "excel", "chrome", "telegram", "aimp", "spotify", "notepad-plus", "painted"):
        exe = tmp_path / f"{name}.exe"; exe.write_text("x"); files[name] = exe
    fixture_folders = {name: str(tmp_path / name) for name in ("загрузки", "документы", "рабочий стол", "домашнюю папку")}
    for folder in fixture_folders.values(): Path(folder).mkdir(exist_ok=True)
    patches = [
        ("core.api.YandexMusic", FakeYandex),
        ("core.yandex_music.YandexMusic", FakeYandex),
        (windows_media, "sessions", lambda: []),
        (windows_media, "perform", lambda action="read": {"available": False}),
        (audio_sessions, "snapshot", lambda: []),
        (device_audio.windows_media, "perform", lambda action="read": {"available": False}),
        (device_audio.windows_audio, "endpoint", lambda: FakeEndpoint()),
        (providers, "chat", scripted_chat),
        (providers, "get_key", lambda config: ""),
        (providers, "structured", scripted_structured),
        (semantic_commands, "route", scripted_route),
        (commands, "folders", lambda: fixture_folders),
    ]
    import core.app_discovery as app_discovery
    patches.append((app_discovery.ApplicationScanner, "find_matches", lambda self, name: []))
    patches.append((app_discovery.ApplicationScanner, "find", lambda self, name: None))

    originals = []
    import importlib
    for target in patches:
        if isinstance(target[0], str):
            module_path, attr = target[0].rsplit(".", 1)
            module = importlib.import_module(module_path)
            originals.append((module, attr, getattr(module, attr)))
            setattr(module, attr, target[1])
        else:
            obj, attr, value = target
            originals.append((obj, attr, getattr(obj, attr, None)))
            setattr(obj, attr, value)
    try:
        app = create_app(store_dir, TOKEN)
        with TestClient(app, headers=HEADERS) as client:
            access = client.get("/tools").json()["access"]
            access.update({"command_understanding": True, "allow_app_open": True, "allow_file_open": True, "allow_web_open": True, "allow_audio_control": True})
            client.put("/tools/access", json=access)
            client.put("/settings", json={"semantic_commands": True, "music_player": "yandex", "media_source": "auto"})
            for name, exe in [("blender", first), *[(name, files[name]) for name in ("krita", "word", "excel", "chrome", "telegram", "aimp", "spotify")], ("notepad++", files["notepad-plus"]), ("пainted", files["painted"])]:
                client.post("/aliases", json={"name": name, "kind": "app", "target": str(exe)})
            yield client
    finally:
        for obj, attr, value in reversed(originals):
            setattr(obj, attr, value)


def send(client, text):
    started = time.perf_counter()
    response = client.post("/chat", json={"text": text})
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code == 400:
        REC.events.append({'type':'http_rejection','status':400,'detail':response.json().get('detail','')})
        return '__http_400__', elapsed  # Safe input rejection, never a clarification success.
    if response.status_code != 200:
        raise RuntimeError("Chat HTTP error: " + str(response.status_code))
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    if not any(e.get('type') == 'done' for e in events): raise RuntimeError('Chat did not complete')
    REC.events.extend(events)
    for item in events:
        action = item.get("action", {}) if item.get("type") == "speech_result" else {}
        if action.get("action") == "open" and action.get("status") in {"clarification", "needs_clarification"}:
            REC.proposals.append(action)
    message = next((item["message"] for item in events if item["type"] == "done"), {})
    text = (message.get("text") or message.get("content") or "")
    if not text:
        text = " ".join(item.get("text", "") for item in events if item["type"] == "delta").strip()
    if not text: raise RuntimeError('Chat returned an empty answer')
    return text, elapsed


CLARIFY_MARKS = ("уточнит", "номер", "Какую", "какую", "Ответьте", "источник", "песню и", "вариант", "Открыть", "Что открыть", "Каким", "Назовите", "Укажите", "Не удалось", "Найдены песни", "отменено", "отменён")
REFUSE_MARKS = ("не открываю", "не запускаю", "не буду", "не открывала")
CANCEL_MARKS = ("отмен", "Ничего не открыто", "не выполнялась")


def legacy_score(case, texts, rec):
    expect = case["e"]
    opens = rec.open
    audio = rec.audio
    media = rec.media
    mutated = bool(opens or audio or [m for m in media if m[0] not in {"search", "found", "status", "read"}])
    target_hint = (case.get("th") or "").casefold()
    query_hint = (case.get("qh") or "").casefold()
    qv = case.get("qv")
    if expect.startswith("open."):
        kind = {"open.app": "app", "open.folder": "folder", "open.url": "url"}.get(expect, "")
        got_open = [item for item in opens if (not kind or item[0] == kind) and (not target_hint or target_hint in (item[1] + item[2]).casefold())]
        if got_open:
            return "pass", "open:" + got_open[0][0]
        if expect == "open.proposal" and rec.proposals:
            return "pass", "proposal"
        if expect == "open.proposal" and not texts:
            return "fail", "no_response"
        return "fail", "open:" + (opens[0][0] if opens else ("none;" + ("proposal" if rec.proposals else "no-proposal")))
    if expect.startswith("media."):
        want = expect.split(".", 1)[1]
        if want == "volume.set":
            current = next((item for item in media if item[0] == "set_volume"), None)
            ok = current is not None and (qv is None or current[4] == qv)
            return ("pass" if ok else "fail"), "media:set_volume:" + str(current[4] if current else None)
        if want in {"volume.down", "volume.up"}:
            current = next((item for item in media if item[0] in {"change_volume", "set_volume"} and ("музык" in (item[3] or "") or item[2] or item[1] == "player")), None)
            ok = current is not None and current[0] == "change_volume" and ((current[4] or 0) < 0 if want == "volume.down" else (current[4] or 0) > 0)
            return ("pass" if ok else "fail"), "media:" + (f"{current[0]}:{current[4]}" if current else "none")
        transport = {"play": "play", "pause": "pause", "next": "next", "previous": "previous", "status": ("status", "media_status"), "wave": "wave", "search": "search", "search_play": "search_play", "select": "select", "like": "like", "unlike": "unlike"}
        want_actions = transport.get(want, want)
        want_actions = want_actions if isinstance(want_actions, tuple) else (want_actions,)
        current = media[-1] if case.get("turns") and media else (media[0] if media else None)
        if current:
            action = current[0]
            query = (current[3] or "").casefold()
            ok = action in want_actions and (not query_hint or query_hint in query)
            return ("pass" if ok else "fail"), "media:" + action + (f"({query[:24]})" if query else "")
        if rec.yandex:
            action = rec.yandex[0][0]
            ok = action in want_actions
            return ("pass" if ok else "fail"), "yandex:" + action
        audio_media = next((item for item in audio if item[0] in want_actions or (want == "status" and item[0] == "media_status")), None)
        if audio_media:
            return "pass", "audio-media:" + audio_media[0]
        return "fail", "media:none"
    if expect.startswith("audio."):
        want = {"audio.volume.set": "set_volume", "audio.volume.down": "change_volume", "audio.volume.up": "change_volume", "audio.mute": "mute", "audio.unmute": "unmute"}.get(expect, expect)
        if not audio:
            return "fail", "audio:none"
        action, value = audio[0][0], audio[0][1]
        ok = action == want
        if expect in {"audio.volume.down", "audio.volume.up"} and value is not None:
            ok = ok and ((value < 0) if expect == "audio.volume.down" else (value > 0))
        if qv is not None and value is not None:
            ok = ok and value == qv
        return ("pass" if ok else "fail"), f"audio:{action}:{value}"
    if expect == "prohibit":
        text = " ".join(texts)
        ok = (not mutated) and any(mark.casefold() in text.casefold() for mark in REFUSE_MARKS)
        return ("pass" if ok else "fail"), "prohibit:" + ("refused" if ok else text[:40])
    if expect == "cancel":
        text = " ".join(texts)
        ok = (not mutated) and any(mark.casefold() in text.casefold() for mark in CANCEL_MARKS)
        return ("pass" if ok else "fail"), "cancel:" + text[:40]
    if expect == "inspect":
        text = " ".join(texts)
        ok = (not mutated) and (CHAT_TEXT not in text)
        return ("pass" if ok else "fail"), "inspect:" + (text[:40] or "silent-ok")
    if expect == "clarify":
        text = " ".join(t for t in texts if not t.startswith("__http"))
        asked = any(mark.casefold() in text.casefold() for mark in CLARIFY_MARKS) or text.rstrip().endswith("?")
        asked |= any(e.get('type') == 'speech_result' and e.get('action', {}).get('status') in {'clarification', 'needs_clarification'} for e in rec.events)
        heavy = opens or audio or [m for m in media if m[0] not in {"search", "found"}]
        ok = (not heavy) and (asked or rec.proposals)
        return ("pass" if ok else "fail"), "clarify:" + text[:40]
    if expect == "chat":
        clean_texts = [t for t in texts if not t.startswith("__http")]
        ok = (not mutated) and (rec.chat_calls > 0) and (CHAT_TEXT in texts or all(t == "" for t in clean_texts) or not clean_texts)
        return ("pass" if ok else "fail"), "chat:" + ("yes" if CHAT_TEXT in texts else ("mutated" if mutated else (texts[0][:40] if texts else "no-text")))
    if expect == "no_mutation":
        return ("pass" if not mutated else "fail"), "no_mutation:" + ("clean" if not mutated else "mutated:" + str((opens[:1], audio[:1], media[:1])))
    return "fail", "unknown-expect"


def assess(case, texts, rec):
    verdict, got = legacy_score(case, texts, rec)
    # Observe fake calls directly. A search is a dispatch too, even if a later
    # answer contains a clarification word. Parent media->Yandex calls count once.
    actions = [*(('open', *row) for row in rec.open), *(('audio', *row) for row in rec.audio if row[0] not in {'read', 'status', 'media_status'}),
               *(('media', *row) for row in rec.media if row[0] not in {'found', 'status', 'read'})]
    if not rec.media: actions.extend(('yandex', *row) for row in rec.yandex if row[0] not in {'found', 'status', 'read'})
    negative = case['c'] in {'negations', 'questions', 'clarify'} and case['e'] in {'prohibit', 'chat', 'no_mutation', 'cancel'}
    partial = case['c'] == 'compound' and case['e'] in {'clarify', 'no_mutation'} and bool(actions)
    argument_error = False
    if case.get('qh'):
        queries = [row[3] for row in rec.media if row[0] == case['e'].removeprefix('media.')]
        queries += [row[1] for row in rec.yandex if row[0] == case['e'].removeprefix('media.')]
        argument_error = bool(queries) and not any(case['qh'].casefold() in q.casefold() for q in queries)
    if case.get('th') and rec.open and case['e'] != 'open.proposal':
        argument_error |= not any(case['th'].casefold() in (row[1]+row[2]).casefold() for row in rec.open)
    if 'qv' in case and (rec.audio or rec.media):
        values = [r[1] for r in rec.audio if r[0] in {'set_volume','change_volume'}] + [r[4] for r in rec.media if r[0] in {'set_volume','change_volume'}]
        argument_error |= bool(values) and case['qv'] not in values
    if case['e'].startswith(('audio.volume.', 'media.volume.')) and any(e.get('type')=='http_rejection' for e in rec.events): argument_error = True
    if partial or (negative and actions) or argument_error: verdict = 'fail'
    replies = [e.get('action', {}) for e in rec.events if e.get('type') == 'speech_result']
    unnecessary = verdict != 'pass' and case['e'].startswith(('open.', 'media.', 'audio.')) and case['e'] != 'open.proposal' and bool(replies) and replies[-1].get('status') in {'clarification', 'needs_clarification'}
    return {'verdict': verdict, 'got': got, 'legacy_verdict': legacy_score(case, texts, rec)[0], 'actions': actions,
            'false_action': negative and bool(actions), 'partial_execution': partial, 'argument_error': argument_error, 'unnecessary_clarification': unnecessary,
            'api_rejection': any(e.get('type')=='http_rejection' for e in rec.events)}


def summarize(rows):
    times = sorted(r['ms'] for r in rows if 'ms' in r)
    return {'total': len(rows), 'passed': sum(r['verdict']=='pass' for r in rows), 'errors': sum(r['verdict']=='error' for r in rows),
            'legacy_passed': sum(r.get('legacy_verdict')=='pass' for r in rows),
            **{key: sum(bool(r.get(key)) for r in rows) for key in ('false_action','partial_execution','argument_error','unnecessary_clarification','api_rejection')},
            'p50_ms': round(statistics.median(times), 2) if times else None, 'p95_ms': times[min(len(times)-1, int(len(times)*.95))] if times else None}


def run_cases(cases, root):
    from unittest.mock import patch
    windows = root / 'Windows'
    (windows / 'System32').mkdir(parents=True)
    for path in (windows/'explorer.exe', windows/'System32/notepad.exe', windows/'System32/calc.exe'): path.touch()
    rows = []
    with patch.dict(os.environ, {'WILEYAI_TEST':'1', 'WILEYAI_DATA_DIR':str(root/'unused-profile'), 'WINDIR':str(windows)}), isolated_boundaries() as blocked:
        for case in cases:
            case_root = root / case['id']; case_root.mkdir()
            real = setup_case(case_root)
            start_blocked = len(blocked)
            try:
                with build_case_app(case_root) as client:
                    texts, latencies = [], []
                    for text in [case['t'], *case.get('turns', [])]:
                        reply, elapsed = send(client, text); texts.append(reply); latencies.append(elapsed)
                    if len(blocked) != start_blocked: raise RuntimeError('Safety guard blocked: ' + ','.join(blocked[start_blocked:]))
                    errors = [e for e in REC.events if e.get('type') == 'error']
                    if errors: raise RuntimeError('Chat API error, not a model verdict: ' + str(errors)[:180])
                    result = {**assess(case, texts, REC), 'texts': [t[:240] for t in texts], 'ms':round(sum(latencies),2), 'llm_calls':REC.chat_calls+REC.structured_calls}
            except Exception as error:
                result = {'verdict':'error','error':str(error)[:240]}
            finally:
                device_audio.AudioTools.execute, media_manager.MediaManager.execute, commands.execute = real[2], real[1], real[0]
            rows.append({'id':case['id'],'c':case['c'],'t':case['t'],'e':case['e'],**result})
            if len(rows) % 25 == 0: print(f"intent-suite: {len(rows)}/{len(cases)}", file=sys.stderr, flush=True)
    return {'summary':summarize(rows), 'categories':{c:summarize([r for r in rows if r['c']==c]) for c in dict.fromkeys(r['c'] for r in rows)}, 'cases':rows, 'blocked_boundary_calls':blocked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--label', choices=('before','after','current'), default='current')
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    digest = hashlib.sha256(json.dumps(dataset, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    report = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    if report and report.get('dataset_sha256') != digest: raise ValueError('Refusing comparison with a different dataset')
    with tempfile.TemporaryDirectory(prefix='wileyai-intent-suite-') as tmp:
        run = run_cases(dataset['cases'], Path(tmp))
    report.update(fixture_only=True, dataset_sha256=digest, dataset='tests/fixtures/intent-suite/ru300.json',
        limitations='Real /chat routing; fake executors and scripted LLM. No microphone, real inference, network or OS actions. Timings measure Python/SQLite/ASGI on this host.',
        glm_reference={'passed':208,'total':300,'false_actions':0,'p50_ms':64,'p95_ms':144,
            'categories':dict(zip(('base','asr_forms','colloquial','music_search','foreign','translit','unknown','questions','negations','compound','clarify','context','ambiguous','stt_art','minpairs'),(28,7,8,19,1,9,14,19,17,13,14,13,11,13,22)))},
        metric_definitions={'false_action':'Any fake effect on the 44-case original negative mask (negations/questions/clarify with prohibit/chat/no_mutation/cancel). Positive cases in those categories are excluded.',
            'partial_execution':'Any fake dispatch, including search, on compound cases expecting clarification/no mutation.',
            'argument_error':'An executed action with wrong target/query/volume, or HTTP 400 on an expected volume action.',
            'unnecessary_clarification':'Final clarification on a failed case expecting execution; intended proposals excluded.',
            'api_rejection':'HTTP 400 input rejection; not a harness error or a successful clarification.'},
        harness_changes=['Independent profile per case; context persists only within turns', 'Native/network/credential boundaries fail closed', 'Folder and Windows EXE fixtures; all declared aliases seeded', 'Proposals counted from emitted events; errors do not count as clarification', 'False actions and partial compound execution counted from calls, not reply text'])
    report.setdefault('runs', {})[args.label] = run
    if 'before' in report['runs'] and 'after' in report['runs']:
        before, after = report['runs']['before'], report['runs']['after']
        report['comparison'] = {'passed_delta': after['summary']['passed']-before['summary']['passed'],
            'categories':{c:{'before':before['categories'][c]['passed'],'after':after['categories'][c]['passed'],'total':after['categories'][c]['total']} for c in after['categories']}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'label':args.label,**run['summary'],'categories':{c:str(s['passed'])+'/'+str(s['total']) for c,s in run['categories'].items()}},ensure_ascii=True))
    for row in run['cases']:
        if row['verdict']=='error': print(json.dumps({'id':row['id'],'error':row['error']},ensure_ascii=True))
    return 1 if run['summary']['errors'] or run['summary']['false_action'] else 0


if __name__ == "__main__":
    raise SystemExit(main())
