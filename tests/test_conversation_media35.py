"""D2/E1 integration with fixture processes and media only; no native dispatch."""
from types import SimpleNamespace
from pathlib import Path
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from core.api import create_app
from core.storage import Store
from core.chatspaces import Spaces
from core import commands, windows_media, media_manager, intent_interpreter
from core.media_manager import MediaManager, MediaRequest, parse
from core.launch_verification import ExecutionText


@pytest.fixture
def media(tmp_path, monkeypatch):
    store = Store(tmp_path)
    exe = tmp_path / "YandexMusic.exe"; exe.touch()
    app = {"id": "fixture", "name": "Яндекс Музыка", "target": str(exe)}
    scanner = SimpleNamespace(find_matches=lambda name: [app] if name.casefold() == "яндекс музыка" else [], saved=lambda: {"items": [app]})
    opened, sent, rows = [], [], []
    yandex = SimpleNamespace(status=lambda: {"connected": False}, execute=lambda *args: pytest.fail("No unrequested special command"))
    opener = SimpleNamespace(execute=lambda command: opened.append(command))
    manager = MediaManager(store, scanner, yandex, opener)
    manager.readiness_timeout = .02; manager.verification_timeout = .02
    monkeypatch.setattr("core.launch_verification.process_ids", lambda _: set())
    monkeypatch.setattr(windows_media, "sessions", lambda: [dict(row) for row in rows])
    def perform(identity, action):
        sent.append((identity, action))
        return {**rows[0], "accepted": True, "confirmed": False, "state": "Playing" if action == "play" else "Paused"}
    monkeypatch.setattr(windows_media, "perform_selected", perform)
    return manager, opened, sent, rows, yandex


def row(state="Paused", title="Old"):
    return {"id": "smtc:YandexMusic.exe", "app_id": "YandexMusic.exe", "player": "Яндекс Музыка", "available": True, "commands": ["play", "pause", "next", "previous"], "state": state, "track": {"title": title, "artist": "Artist"}}


def test_delayed_session_is_read_before_exactly_one_play(media, monkeypatch):
    manager, opened, sent, rows, _ = media
    checks = []
    def sessions():
        checks.append(1)
        if len(checks) >= 2: rows[:] = [row()]
        return [dict(value) for value in rows]
    monkeypatch.setattr(windows_media, "sessions", sessions)
    result = manager.execute(MediaRequest("play", target="Яндекс Музыка"))
    assert result["confirmed"] and len(opened) == 1 and len(sent) == 1 and len(checks) == 2
    assert result["readiness_ms"] >= 0 and result["media"]["timings"]["verification_ms"] >= 0


def test_already_playing_never_restarts_or_sends_play(media):
    manager, opened, sent, rows, _ = media; rows.append(row("Playing"))
    assert manager.execute(MediaRequest("play", target="Яндекс Музыка"))["confirmed"]
    assert not opened and not sent


def test_absent_session_has_finite_wait_and_no_fake_wave_success(media):
    manager, opened, sent, rows, _ = media
    began = time.monotonic(); result = manager.execute(MediaRequest("play", target="Яндекс Музыка"))
    assert time.monotonic() - began < .5 and len(opened) == 1 and not sent
    assert result["status"] == "unavailable" and "Мою волну" in result["text"]


def test_autoplay_after_uncertain_open_never_launches_twice(media):
    manager, opened, sent, rows, _ = media
    manager.execute(MediaRequest("play", target="Яндекс Музыка"), allow_launch=False)
    assert not opened and not sent


def test_cancellation_and_permissions_prevent_late_media_action(media, monkeypatch):
    manager, opened, sent, rows, _ = media
    cancel = threading.Event(); cancel.set()
    with pytest.raises(ValueError): manager.execute(MediaRequest("play", target="Яндекс Музыка"), cancel=cancel)
    assert not sent and not opened
    manager.store.patch_settings({"allow_audio_control": False})
    with pytest.raises(ValueError): manager.execute(MediaRequest("play", target="Яндекс Музыка"))
    assert not sent and not opened


