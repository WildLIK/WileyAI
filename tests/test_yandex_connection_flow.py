"""Owner-reported connection sequences; all processes, renderer and clicks are fakes."""
from contextlib import contextmanager
import json

import psutil
import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core import commands
from core.media_manager import parse
from core.music_intents import resolve
from core.yandex_music import MusicError, YandexMusic
from core.storage import Store
from tests.test_yandex_music import Page


@pytest.mark.parametrize("text,action", [
    ("Запусти мою волну", "wave"), ("Запусти моя волна", "wave"),
    ("Открой моя волна", "wave"), ("Запусти мою музыку", "play"),
    ("Воспроизвести музыку", "play"), ("Уайли, можешь запустить мою волну?", "wave"),
])
def test_exact_natural_forms_are_media_requests(text, action):
    assert parse(text).action == action
    assert resolve(text, preferred=True).action == action


@pytest.mark.parametrize("text", [
    "Не запусти моя волна", "Яндекс Музыка, не запусти мою волну", "Как запустить мою волну?",
    "Если открыть моя волна", "Открой моя волна и удали файл", "Запусти мою музыку и открой блокнот",
    '«Запусти моя волна»', "Он сказал запусти мою музыку", "Не воспроизвести музыку",
])
def test_variants_keep_negations_quotes_mentions_and_multiple_actions_inert(text):
    assert parse(text) is None
    assert resolve(text, preferred=True) is None


@pytest.fixture
def flow(tmp_path, monkeypatch):
    app = create_app(tmp_path, "yandex-connection-flow-0123456789")
    store = app.state.store
    exe = tmp_path / "YandexMusic.exe"; exe.touch()
    store.add_alias("Яндекс Музыка", "app", str(exe))
    store.patch_settings({"allow_audio_control": True, "allow_app_open": True})
    # Deliberately preserved descriptor bytes: Open must not rewrite/replace it.
    app.state.music.path.write_text('{"fixture":"same authenticated process"}')
    page = Page(); sent = []
    old = page.action
    def action(kind, **args):
        if kind == "wave_target":
            page.calls.append((kind, args))
            return {"already_playing": True} if page.state.get("wave_playing") else {"x": 20, "y": 20}
        return old(kind, **args)
    page.action = action
    def pointer(*args):
        sent.append(args); page.state.update(available=True, id="42", playing=True, wave_playing=True)
    page.pointer = pointer
    @contextmanager
    def renderer(): yield page
    monkeypatch.setattr(app.state.music, "renderer", renderer)
    monkeypatch.setattr("core.yandex_music.time.sleep", lambda _: None)
    monkeypatch.setattr(commands, "execute", lambda *a, **k: pytest.fail("Connected player must not be launched again"))
    monkeypatch.setattr("core.yandex_music.start_player", lambda *a: pytest.fail("No real process launch"))
    async def no_model(*args, **kw):
        pytest.fail("These commands must use the media fast path")
        yield ""
    monkeypatch.setattr("core.providers.chat", no_model)
    with TestClient(app, headers={"Authorization": "Bearer yandex-connection-flow-0123456789"}) as client:
        yield client, app, page, sent


def chat(client, text):
    response = client.post("/chat", json={"text": text, "mode": "conversation"})
    assert response.status_code == 200 and '"done"' in response.text, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return next(e["action"] for e in events if e["type"] == "speech_result")


@pytest.mark.parametrize("automatic", [False, True])
def test_manual_connection_open_then_wave_preserves_connection_and_never_relaunches(flow, monkeypatch, automatic):
    client, app, page, sent = flow
    app.state.store.patch_settings({"yandex_auto_play": automatic, "yandex_auto_connect": False})
    before = app.state.music.path.read_bytes()
    assert client.post("/music/yandex/connect", json={}).json()["connected"]
    # A verified live connection is reusable even when both auto settings are off.
    monkeypatch.setattr(app.state.music, "connect", lambda *a: pytest.fail("Open must reuse the connection"))
    opened = chat(client, "Открой Яндекс Музыку")
    assert app.state.music.path.read_bytes() == before
    assert len(sent) == int(automatic)
    if automatic: assert opened["details"]["autoplay"]["confirmed"]
    result = chat(client, "Запусти мою волну")
    assert result["status"] == "confirmed"
    assert len(sent) == 1  # Explicit Wave after autoplay is idempotent.
    assert app.state.music.path.read_bytes() == before


