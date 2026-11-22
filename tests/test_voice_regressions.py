"""User's seven Windows regressions. Native side effects are deliberately mocked."""
from contextlib import contextmanager
import json
import time

import pytest
from fastapi.testclient import TestClient

from core import app_discovery, commands, intent_interpreter, intents, providers, windows_audio
from core.api import create_app
from core.device_audio import AudioAction, AudioTools
from core.launch_verification import ExecutionText
from core.storage import Store


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    rows = []
    for number, name in enumerate(["Blender", "Blender", "OBS Studio", "AIMP"]):
        path = tmp_path / str(number) / ("blender.exe" if name == "Blender" else name.split()[0] + ".exe")
        path.parent.mkdir(); path.touch()
        rows.append({"id": str(number), "name": name, "target": str(path), "source": "Меню", "category": "work", "aliases": []})
    monkeypatch.setattr(app_discovery, "discover", lambda: {"supported": True, "items": rows, "warnings": []})
    app = create_app(tmp_path, "voice-regression-tests-0123456789")
    app.state.applications.scan()
    calls, llm = [], []
    def launch(command, **kwargs):
        calls.append(command.target)
        return ExecutionText("Windows приняла запрос; окно не проверено.", {"status": "dispatched"})
    monkeypatch.setattr(commands, "execute", launch)
    async def model(*args, **kwargs):
        llm.append(1)
        yield "Программа OBS Studio открыта. Закрываю Blender. Громкость уменьшена на 35 процентов."
    monkeypatch.setattr(providers, "chat", model)
    with TestClient(app, headers={"Authorization": "Bearer voice-regression-tests-0123456789"}) as client:
        yield client, app, rows, calls, llm


def send(client, text, **kwargs):
    result = client.post("/chat", json={"text": text, "mode": "conversation", **kwargs})
    assert result.status_code == 200
    events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
    return events, "".join(event.get("text", "") for event in events if event["type"] == "delta")


@pytest.mark.parametrize("text", ["Не открывай Blender", "Не запускай OBS", "Не надо открывать Telegram", "Отмени запуск Blender", "Закрой Blender"])
def test_prohibition_cancellation_and_unsupported_close_never_delegate(ctx, text):
    client, app, rows, calls, llm = ctx
    events, answer = send(client, text)
    assert not calls and not llm
    assert "закрываю" not in answer.casefold() and "открыта" not in answer.casefold()
    assert any(event["type"] == "speech_result" for event in events)
    if text.startswith("Не "):
        assert "не буду открывать" in answer


@pytest.mark.parametrize("phrase", ["Первый вариант", "Приложение номер один", "Открой первый", "Первый", "Номер один"])
def test_candidate_selection_dispatches_once_and_only_with_current_context(ctx, phrase):
    client, app, rows, calls, llm = ctx
    _, answer = send(client, "Открой блендер")
    assert "номер" in answer and not calls
    send(client, phrase)
    assert calls == [rows[0]["target"]] and not llm


def test_unclear_choice_keeps_original_ttl_and_can_be_followed_by_selection(ctx):
    client, app, rows, calls, llm = ctx
    send(client, "Открой блендер")
    created = app.state.store.for_chat(None).dialogue()["pending_open"]["created"]
    _, answer = send(client, "Вариант")
    assert "номер" in answer and not calls and not llm
    assert app.state.store.for_chat(None).dialogue()["pending_open"]["created"] == created
    send(client, "Приложение номер один")
    assert calls == [rows[0]["target"]]


def test_stale_cancelled_and_cross_chat_selection_cannot_launch(ctx):
    client, app, rows, calls, llm = ctx
    send(client, "Открой блендер")
    scoped = app.state.store.for_chat(None)
    state = scoped.dialogue(); state["pending_open"]["created"] = time.time() - intents.TTL - 1; scoped.save_dialogue(state)
    send(client, "Первый вариант")
    assert not calls and not llm
    send(client, "Открой блендер"); send(client, "отмена"); send(client, "Первый вариант")
    assert not calls and not llm
    send(client, "Открой блендер")
    other = client.post("/conversations", json={"title": "Другой чат"}).json()
    send(client, "Первый вариант", conversation_id=other["id"])
    assert not calls and not llm


@pytest.mark.parametrize("text", ["Открой OBS Studio", "Открой. OBS Studio"])
def test_obvious_open_uses_tool_once_not_model(ctx, text):
    client, app, rows, calls, llm = ctx
    events, answer = send(client, text, request_id="obs-regression")
    assert calls == [rows[2]["target"]] and not llm
    assert "окно не проверено" in answer and "открыта" not in answer
    traces = [row for row in app.state.store.list("actions", 100) if row["kind"] == "command.trace"]
    trace = json.loads(traces[-1]["details"])
    assert trace["request_id"] == "obs-regression" and trace["status"] == "dispatched"
    assert any(step["phase"] == "command.tool" for step in trace["steps"])