def test_cancel_during_readiness_cannot_send_play(media):
    manager, opened, sent, rows, _ = media; manager.readiness_timeout = 1
    cancel = threading.Event(); timer = threading.Timer(.01, cancel.set); timer.start()
    try:
        with pytest.raises(ValueError): manager.execute(MediaRequest("play", target="Яндекс Музыка"), cancel=cancel, allow_launch=False)
        assert not sent and not opened
    finally: timer.join()


def test_special_resume_requires_already_connected_available_track(media):
    manager, opened, sent, rows, yandex = media; calls = []
    yandex.status = lambda: {"connected": True, "state": {"available": True}}
    yandex.execute = lambda command, cancel: calls.append(command.action) or {"confirmed": True, "text": "Плеер подтвердил воспроизведение"}
    assert manager.execute(MediaRequest("play", target="Яндекс Музыка"), allow_launch=False)["confirmed"]
    assert calls == ["play"] and not sent and not opened


@pytest.mark.parametrize("case,confirmed", [("changed", True), ("delayed", True), ("unchanged", False), ("empty_before", False), ("empty_after", False), ("rejected", False), ("disappeared", False)])
def test_next_requires_nonempty_changed_metadata_not_just_playing(media, monkeypatch, case, confirmed):
    manager, opened, sent, rows, _ = media
    before = row("Playing"); rows.append(before)
    if case == "empty_before": before["track"] = {}
    after = row("Playing", "New" if case == "changed" else "Old")
    if case == "empty_after": after["track"] = {}
    def perform(identity, action):
        sent.append((identity, action))
        return {**(before if case == "delayed" else after), "accepted": case != "rejected", "confirmed": True}
    monkeypatch.setattr(windows_media, "perform_selected", perform)
    def inventory(): return [] if case == "disappeared" else [row("Playing", "New") if case == "delayed" else after]
    if case == "disappeared": after["track"] = before["track"]
    monkeypatch.setattr(windows_media, "sessions", inventory)
    result = windows_media.verify_selected(before, "next", timeout=.01)
    assert result["confirmed"] is confirmed and len(sent) == 1
    assert result["sent"] and result["accepted"] is (case != "rejected")


def test_voice_session_end_and_prepare_retire_executable_pending_in_only_this_chat(tmp_path, monkeypatch):
    app = create_app(tmp_path, "conversation35-lifecycle-0123456789")
    store = app.state.store
    other = Spaces(store).create_chat(title="Другой чат")
    keys = {key: {"fixture": True} for key in ("pending_open", "pending_audio", "pending_media", "media_choice")}
    other_store = store.for_chat(other["id"]); other_store.save_dialogue(keys)
    monkeypatch.setattr("core.api.Voice.prepare", lambda *args: None)
    async def prepare(*args): pass
    monkeypatch.setattr("core.providers.prepare", prepare)
    with TestClient(app, headers={"Authorization": "Bearer conversation35-lifecycle-0123456789"}) as client:
        for route in ("/voice/conversation/end", "/voice/prepare"):
            store.save_dialogue({**keys, "unrelated_context": {"keep": True}})
            response = client.post(route, json={"conversation_id": store.conversation_id})
            assert response.status_code == 200, response.text
            assert store.dialogue() == {"unrelated_context": {"keep": True}}
            assert other_store.dialogue() == keys
    assert not store.list("actions")


@pytest.mark.parametrize("text", ["Включи Мою волну", "Включи найденную песню"])
def test_unsupported_selection_does_not_become_an_application_or_fake_play(media, text):
    manager, opened, sent, rows, _ = media
    result = manager.execute(parse(text))
    assert result["status"] == "unavailable" and not sent and not opened


