from contextlib import contextmanager
import asyncio
import json
import threading
from types import SimpleNamespace
from pathlib import Path
import httpx
import psutil

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from core.api import create_app
from core.music_intents import MusicAction, resolve, search_query
from core.yandex_music import YandexMusic, Renderer, rank, run_action
from core.storage import Store
from core import persona
from core.yandex_music import start_player, exit_waiter
from core.device_audio import resolve as audio_resolve


@pytest.mark.parametrize("text,action,value", [
    ("Пауза", "pause", None), ("Уайли, плей!", "play", None),
    ("Следующая песня", "next", None), ("Предыдущий трек", "previous", None),
    ("Добавь в любимые", "like", None), ("Убери из любимых", "unlike", None),
    ("Что сейчас играет", "status", None), ("Громкость музыки 30 процентов", "volume", 30),
    ("Сделай тише", "change_volume", -10),
    ("включи песню", "play", None), ("включи трек", "play", None),
    ("сними песню с паузы", "play", None), ("Останови музыку", "pause", None),
    ("првоерь проигрыватель", "status", None),
])
def test_whole_utterance_commands(text, action, value):
    assert resolve(text, preferred=True) == MusicAction(action=action, value=value)


@pytest.mark.parametrize("text", ["Не ставь песню", "Если включи песню Linkin Park", '«Пауза»', "Он сказал пауза", "пауза\n", "Добавь в любимые и открой блокнот", "Как добавить в любимые", "Запомни: плей"])
def test_mentions_negation_and_compound_requests_are_not_commands(text):
    assert resolve(text, preferred=True) is None


def test_music_selection_and_query_data():
    assert resolve("пауза") is None
    assert resolve("найди песню линкин парк виз ю") is None
    action = resolve("Найди песню линкин парк виз ю в Яндекс Музыке")
    assert action.action == "search_play" and search_query(action.query) == "Linkin Park With You"
    assert search_query("Something Else") == "Something Else"


def test_unspecified_song_means_resume_and_named_song_still_means_search():
    assert audio_resolve("Включи песню").action == "play"
    assert audio_resolve("Включи песню Linkin Park With You") is None
    assert resolve("Включи песню Linkin Park With You", preferred=True).action == "search_play"


@pytest.mark.parametrize("body", [{"action": "shell"}, {"action": "volume"}, {"action": "volume", "value": True}, {"action": "volume", "value": -1}, {"action": "search_play", "query": ""}, {"action": "pause", "query": "abc"}, {"action": "play", "url": "http://example.com"}])
def test_arguments_are_bounded(body):
    with pytest.raises(ValidationError): MusicAction.model_validate(body)


def test_best_match_prefers_requested_original_not_remix():
    rows = [{"id": "1", "title": "With You", "artists": "Linkin Park"}, {"id": "2", "title": "Wth>You (Reanimation)", "artists": "Linkin Park"}, {"id": "3", "title": "Lying from You", "artists": "Linkin Park"}, {"id": "evil", "title": "With You", "artists": "Linkin Park"}]
    result = rank("линкин парк виз ю", rows)
    assert result[0]["id"] == "1" and result[0]["score"] == 1
    assert result[0]["score"] - result[1]["score"] > .05


def test_unexecuted_model_favorite_claims_do_not_reach_the_user():
    assert persona.action_context("А в любимых?", [])
    assert "не изменялось" in persona.without_unexecuted_claims("Я добавила песню в любимые.")
    assert persona.without_unexecuted_claims("Мне нравится эта песня.") == "Мне нравится эта песня."
    assert "не проверялось" in persona.without_unexecuted_claims("Проверка проигрывателя завершена. Проверенный статус: музыка на паузе.")