@pytest.mark.parametrize("text", ["Открой. OBS Studio и удали файл", "Открой OBS. Закрой Blender", "Валь. Проверь, открыт лимп", "О, Алиса, запусти орбиатор"])
def test_unclear_action_never_reaches_a_hallucinating_model(ctx, text):
    client, app, rows, calls, llm = ctx
    _, answer = send(client, text)
    assert not calls and not llm
    assert "уточните" in answer.casefold()


def test_plain_question_still_uses_the_model(ctx):
    client, app, rows, calls, llm = ctx
    _, answer = send(client, "Как закрыть Blender?")
    assert llm == [1] and not calls
    assert "Программа OBS Studio открыта" not in answer and "Закрываю Blender" not in answer


def test_player_volume_without_selected_player_is_clarification(ctx):
    client, app, rows, calls, llm = ctx
    _, answer = send(client, "Сделай музыку потише")
    assert ("громкость" in answer or "медиасессия не найдена" in answer) and not calls and not llm


def test_failed_launch_never_claims_success(ctx, monkeypatch):
    client, app, rows, calls, llm = ctx
    def failed(command, **kwargs):
        calls.append(command.target)
        raise ValueError("Отказ Windows")
    monkeypatch.setattr(commands, "execute", failed)
    events, answer = send(client, "Открой OBS Studio")
    assert len(calls) == 1 and not llm
    assert "открыта" not in answer and any(event.get("action", {}).get("status") == "error" for event in events)


def test_running_is_a_process_query_not_installation_or_window(ctx, monkeypatch):
    client, app, rows, calls, llm = ctx
    queried = []
    monkeypatch.setattr("core.launch_verification.process_ids", lambda target: queried.append(target) or {42})
    _, answer = send(client, "Проверь, работает ли AIMP")
    assert queried == [rows[3]["target"]] and not calls and not llm
    assert "Процесс AIMP работает" in answer and "окна не проверено" in answer


def test_same_blender_pair_is_merged_but_other_directory_is_preserved(tmp_path):
    def item(path, name):
        path.parent.mkdir(exist_ok=True); path.touch()
        return {"id": str(path), "name": name, "target": str(path), "source": "Тест", "aliases": []}
    first = item(tmp_path / "v52" / "blender.exe", "Blender")
    launcher = item(tmp_path / "v52" / "blender-launcher.exe", "Blender 5.2")
    second = item(tmp_path / "v51" / "blender.exe", "Blender 5.1")
    result = app_discovery.distinct_installations([launcher, first, second])
    assert len(result) == 2 and {row["target"] for row in result} == {first["target"], second["target"]}
    assert "Blender 5.2" in result[0]["aliases"]


def test_endpoint_readback_must_match_volume_request(tmp_path, monkeypatch):
    writes = []
    class Device:
        def read(self): return {"volume": 60, "muted": False}
        def set_volume(self, value): writes.append(value)  # Device refuses change.
    @contextmanager
    def endpoint(): yield Device()
    monkeypatch.setattr(windows_audio, "endpoint", endpoint)
    with pytest.raises(ValueError, match="не подтвердила"):
        AudioTools(Store(tmp_path)).execute(AudioAction(action="change_volume", value=-10))
    assert writes == [50]


def test_prohibition_is_not_a_permanent_ban_and_replay_never_dispatches(ctx):
    client, app, rows, calls, llm = ctx
    send(client, "Не открывай OBS Studio")
    assert not calls
    replay = client.post("/commands/replay", json={"text": "Открой. OBS Studio"}).json()
    assert replay["candidates"] == ["OBS Studio"] and replay["dispatched"] is False and not calls
    send(client, "Открой OBS Studio")
    assert calls == [rows[2]["target"]] and not llm


def test_transcript_ticket_is_correlated_without_persisting_raw_audio_or_text(ctx, monkeypatch):
    from core.voice import Voice
    client, app, rows, calls, llm = ctx
    monkeypatch.setattr(Voice, "transcribe", lambda *args: "Открой. OBS Studio")
    result = client.post("/voice/transcribe", files={"file": ("speech.wav", b"fake", "audio/wav")}, data={"trace": "true"}).json()
    assert result["text"] == "Открой. OBS Studio"
    send(client, "Открой. OBS Studio", recognition_id=result["recognition_id"], request_id="transcript-trace")
    traces = [json.loads(row["details"]) for row in app.state.store.list("actions", 100) if row["kind"] == "command.trace"]
    assert traces[0]["stt"]["recognition_id"] == result["recognition_id"]
    assert traces[0]["stt"]["engine"] == "small" and "raw_text" not in traces[0]["stt"]
    assert len(calls) == 1 and not llm
