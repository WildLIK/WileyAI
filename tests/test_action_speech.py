import json

import pytest
from fastapi.testclient import TestClient

from core import commands
from core.api import create_app
from core.launch_verification import ExecutionText
from core.storage import Store


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    exe = tmp_path / "Blender.exe"; exe.touch()
    app = create_app(tmp_path, "speech-route-tests-0123456789")
    row = {"id": "blender", "name": "Blender", "target": str(exe), "source": "Меню", "category": "work", "aliases": []}
    monkeypatch.setattr(app.state.applications, "find_matches", lambda name: [row] if name.casefold() == "blender" else [])
    monkeypatch.setattr(app.state.applications, "suggest_matches", lambda name: [])
    with TestClient(app, headers={"Authorization": "Bearer speech-route-tests-0123456789"}) as client:
        yield client, app, exe, row


def send(client, text, **kwargs):
    response = client.post("/chat", json={"text": text, "mode": "conversation", **kwargs})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("status,phrase", [
    ("process_started", "Процесс Blender запущен."),
    ("already_running", "Blender уже запущен."),
    ("dispatched", "Результат не подтверждён."),
])
def test_real_chat_stream_separates_open_diagnostics_and_spoken_result(ctx, monkeypatch, status, phrase):
    client, app, exe, row = ctx
    monkeypatch.setattr(commands, "execute", lambda *args, **kw: ExecutionText("PID 30728. Проверенный EXE: " + str(exe), {"status": status, "pid": 30728, "executable": str(exe)}))
    events = send(client, "Открой Blender")
    mode = next(i for i, e in enumerate(events) if e["type"] == "speech_mode")
    delta = next(i for i, e in enumerate(events) if e["type"] == "delta")
    result = next(e["action"] for e in events if e["type"] == "speech_result")
    assert mode < delta and phrase in result["spoken"]
    assert "30728" in result["display"] and str(exe) in result["display"]
    assert "30728" not in result["spoken"] and str(exe) not in result["spoken"]
    assert len([e for e in events if e["type"] == "speech_result"]) == 1


def test_failed_disabled_missing_and_inspection_speech_are_short(ctx, monkeypatch):
    client, app, exe, row = ctx
    def fail(*args, **kw): raise ValueError("Windows internal C:\\secret\\Blender.exe PID 123")
    monkeypatch.setattr(commands, "execute", fail)
    failed = send(client, "Запусти Blender")
    result = next(e["action"] for e in failed if e["type"] == "speech_result")
    assert result["status"] == "error" and result["spoken"] == "Не удалось открыть Blender."
    assert "secret" in result["display"] and "secret" not in result["spoken"]
    checked = send(client, "Проверь, установлен ли Blender")
    assert next(e["action"]["spoken"] for e in checked if e["type"] == "speech_result").startswith("Нашла Blender")
    missing = send(client, "Открой НеизвестнаяПрограмма")
    assert next(e["action"]["status"] for e in missing if e["type"] == "speech_result") == "not_found"
    Store(app.state.store.root).patch_settings({"allow_app_open": False})
    denied = send(client, "Открой Blender")
    assert next(e["action"]["status"] for e in denied if e["type"] == "speech_result") == "denied"


def test_speech_start_emitted_only_at_verified_dispatch(ctx, monkeypatch):
    from core import launch_verification
    client, app, exe, row = ctx
    process_calls = iter([set(), {1234}])
    monkeypatch.setattr(launch_verification, "process_ids", lambda path: next(process_calls))
    monkeypatch.setattr(launch_verification, "shell_launch", lambda target: None)
    events = send(client, "Открой Blender")
    assert next(e["text"] for e in events if e["type"] == "speech_start") == "Запускаю Blender."
    assert next(e["action"]["status"] for e in events if e["type"] == "speech_result") == "process_started"
    Store(app.state.store.root).patch_settings({"allow_app_open": False})
    assert not any(e["type"] == "speech_start" for e in send(client, "Открой Blender"))