class Page:
    def __init__(self):
        self.state = {"available": True, "id": "1", "title": "With You", "artists": "Linkin Park", "playing": False, "liked": False, "volume": 50}
        self.calls = []
        self.ignore = False
        self.rows = [{"id": "2", "title": "Numb", "artists": "Linkin Park"}]
    def action(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == "status": return dict(self.state)
        if action == "results": return {"ready": True, "rows": self.rows}
        if action == "select" and not self.ignore:
            self.state.update(id=kwargs["id"], title=kwargs["title"], artists=kwargs["artists"], playing=True)
        if action in {"play", "pause"} and not self.ignore: self.state["playing"] = action == "play"
        if action in {"like", "unlike", "toggle_like"}:
            wanted = not self.state["liked"] if action == "toggle_like" else action == "like"
            if not self.ignore: self.state["liked"] = wanted
            return {"wanted": wanted}
        if action == "volume_target": self.desired = kwargs["value"]; return {"x": 50, "y": 10}
        return {"dispatched": True}
    def pointer(self, *args):
        if not self.ignore: self.state["volume"] = self.desired


@pytest.fixture
def controller(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.patch_settings({"allow_audio_control": True, "allow_app_open": True})
    controller = YandexMusic(tmp_path, store, None)
    page = Page()
    @contextmanager
    def renderer(): yield page
    monkeypatch.setattr(controller, "renderer", renderer)
    monkeypatch.setattr("core.yandex_music.time.sleep", lambda _: None)
    return controller, page


def test_confirm_actual_result_and_audit(controller):
    player, page = controller
    for action in [MusicAction(action="play"), MusicAction(action="like"), MusicAction(action="change_volume", value=-10), MusicAction(action="search_play", query="Linkin Park Numb")]:
        assert player.execute(action)["confirmed"] is True
    assert page.state["id"] == "2" and page.state["volume"] == 40
    page.ignore = True
    assert player.execute(MusicAction(action="pause"))["confirmed"] is False
    assert player.store.list("actions")[-1]["status"] == "unconfirmed"


def test_ambiguous_search_never_plays(controller):
    player, page = controller
    page.rows.append({"id": "3", "title": "Numb", "artists": "Linkin Park"})
    result = player.execute(MusicAction(action="search_play", query="Linkin Park Numb"))
    assert result["confirmed"] is False and len(result["candidates"]) == 2
    assert not any(call[0] == "select" for call in page.calls)
    assert player.store.list("actions")[-1]["status"] == "ambiguous"


def test_permission_revocation_and_cancellation_before_dispatch(controller):
    player, page = controller
    player.store.patch_settings({"allow_audio_control": False})
    with pytest.raises(ValueError, match="отключено"): player.execute(MusicAction(action="play"))
    player.store.patch_settings({"allow_audio_control": True})
    cancel = threading.Event(); cancel.set()
    with pytest.raises(ValueError, match="остановлена"): player.execute(MusicAction(action="play"), cancel)
    assert not page.calls


def test_api_and_chat_target_yandex_without_global_media(tmp_path, monkeypatch):
    monkeypatch.setenv("WILEYAI_TEST", "1")
    def forbidden(*args, **kwargs): raise AssertionError("Must never touch another player's media controls")
    monkeypatch.setattr("core.windows_media.perform", forbidden)
    app = create_app(tmp_path, "yandex-test-0123456789abcdef")
    app.state.store.patch_settings({"allow_audio_control": True, "music_player": "yandex"})
    calls = []
    def execute(command, cancel=None):
        calls.append(command)
        return {"confirmed": True, "text": "Подтверждено тестовым плеером"}
    monkeypatch.setattr(app.state.music, "execute", execute)
    with TestClient(app, headers={"Authorization": "Bearer yandex-test-0123456789abcdef"}) as api:
        assert api.post("/music/yandex/action", json={"action": "play"}).json()["confirmed"]
        assert api.post("/commands", json={"text": "пауза"}).json()["kind"] == "music.yandex"
        assert len(calls) == 1  # Preview has no effects.
        for text in ("Следующая песня", "Найди песню Linkin Park With You", "Включи песню"):
            response = api.post("/chat", json={"text": text})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "done" and "Подтверждено" in events[-1]["message"]["content"]
        assert [c.action for c in calls] == ["play", "next", "search_play", "play"]
        assert api.post("/music/yandex/action", json={"action": "shell"}).status_code == 422


def test_connect_never_restarts_without_explicit_request(tmp_path, monkeypatch):
    store = Store(tmp_path); store.patch_settings({"allow_app_open": True, "allow_audio_control": True})
    player = YandexMusic(tmp_path, store, None)
    monkeypatch.setattr(player, "executable", lambda: tmp_path / "Яндекс Музыка.exe")
    monkeypatch.setattr("core.yandex_music.running", lambda _: [object()])
    monkeypatch.setattr("core.yandex_music.debug_port", lambda _: None)
    assert player.connect()["restart_required"] is True
    assert not player.path.exists()


def test_renderer_treats_song_text_as_data():
    class Socket:
        def send(self, raw): self.sent = json.loads(raw)
        def recv(self, **kwargs): return json.dumps({"id": self.sent["id"], "result": {"result": {"value": {"ok": True}}}})
    socket = Socket()
    assert Renderer(socket).action("search", query='\"); alert("x") //')["ok"]
    expression = socket.sent["params"]["expression"]
    assert expression.endswith('(' + json.dumps({"action": "search", "query": '\"); alert("x") //'}, ensure_ascii=False) + ')')


def test_cancel_waits_for_dispatched_operation(controller):
    player, _ = controller
    began, finish = threading.Event(), threading.Event()
    def execute(command, cancel):
        began.set(); finish.wait(2)
        assert cancel.is_set()
        return {"text": "Пауза действительно выполнена"}
    player.execute = execute
    async def run():
        progress = []
        task = asyncio.create_task(run_action(player, MusicAction(action="pause"), progress))
        await asyncio.to_thread(began.wait, 1)
        task.cancel(); await asyncio.sleep(.01)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert progress == ["Пауза действительно выполнена"]
    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "desktop", "foreign_desktop", "foreign_pid", "public_bind", "foreign_page", "foreign_socket"])