@pytest.mark.parametrize("prefix", ["А-а, ", "Ну, ", "Слушай, ", "", "А теперь "])
def test_fillers_keep_fast_open_and_media_grammar(prefix):
    assert intent_interpreter.interpret(prefix + "Открой Blender").target == "Blender"
    assert parse(prefix + "Включи музыку").action == "play"
    assert parse(prefix + "Следующий трек").action == "next"


@pytest.mark.parametrize("text", ["Не открывай Blender", "А-а, нет, не открывай Blender", "Расскажи, как открыть Blender", "Я не хочу запускать музыку", "Что будет, если открыть браузер?", "Ну, не включи музыку"])
def test_normalization_preserves_scope_and_negation(text):
    assert intent_interpreter.interpret(text) is None and parse(text) is None


def test_song_search_is_data_and_does_not_launch_or_play(media):
    manager, opened, sent, rows, yandex = media
    request = parse("Найди песню Numb группы Linkin Park")
    assert request.action == "search" and request.query == "Numb группы Linkin Park"
    result = manager.execute(request)
    assert result["status"] == "unavailable" and not opened and not sent


@pytest.mark.parametrize("automatic", [False, True])
def test_open_then_resume_uses_short_lived_yandex_context_and_setting(tmp_path, monkeypatch, automatic):
    app = create_app(tmp_path, "conversation35-fixture-token-012345")
    exe = tmp_path / "YandexMusic.exe"; exe.touch()
    store = app.state.store; store.add_alias("Яндекс Музыка", "app", str(exe))
    item = {"id": "yandex", "name": "Яндекс Музыка", "target": str(exe)}
    monkeypatch.setattr(app.state.applications, "saved", lambda: {"items": [item]})
    monkeypatch.setattr(app.state.applications, "find_matches", lambda name: [item] if name.casefold() == "яндекс музыка" else [])
    opened, sent, special = [], [], []
    monkeypatch.setattr(commands, "execute", lambda command, **kw: opened.append(command) or ExecutionText("Процесс запущен", {"status": "process_started"}))
    monkeypatch.setattr(windows_media, "sessions", lambda: [row()])
    monkeypatch.setattr(windows_media, "perform_selected", lambda identity, action: sent.append((identity, action)) or {**row("Playing"), "accepted": True, "confirmed": True})
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": False})
    def connect(restart=False):
        opened.append("special connection")
        monkeypatch.setattr(app.state.music, "status", lambda: {"connected": True})
        return {"connected": True, "text": "Плеер подключён"}
    monkeypatch.setattr(app.state.music, "connect", connect)
    monkeypatch.setattr(app.state.music, "execute", lambda command, cancel=None: special.append(command.action) or {"confirmed": True, "text": "Моя волна подтверждена"})
    async def forbidden(*args, **kwargs):
        pytest.fail("Fast requests cannot use the LLM")
        yield ""
    monkeypatch.setattr("core.providers.chat", forbidden)
    with TestClient(app, headers={"Authorization": "Bearer conversation35-fixture-token-012345"}) as client:
        assert client.get("/settings").json()["yandex_auto_play"] is False
        assert client.put("/media/preferences", json={"source": "auto", "auto_play": automatic}).status_code == 200
        records = []
        for text in ["Открой Яндекс Музыку", "А теперь включи музыку"]:
            began = time.perf_counter()
            response = client.post("/chat", json={"text": text, "mode": "conversation"})
            assert response.status_code == 200 and '"done"' in response.text
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            action = next(event["action"] for event in events if event["type"] == "speech_result")
            records.append({"http_ms": round((time.perf_counter()-began)*1000, 2), "details": action.get("details", {})})
        assert len(opened) == 1 and len(sent) == (0 if automatic else 1)
        assert special == (["wave", "play"] if automatic else [])
        assert store.settings().yandex_auto_play is automatic
        print("fixture_media_timings=" + json.dumps({"autoplay": automatic, "records": records}))
    assert Store(tmp_path).settings().yandex_auto_play is automatic
