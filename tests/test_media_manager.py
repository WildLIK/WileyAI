from contextlib import contextmanager
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import commands, windows_media, windows_audio, audio_sessions
from core.api import create_app
from core.media_manager import MediaRequest, parse


@pytest.mark.parametrize("action,expected", [
    ("play", "Продолжаю."), ("pause", "На паузе."),
    ("stop", "Музыка остановлена."), ("next", "Переключаю."),
    ("previous", "Переключаю."), ("search_play", "Включаю."),
    ("select", "Включаю."),
])
def test_yandex_verified_action_speech_omits_long_metadata(ctx, action, expected):
    manager = ctx[1].state.media
    display = "Подтверждено: " + "очень длинное название " * 20 + "длительность 99 минут"
    result = manager.special_result({"confirmed": True, "text": display}, MediaRequest(action))
    assert result["spoken"] == expected
    assert result["text"] == display and result["status"] == "confirmed"


def test_yandex_speech_keeps_unconfirmed_reason_and_status(ctx):
    manager = ctx[1].state.media
    result = manager.special_result({"confirmed": False, "status": "failed", "text": "Плеер не принял команду."}, MediaRequest("play"))
    assert result["status"] == "failed"
    assert result["spoken"] == "Плеер не принял команду."


def test_yandex_current_track_speech_has_no_duration(ctx):
    manager = ctx[1].state.media
    result = manager.special_result({"confirmed": True, "text": "Песня · длительность 10 минут", "state": {"title": "Трек", "artists": "Исполнитель"}}, MediaRequest("read"))
    assert result["spoken"] == "Трек — Исполнитель."
    assert "длительность" in result["text"]


def test_windows_current_track_speech_uses_metadata_without_duration(ctx):
    client, app, rows, *_ = ctx
    rows[0]["track"] = {"title": "Трек", "artist": "Исполнитель"}
    result = app.state.media.execute(MediaRequest("read"))
    assert result["spoken"] == "Трек — Исполнитель."
    assert "AIMP" in result["text"]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    app = create_app(tmp_path, "media-manager-tests-0123456789")
    aimp = tmp_path / "AIMP.exe"; aimp.touch()
    yandex = tmp_path / "YandexMusic.exe"; yandex.touch()
    apps = [{"id": "a", "name": "AIMP", "target": str(aimp)}, {"id": "y", "name": "Яндекс Музыка", "target": str(yandex)}]
    monkeypatch.setattr(app.state.applications, "find_matches", lambda name: [item for item in apps if item["name"].casefold() == name.casefold()])
    rows = [{"id": "smtc:AIMP", "app_id": "AIMP", "player": "AIMP", "backend": "smtc", "state": "Playing", "commands": ["play", "pause", "next"], "available": True, "executable": str(aimp)}]
    mixer = [{"id": "mix", "pid": 42, "created": 123, "executable": str(aimp), "active": True, "volume": 60, "muted": False}]
    sent, writes, special = [], [], []
    monkeypatch.setattr(windows_media, "sessions", lambda: list(rows))
    def perform(identity, action):
        sent.append((identity, action))
        # The fake must expose the post-action state on the following inventory.
        # D2 correctly avoids sending Play to an already Playing session.
        for row in rows:
            if row["id"] == identity and action in {"play", "pause"}: row["state"] = "Paused" if action == "pause" else "Playing"
        return {"available": True, "player": "AIMP", "state": "Пауза" if action == "pause" else "Воспроизведение", "confirmed": True, "accepted": True}
    monkeypatch.setattr(windows_media, "perform_selected", perform)
    monkeypatch.setattr(audio_sessions, "snapshot", lambda: list(mixer))
    monkeypatch.setattr(audio_sessions, "set_volume", lambda session, exe, created, value, relative=True: writes.append((session, exe, value)) or {**mixer[0], "volume": mixer[0]["volume"] + value if relative else value, "confirmed": True})
    monkeypatch.setattr(app.state.music, "execute", lambda command, cancel=None: special.append(command) or {"confirmed": True, "text": "Песня запущена и проверена"})
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": False, "error": "Не подключена"})
    async def forbidden(*args, **kwargs):
        pytest.fail("Media commands must never be answered by an LLM")
        yield ""
    monkeypatch.setattr("core.providers.chat", forbidden)
    with TestClient(app, headers={"Authorization": "Bearer media-manager-tests-0123456789"}) as client:
        yield client, app, rows, mixer, sent, writes, special, apps