def test_debug_channel_is_process_bound_loopback_and_page_scoped(tmp_path, monkeypatch, fault):
    player = YandexMusic(tmp_path, Store(tmp_path), None)
    data = {"pid": 12, "exe": str(tmp_path / "Яндекс Музыка.exe"), "port": 32123}
    monkeypatch.setattr(player, "descriptor", lambda: data)
    monkeypatch.setattr("core.yandex_music.psutil.Process", lambda _: SimpleNamespace(children=lambda **_: []))
    listener = SimpleNamespace(pid=13 if fault == "foreign_pid" else 12, status="LISTEN", laddr=SimpleNamespace(port=32123, ip="0.0.0.0" if fault == "public_bind" else "127.0.0.1"))
    monkeypatch.setattr("core.yandex_music.psutil.net_connections", lambda **_: [listener])
    page = {"type": "page", "url": "https://evil.example/" if fault == "foreign_page" else (tmp_path / "resources" / "index.html").as_uri(), "webSocketDebuggerUrl": "ws://127.0.0.1:32123/devtools/page/test"}
    if fault == "desktop": page["url"] = "music-application://desktop/"
    if fault == "foreign_desktop": page["url"] = "music-application://evil.example/"
    if fault == "foreign_socket": page["webSocketDebuggerUrl"] = "ws://example.com:32123/devtools/page/test"
    class Client:
        def __init__(self, **kwargs): assert kwargs == {"trust_env": False, "follow_redirects": False, "timeout": 3}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url): return httpx.Response(200, json=[page], request=httpx.Request("GET", url))
    monkeypatch.setattr("core.yandex_music.httpx.Client", Client)
    @contextmanager
    def connect(url, **kwargs):
        assert url == page["webSocketDebuggerUrl"] and kwargs["proxy"] is None
        yield object()
    monkeypatch.setattr("websockets.sync.client.connect", connect)
    if fault not in {None, "desktop"}:
        with pytest.raises(ValueError):
            with player.renderer(): pytest.fail("Untrusted connection admitted")
    else:
        with player.renderer() as renderer: assert isinstance(renderer, Renderer)


def test_windows_launch_uses_shell_for_application_elevation(monkeypatch, tmp_path):
    import os
    if os.name != "nt": pytest.skip("Windows shell launch")
    calls = []
    monkeypatch.setattr("core.yandex_music.shell_launch", lambda exe, **kw: calls.append((exe, kw)))
    executable = tmp_path / "Яндекс Музыка.exe"
    start_player(executable, 32123)
    assert calls == [(executable, {"arguments": ["--remote-debugging-port=32123", "--remote-debugging-address=127.0.0.1"], "directory": tmp_path})]


@pytest.mark.parametrize("error", [OSError(740, "elevation required"), psutil.AccessDenied(123)])
def test_connect_native_errors_are_readable_json_and_audited(tmp_path, monkeypatch, error):
    monkeypatch.setenv("WILEYAI_TEST", "1")
    app = create_app(tmp_path, "yandex-tests-0123456789abcdef")
    def fail(*args): raise error
    monkeypatch.setattr(app.state.music, "_connect", fail)
    with TestClient(app, headers={"Authorization": "Bearer yandex-tests-0123456789abcdef"}) as api:
        response = api.post("/music/yandex/connect", json={"restart": True}, headers={"Origin": "app://wileyai"})
        assert response.status_code == 400 and "Windows" in response.json()["detail"]
        assert response.headers["access-control-allow-origin"] == "app://wileyai"
        assert app.state.store.list("actions")[-1]["status"] == "error"


def test_windows_exit_waiter_keeps_handle_before_termination(tmp_path, monkeypatch):
    import os, subprocess, sys, psutil
    if os.name != "nt": pytest.skip("Windows native synchronization")
    process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=subprocess.CREATE_NO_WINDOW)
    def forbidden(*args, **kwargs): raise AssertionError("Do not reopen terminated processes through psutil.wait_procs")
    monkeypatch.setattr("core.yandex_music.psutil.wait_procs", forbidden)
    try:
        with exit_waiter([psutil.Process(process.pid)]) as wait:
            process.terminate()
            assert wait()
    finally:
        if process.poll() is None: process.terminate()
        process.wait(timeout=5)