def test_indirect_request_waits_for_confirmation_and_can_cancel(ctx, monkeypatch):
    client, app, exe, row = ctx
    app.state.store.add_alias("Blender", "app", str(exe))
    called = []
    monkeypatch.setattr(commands, "execute", lambda *a, **kw: called.append(1) or "opened")
    events = send(client, "Мне нужен Blender")
    assert not called and next(e["action"]["status"] for e in events if e["type"] == "speech_result") == "clarification"
    result = send(client, "Нет, я имел в виду другое приложение")
    assert not called and next(e["action"]["status"] for e in result if e["type"] == "speech_result") == "cancelled"


def test_approximate_app_name_never_runs_without_confirmation(ctx, monkeypatch):
    client, app, exe, row = ctx
    called = []
    monkeypatch.setattr(app.state.applications, "find_matches", lambda name: [])
    monkeypatch.setattr(app.state.applications, "suggest_matches", lambda name: [row])
    monkeypatch.setattr(commands, "execute", lambda *a, **kw: called.append(1) or "opened")
    events = send(client, "Запускай Блендер")
    assert not called and next(e["action"]["status"] for e in events if e["type"] == "speech_result") == "clarification"


def test_phone_target_never_executes_a_pc_alias(ctx, monkeypatch):
    client, app, exe, row = ctx
    app.state.store.add_alias("Blender на телефоне", "app", str(exe))
    calls = []
    monkeypatch.setattr(commands, "execute", lambda *a, **kw: calls.append(1) or "opened")
    events = send(client, "Открой Blender на телефоне")
    assert not calls and next(e["action"]["status"] for e in events if e["type"] == "speech_result") == "phone_unavailable"


def test_voice_mode_setting_is_saved_and_defaults_to_brief(ctx):
    client, app, exe, row = ctx
    assert client.get("/settings").json()["action_speech"] == "brief"
    assert client.put("/settings/speech", json={"action_speech": "off"}).json()["action_speech"] == "off"
    assert Store(app.state.store.root).settings().action_speech == "off"
    from core.backups import Backups
    backups = Backups(app.state.store)
    exported = backups.export()
    app.state.store.patch_settings({"action_speech": "full"})
    backups.restore(backups.preview(exported)["ticket"])
    assert Store(app.state.store.root).settings().action_speech == "off"


def test_explicit_read_previous_sends_full_answer_even_in_off_mode(ctx):
    client, app, exe, row = ctx
    app.state.store.add_message("assistant", "Полный технический ответ. PID 123.")
    app.state.store.patch_settings({"action_speech": "off"})
    events = send(client, "Прочитай полный ответ")
    assert next(e["mode"] for e in events if e["type"] == "speech_mode") == "read_full"
    assert next(e["action"]["spoken"] for e in events if e["type"] == "speech_result") == "Полный технический ответ. PID 123."


def test_music_and_volume_use_evidence_without_reading_diagnostics(ctx, monkeypatch):
    client, app, exe, row = ctx
    monkeypatch.setattr("core.device_audio.AudioTools.execute", lambda self, command, dry_run=False: {"text": "Windows internal ID 123", "volume": 50, "muted": False})
    events = send(client, "Громкость 50")
    result = next(e["action"] for e in events if e["type"] == "speech_result")
    assert result["spoken"] == "Громкость — 50 процентов." and "ID 123" in result["display"]


def test_ordinary_llm_text_and_full_document_have_no_action_speech_gate(ctx, monkeypatch):
    from core.document_library import Library
    client, app, exe, row = ctx
    async def chat(*args, **kwargs):
        yield "Привет. "
        yield "Я рада тебя видеть."
    monkeypatch.setattr("core.providers.chat", chat)
    events = send(client, "Расскажи, как прошёл день")
    assert not any(e["type"] == "speech_mode" for e in events)
    assert "Привет" in "".join(e.get("text", "") for e in events if e["type"] == "delta")
    doc = Library(app.state.store).add("Книга.txt", "Текст документа.")
    async def respond(*args, **kwargs):
        yield {"type": "delta", "text": "Полное содержание документа."}
    monkeypatch.setattr("core.document_summary.respond", respond)
    events = send(client, "Прочитай весь документ", document_ids=[doc["id"]], full_document=True)
    assert not any(e["type"] == "speech_mode" for e in events)
    assert any("Полное содержание" in e.get("text", "") for e in events if e["type"] == "delta")