def chat(client, text):
    result = client.post("/chat", json={"text": text, "mode": "conversation"})
    assert result.status_code == 200
    return [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("phrase", ["Убавь звук", "Уайли, убавь звук", "Сделай тише", "Громкость 35", "Выключи звук"])
def test_master_volume_never_captured_by_preferred_yandex(ctx, monkeypatch, phrase):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({"music_player": "yandex"})
    changes = []
    class Device:
        level = 60; muted = False
        def read(self): return {"volume": self.level, "muted": self.muted}
        def set_volume(self, value): changes.append(value); self.level = value
        def set_mute(self, value): changes.append(value); self.muted = value
    @contextmanager
    def endpoint(): yield Device()
    monkeypatch.setattr(windows_audio, "endpoint", endpoint)
    events = chat(client, phrase)
    assert changes and not sent and not writes and not special
    assert any(e.get("action", {}).get("status") == "confirmed" for e in events)


@pytest.mark.parametrize("phrase", ["Убавь звук в AIMP", "Сделай музыку потише", "Уайли, сделай музыку потише"])
def test_application_mixer_has_exact_process_and_one_write(ctx, phrase):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    events = chat(client, phrase)
    assert writes == [("mix", apps[0]["target"], -10)] and not sent and not special
    assert any(e.get("action", {}).get("status") == "confirmed" for e in events)


def test_two_playing_sessions_need_selection_and_selected_only_once(ctx):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    rows.append({**rows[0], "id": "smtc:Spotify", "app_id": "Spotify", "player": "Spotify", "current": True})
    events = chat(client, "Поставь музыку на паузу")
    assert not sent and any(e.get("action", {}).get("status") == "needs_clarification" for e in events)
    assert any("текущая сессия Windows" in e.get("text", "") for e in events)
    chat(client, "второй")
    assert sent == [("smtc:Spotify", "pause")]
    chat(client, "продолжи музыку")
    assert sent[-1] == ("smtc:Spotify", "play") and len(sent) == 2


def test_explicit_target_and_saved_source_do_not_fall_back(ctx):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    rows.append({**rows[0], "id": "smtc:VLC", "app_id": "VLC", "player": "VLC", "executable": str(Path(apps[0]["target"]).with_name("vlc.exe"))})
    assert client.put("/media/preferences", json={"source": "smtc:VLC"}).status_code == 200
    chat(client, "Поставь музыку на паузу в AIMP")
    assert sent == [("smtc:AIMP", "pause")]
    rows.pop()
    chat(client, "продолжи музыку")
    assert len(sent) == 1


@pytest.mark.parametrize("phrase", ["Запусти песню", "Включи песню в Spotify", "Включи Numb в Spotify"])
def test_song_request_does_not_become_app_search_or_transport(ctx, phrase):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    events = chat(client, phrase)
    assert not sent and not writes and not special
    assert any(e["type"] == "speech_result" for e in events)


def test_advanced_yandex_search_only_uses_special_adapter(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": True})
    chat(client, "Включи Numb в Яндекс Музыке")
    assert len(special) == 1 and special[0].query == "Numb" and not sent and not writes


def test_unavailable_error_and_unconfirmed_never_report_success(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    rows.clear()
    assert any(e.get("action", {}).get("status") == "unavailable" for e in chat(client, "Продолжи музыку"))
    assert not sent
    rows.append({"id": "smtc:AIMP", "app_id": "AIMP", "player": "AIMP", "state": "Playing", "commands": ["pause"]})
    monkeypatch.setattr(windows_media, "perform_selected", lambda *a: {"available": True, "player": "AIMP", "state": "Воспроизведение", "accepted": True, "confirmed": False})
    assert any(e.get("action", {}).get("status") == "unconfirmed" for e in chat(client, "Пауза"))


def test_ambiguous_or_wrong_mixer_identity_cannot_write(ctx):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    mixer[0]["executable"] = str(Path(apps[0]["target"]).with_name("Other-AIMP.exe"))
    chat(client, "Убавь звук в AIMP")
    assert not writes
    mixer[0]["executable"] = apps[0]["target"]
    mixer.append({**mixer[0], "id": "second"})
    chat(client, "Сделай музыку потише")
    assert not writes


@pytest.mark.parametrize("verified", [True, False])
def test_store_app_mixer_requires_exact_os_application_identity(ctx, monkeypatch, verified):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    apps.append({"id": "spotify", "name": "Spotify", "target": "aumid:package!Spotify"})
    mixer[0]["executable"] = str(Path(apps[0]["target"]).with_name("packaged-player.exe"))
    mixer[0]["active"] = False
    mixer.append({**mixer[0], "id": "other-app-same-path", "pid": 43, "active": True})
    monkeypatch.setattr(audio_sessions, "app_id", lambda pid: "package!Spotify" if verified and pid == 42 else "other!Spotify")
    chat(client, "Убавь звук в Spotify")
    assert writes == ([("mix", mixer[0]["executable"], -10)] if verified else [])
    assert not sent and not special


@pytest.mark.parametrize("approval", ["да", "нет"])
def test_auto_connection_never_restarts_without_separate_consent(ctx, monkeypatch, approval):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({"yandex_auto_connect": True})
    app.state.store.add_alias("Яндекс Музыка", "app", apps[1]["target"])
    monkeypatch.setattr(app.state.music, "executable", lambda: Path(apps[1]["target"]))
    connections, generic = [], []
    def connect(restart=False):
        connections.append(restart)
        return {"connected": restart, "restart_required": not restart, "text": "Плеер уже запущен" if not restart else "Подключение подтверждено"}
    monkeypatch.setattr(app.state.music, "connect", connect)
    monkeypatch.setattr(commands, "execute", lambda *a, **kw: generic.append(1) or "Не должно вызываться")
    events = chat(client, "Открой Яндекс Музыку")
    assert connections == [False] and not generic
    assert any(e.get("action", {}).get("status") == "restart_required" for e in events)
    chat(client, approval)
    assert connections == ([False, True] if approval == "да" else [False]) and not generic


def test_auto_connection_failure_does_not_double_launch(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({"yandex_auto_connect": True})
    app.state.store.add_alias("Яндекс Музыка", "app", apps[1]["target"])
    monkeypatch.setattr(app.state.music, "executable", lambda: Path(apps[1]["target"]))
    def failed(restart=False): raise ValueError("Не подключено")
    monkeypatch.setattr(app.state.music, "connect", failed)
    monkeypatch.setattr(commands, "execute", lambda *a, **kw: pytest.fail("No second launch after uncertain connection"))
    events = chat(client, "Открой Яндекс Музыку")
    assert any(e.get("action", {}).get("status") == "dispatched" for e in events)


def test_parser_numeric_preposition_is_not_a_player():
    assert parse("Убавь звук на десять") == MediaRequest("change_volume", "system", value=-10)
    assert parse("Убавь громкость Яндекс Музыки") == MediaRequest("change_volume", "player", "Яндекс Музыка", -10)
    assert parse("Не запускай песню") is None


def test_system_current_is_not_an_unconditional_choice(ctx):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    rows.append({**rows[0], "id": "smtc:Paused", "player": "Paused", "app_id": "Paused", "state": "Paused", "current": True})
    chat(client, "Пауза")
    assert sent == [("smtc:AIMP", "pause")]


def test_missing_capability_duplicate_identity_and_disabled_access_never_dispatch(ctx):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    rows[0]["commands"] = []
    chat(client, "Пауза"); assert not sent
    rows[0]["commands"] = ["pause"]; rows.append(dict(rows[0]))
    chat(client, "Пауза"); assert not sent
    rows.pop(); app.state.store.patch_settings({"allow_audio_control": False})
    chat(client, "Пауза"); assert not sent


def test_error_after_native_dispatch_is_not_retried_in_any_backend(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    def failed(identity, action):
        sent.append((identity, action)); raise ValueError("Response lost after dispatch")
    monkeypatch.setattr(windows_media, "perform_selected", failed)
    events = chat(client, "Пауза")
    assert sent == [("smtc:AIMP", "pause")] and not special
    assert any(e.get("action", {}).get("status") == "failed" for e in events)


def test_preferred_yandex_cannot_capture_confirmed_volume_correction(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({"music_player": "yandex"})
    changes = []
    class Device:
        level = 60
        def read(self): return {"volume": self.level, "muted": False}
        def set_volume(self, value): self.level = value; changes.append(value)
    @contextmanager
    def endpoint(): yield Device()
    monkeypatch.setattr(windows_audio, "endpoint", endpoint)
    chat(client, "Упавь громкость на 10")
    assert not changes
    chat(client, "да")
    assert changes == [50] and not writes and not sent and not special