@pytest.mark.parametrize("automatic", [False, True])
def test_open_without_cdp_offers_restart_and_no_does_not_play(flow, monkeypatch, automatic):
    client, app, page, sent = flow
    app.state.store.patch_settings({"yandex_auto_play": automatic, "music_player": "yandex"})
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": False, "selected": True, "diagnostics": {"reason": "stale_pid"}})
    calls = []
    def connect(restart=False):
        calls.append(restart)
        assert restart is False
        return {"connected": False, "restart_required": True, "text": "Открыта без CDP"}
    monkeypatch.setattr(app.state.music, "connect", connect)
    chat(client, "Открой Яндекс Музыку")
    assert app.state.store.dialogue()["pending_media"]["restart"]
    chat(client, "нет")
    assert calls == [False] and not sent and not page.calls


@pytest.mark.parametrize("text", ["Запусти моя волна", "Открой моя волна", "Запусти мою музыку", "Воспроизвести музыку"])
def test_natural_forms_take_media_path_before_application_intent(flow, text):
    client, app, page, sent = flow
    app.state.store.patch_settings({"music_player": "yandex"})
    assert chat(client, text)["status"] == "confirmed"
    assert any(kind in {"wave_target", "play"} for kind, _ in page.calls)


@pytest.mark.parametrize("automatic", [False, True])
def test_wave_without_cdp_requires_yes_and_resumes_only_the_original_request(flow, monkeypatch, automatic):
    client, app, page, sent = flow
    app.state.store.patch_settings({"music_player": "yandex", "yandex_auto_play": automatic})
    monkeypatch.setattr(app.state.music, "status", lambda: {"connected": False})
    calls = []
    def connect(restart=False):
        calls.append(restart)
        if restart:
            monkeypatch.setattr(app.state.music, "status", lambda: {"connected": True})
        return {"connected": restart, "restart_required": not restart}
    monkeypatch.setattr(app.state.music, "connect", connect)
    proposal = chat(client, "Запусти мою волну")
    assert proposal["status"] == "needs_clarification" and calls == [False] and not sent
    assert chat(client, "да")["status"] == "confirmed"
    assert calls == [False, True] and len(sent) == 1


@pytest.mark.parametrize("fault,reason", [("button", "button_missing"), ("click", "click_failed"), ("progress", "playback_unconfirmed")])
@pytest.mark.parametrize("automatic", [False, True])
def test_real_error_reason_reaches_chat_and_autoplay_without_retries(flow, monkeypatch, fault, reason, automatic):
    client, app, page, sent = flow
    app.state.store.patch_settings({"music_player": "yandex", "yandex_auto_play": automatic})
    old = page.action
    def action(kind, **args):
        if kind == "wave_target" and fault == "button": raise MusicError("button_missing", "Кнопка «Моя волна» отсутствует", "target")
        value = old(kind, **args)
        if kind == "status" and fault == "progress": value["position"] = 0
        return value
    page.action = action
    if fault == "click":
        def pointer(*args): sent.append(args); raise OSError("CDP disconnected after mouse press")
        page.pointer = pointer
    result = chat(client, "Открой Яндекс Музыку" if automatic else "Запусти мою волну")
    detail = result["details"]["autoplay"] if automatic else result["details"]
    assert detail["diagnostics"]["reason"] == reason
    assert len(sent) == (0 if fault == "button" else 1)
    assert "Не удалось управлять этим плеером" not in result["display"]


def test_stale_descriptor_reports_exact_cause_without_connecting(tmp_path, monkeypatch):
    p = YandexMusic(tmp_path, Store(tmp_path), None)
    p.path.write_text(json.dumps({"pid": 123, "created": 1, "port": 32123, "exe": str(tmp_path / "YandexMusic.exe")}))
    def missing(pid): raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr("core.yandex_music.psutil.Process", missing)
    monkeypatch.setattr(p, "listeners", lambda *a: pytest.fail("Never probe a stale descriptor's port"))
    assert p.descriptor() is None
    status = p.status()
    assert not status["connected"] and status["diagnostics"]["reason"] == "stale_pid"
    assert "уже завершён" in status["error"]
