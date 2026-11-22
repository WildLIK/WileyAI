"""Wave/search regressions use fake renderers and chat stores, never personal players."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.media_manager import MediaRequest, parse, remember, consume, end_session
from core.music_intents import MusicAction, search_query
from tests.test_yandex_music import controller
from tests.test_conversation_media35 import media


def test_search_only_returns_numbered_choices_without_play(controller):
    player, page = controller
    result = player.execute(MusicAction(action="search", query="Numb группы Linkin Park"))
    assert result["status"] == "needs_clarification" and not result["confirmed"]
    assert result["candidates"][0]["id"] == "2" and "1. Linkin Park — Numb" in result["text"]
    assert len(result["candidates"][0]["search_id"]) == 32
    assert not any(action in {"select_target", "play"} for action, _ in page.calls)
    assert search_query("Numb группы Linkin Park") == "Numb Linkin Park"


def test_selection_reuses_exact_search_and_does_not_search_again(controller):
    player, page = controller
    found = player.execute(MusicAction(action="search", query="Linkin Park Numb"))
    selected = {key: found["candidates"][0][key] for key in ("id", "title", "artists", "search_id")}
    page.calls.clear()
    result = player.execute(MusicAction(action="select", query=found["query"], selection=selected))
    assert result["confirmed"] and result["state"]["id"] == "2"
    assert not any(action == "search" for action, _ in page.calls)
    assert next(args for action, args in page.calls if action == "select_target")["search_id"] == selected["search_id"]


@pytest.mark.parametrize("action", ["wave", "play"])
def test_wave_can_start_without_previous_track_and_requires_progress(controller, monkeypatch, action):
    player, page = controller
    page.state.update(available=False, id="", playing=False)
    old = page.action
    def perform(kind, **arguments):
        if kind == "wave_target":
            page.calls.append((kind, arguments)); return {"x": 10, "y": 10}
        return old(kind, **arguments)
    monkeypatch.setattr(page, "action", perform)
    sent = []
    def pointer(*args):
        sent.append(args); page.state.update(available=True, id="42", title="Wave song", playing=True)
    monkeypatch.setattr(page, "pointer", pointer)
    result = player.execute(MusicAction(action=action))
    assert result["confirmed"] and result["playback_progress"] and len(sent) == 1
    assert "Моя волна" in result["text"]


@pytest.mark.parametrize("fault", ["stalled", "no_id", "paused", "unchanged_old_track"])
def test_wave_does_not_confirm_an_unobserved_result(controller, monkeypatch, fault):
    player, page = controller
    page.state.update(available=True, playing=False, id="old" if fault == "unchanged_old_track" else "")
    old = page.action
    def action(kind, **arguments):
        if kind == "wave_target": return {"x": 10, "y": 10}
        value = old(kind, **arguments)
        if kind == "status" and fault == "stalled": value["position"] = 0
        return value
    monkeypatch.setattr(page, "action", action)
    sent = []
    def pointer(*args):
        sent.append(args)
        page.state.update(id="" if fault == "no_id" else "old" if fault == "unchanged_old_track" else "42", playing=fault != "paused")
    monkeypatch.setattr(page, "pointer", pointer)
    assert not player.execute(MusicAction(action="wave"))["confirmed"]
    assert len(sent) == 1


@pytest.mark.parametrize("fault", ["missing_button", "cancel", "permissions"])
def test_wave_failure_never_dispatches_or_retries(controller, monkeypatch, fault):
    player, page = controller
    cancel = threading.Event()
    if fault == "cancel": cancel.set()
    if fault == "permissions": player.store.patch_settings({"allow_audio_control": False})
    old = page.action
    def action(kind, **arguments):
        if kind == "wave_target": raise ValueError("Кнопка отсутствует")
        return old(kind, **arguments)
    monkeypatch.setattr(page, "action", action)
    monkeypatch.setattr(page, "pointer", lambda *args: pytest.fail("No pointer on failed preparation"))
    with pytest.raises(ValueError): player.execute(MusicAction(action="wave"), cancel)


def test_already_playing_wave_is_idempotent_and_progress_is_still_required(controller, monkeypatch):
    player, page = controller
    page.state.update(playing=True, wave_playing=True)
    old = page.action
    monkeypatch.setattr(page, "action", lambda kind, **args: {"already_playing": True} if kind == "wave_target" else old(kind, **args))
    monkeypatch.setattr(page, "pointer", lambda *args: pytest.fail("Do not pause an active wave"))
    assert player.execute(MusicAction(action="wave"))["confirmed"]
    page.ignore = True
    assert not player.execute(MusicAction(action="wave"))["confirmed"]


@pytest.mark.parametrize("text", ["Не найди Numb группы Linkin Park", "Не включи первую", "Если включи Мою волну", '«Включи Мою волну»'])
def test_negative_and_quoted_requests_are_not_media_commands(text):
    assert parse(text) is None


def test_chat_search_select_transport_and_session_retirement(tmp_path, monkeypatch):
    app = create_app(tmp_path, "yandex-wave-search-tests-012345")
    store = app.state.store
    store.patch_settings({"music_player": "yandex", "allow_audio_control": True})
    calls = []
    candidate = {"id": "42", "title": "Numb", "artists": "Linkin Park", "search_id": "a" * 32}
    def execute(command, cancel=None):
        calls.append(command)
        if command.action == "search":
            return {"confirmed": False, "candidates": [candidate], "text": "1. Linkin Park — Numb"}
        return {"confirmed": True, "text": "Подтверждено плеером"}
    monkeypatch.setattr(app.state.music, "execute", execute)
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": True})
    monkeypatch.setattr(app.state.media, "inventory", lambda: pytest.fail("Explicit adapter needs no SMTC polling"))
    async def forbidden(*args, **kwargs):
        pytest.fail("No LLM for deterministic media commands")
        yield ""
    monkeypatch.setattr("core.providers.chat", forbidden)
    def chat(client, text):
        response = client.post("/chat", json={"text": text, "mode": "conversation"})
        assert response.status_code == 200 and '"done"' in response.text, response.text
    with TestClient(app, headers={"Authorization": "Bearer yandex-wave-search-tests-012345"}) as client:
        chat(client, "Найди Numb группы Linkin Park")
        assert store.dialogue()["pending_media"]["candidates"] == [candidate]
        chat(client, "Включи первую")
        assert calls[-1].action == "select" and calls[-1].selection.id == "42"
        assert "pending_media" not in store.dialogue()
        for phrase in ("Включи музыку", "Продолжи музыку", "Следующий трек", "Включи мою волну"):
            chat(client, phrase)
        assert [c.action for c in calls] == ["search", "select", "play", "play", "next", "wave"]
        chat(client, "Найди песню Numb")
        end_session(store)
        assert "pending_media" not in store.dialogue()


@pytest.mark.parametrize("reason", ["cancel", "expired", "stopped", "changed_topic", "end_session"])
def test_pending_song_cannot_survive_cancel_expiry_or_new_context(controller, reason):
    player, _ = controller; store = player.store
    assistant = store.add_message("assistant", "1. Numb")
    request = MediaRequest("search", "song", "Яндекс Музыка", query="Numb")
    remember(store, assistant["id"], request=request, candidates=[{"id": "2", "title": "Numb", "artists": "Linkin Park", "search_id": "a" * 32}], request_id="request")
    if reason == "expired":
        state = store.dialogue(); state["pending_media"]["created"] = time.time() - 301; store.save_dialogue(state)
    if reason == "end_session": end_session(store)
    text = "отмена" if reason == "cancel" else "новая тема" if reason == "changed_topic" else "включи первую"
    store.add_message("user", text)
    result = consume(store, text, "Уайли", {"request": 1} if reason == "stopped" else {})
    assert not result or "request" not in result
    assert "pending_media" not in store.dialogue()


def test_auto_connection_for_play_never_double_launches_or_uses_other_backend(media):
    manager, opened, sent, rows, yandex = media
    manager.store.patch_settings({"yandex_auto_connect": True})
    calls = []
    yandex.connect = lambda restart: calls.append(("connect", restart)) or {"connected": True}
    yandex.execute = lambda command, cancel: calls.append((command.action, None)) or {"confirmed": True, "text": "Плеер подтвердил воспроизведение"}
    assert manager.execute(MediaRequest("play", target="Яндекс Музыка"))["confirmed"]
    assert calls == [("connect", False), ("play", None)] and not opened and not sent


def test_uncertain_auto_connection_is_not_retried(media):
    manager, opened, sent, rows, yandex = media
    manager.store.patch_settings({"yandex_auto_connect": True})
    def connect(restart): raise ValueError("Связь потеряна после запуска")
    yandex.connect = connect
    with pytest.raises(ValueError): manager.execute(MediaRequest("play", target="Яндекс Музыка"))
    assert not opened and not sent


def test_autowave_waits_for_explicit_restart_confirmation(tmp_path, monkeypatch):
    app = create_app(tmp_path, "yandex-restart-tests-0123456789")
    store = app.state.store
    exe = tmp_path / "YandexMusic.exe"; exe.touch()
    store.add_alias("Яндекс Музыка", "app", str(exe))
    store.patch_settings({"yandex_auto_play": True, "allow_app_open": True, "allow_audio_control": True})
    calls = []
    def connect(restart=False):
        calls.append(("connect", restart))
        if restart: monkeypatch.setattr(app.state.music, "status", lambda: {"connected": True})
        return {"connected": restart, "restart_required": not restart, "text": "Подключение"}
    monkeypatch.setattr(app.state.music, "connect", connect)
    monkeypatch.setattr(app.state.music, "execute", lambda command, cancel=None: calls.append((command.action, None)) or {"confirmed": True, "text": "Волна подтверждена"})
    monkeypatch.setattr(app.state.media.opener, "execute", lambda *args: pytest.fail("No ordinary launch"))
    with TestClient(app, headers={"Authorization": "Bearer yandex-restart-tests-0123456789"}) as client:
        opened = client.post("/chat", json={"text": "Открой Яндекс Музыку"})
        assert opened.status_code == 200 and '"done"' in opened.text
        assert calls == [("connect", False)]
        assert store.dialogue()["pending_media"]["restart"]
        resumed = client.post("/chat", json={"text": "да"})
        assert resumed.status_code == 200 and '"done"' in resumed.text
        assert calls == [("connect", False), ("connect", True), ("wave", None)]
