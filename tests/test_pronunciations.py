import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import app_discovery, commands, pronunciations
from core.api import create_app
from core.backups import Backups
from core.intent_interpreter import interpret
from core.launch_verification import ExecutionText
from core.storage import Store
from core.voice import speech_prompt


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    rows = []
    for index, name in enumerate(["OBS Studio", "Other Studio"]):
        path = tmp_path / f"app{index}.exe"; path.touch()
        rows.append({"id": f"app{index}", "name": name, "target": str(path), "source": "Меню", "category": "other", "aliases": []})
    monkeypatch.setattr(app_discovery, "discover", lambda: {"supported": True, "items": rows, "warnings": []})
    app = create_app(tmp_path, "pronunciation-tests-token-12345")
    app.state.applications.scan()
    with TestClient(app, headers={"Authorization": "Bearer pronunciation-tests-token-12345"}) as client:
        yield client, app, rows


def chat(client, text):
    response = client.post("/chat", json={"text": text, "mode": "conversation"})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_explicit_correction_persists_and_survives_move_and_backup(catalog, monkeypatch, tmp_path):
    client, app, rows = catalog
    calls = []
    monkeypatch.setattr(commands, "execute", lambda command, **kwargs: calls.append(command.target) or ExecutionText("PID 42", {"status": "process_started"}))
    first = chat(client, "Открой ОПС")
    assert not calls and any(e.get("action", {}).get("status") == "clarification" for e in first)
    selected = chat(client, "да")
    assert calls == [rows[0]["target"]] and "Запомнить произношение" in str(selected)
    assert not client.get("/voice/pronunciations").json()
    accepted = chat(client, "да")
    assert "Запомнила произношение" in str(accepted)
    assert len(Store(tmp_path).settings().pronunciations) == 1
    rules = Store(tmp_path).settings().pronunciations
    moved = tmp_path / "new-place.exe"; moved.touch()
    rows[0]["target"] = str(moved)
    app.state.applications.scan()
    assert pronunciations.candidates(app.state.applications, rules, "опс")[0]["target"] == str(moved)
    backup = Backups(app.state.store); data = backup.export()
    app.state.store.patch_settings({"pronunciations": []})
    backup.restore(backup.preview(data)["ticket"])
    assert len(Store(tmp_path).settings().pronunciations) == 1
    chat(client, "Открой ОПС")
    assert calls[-1] == str(moved)


def test_no_learning_without_second_consent_and_cancel(catalog, monkeypatch):
    client, app, rows = catalog
    calls = []
    monkeypatch.setattr(commands, "execute", lambda command, **kwargs: calls.append(command.target) or "sent")
    chat(client, "Открой ОПС"); chat(client, "отмена")
    assert not calls and not client.get("/voice/pronunciations").json()
    chat(client, "Открой ОПС"); chat(client, "да"); chat(client, "нет")
    assert len(calls) == 1 and not client.get("/voice/pronunciations").json()


def test_conflicts_preview_disable_delete_and_permission(catalog, monkeypatch):
    client, app, rows = catalog
    calls = []
    monkeypatch.setattr(commands, "execute", lambda command, **kwargs: calls.append(command.target) or "sent")
    rules = [client.post("/voice/pronunciations", json={"application_id": row["id"], "spoken": "опс"}).json() for row in rows]
    preview = client.post("/voice/pronunciations/preview", json={"text": "Открой опс"}).json()
    assert preview["match"] == "неоднозначно" and preview["requires_confirmation"] and not calls
    assert "вариант" in str(chat(client, "Открой опс")) and not calls
    client.put(f"/voice/pronunciations/{rules[1]['id']}", json={"application_id": rows[1]["id"], "spoken": "опс", "enabled": False})
    assert client.post("/voice/pronunciations/preview", json={"text": "Открой опс"}).json()["match"] == "подтверждённое произношение"
    app.state.store.patch_settings({"allow_app_open": False})
    chat(client, "Открой опс")
    assert not calls
    client.delete(f"/voice/pronunciations/{rules[0]['id']}")
    assert len(client.get("/voice/pronunciations").json()) == 1


def test_prompt_is_bounded_and_never_contains_paths_or_documents():
    prompt = speech_prompt("Уайли", ["ОПС", "OBS Studio", r"C:\secret\password", "A" * 400])
    assert "ОПС" in prompt and "OBS Studio" in prompt and "password" not in prompt and len(prompt) <= 800


def test_diagnostics_and_whisper_context_do_not_change_transcript(catalog, monkeypatch):
    from core.voice import Voice
    client, app, rows = catalog
    client.post("/voice/pronunciations", json={"application_id": rows[0]["id"], "spoken": "опс"})
    app.state.store.patch_settings({"voice_diagnostics": True})
    received = []
    def transcribe(self, data, model, hint="", quality="accurate", environment="normal", vocabulary=()):
        received.append((model, vocabulary))
        return "Открой опыс"
    monkeypatch.setattr(Voice, "transcribe", transcribe)
    result = client.post("/voice/transcribe", files={"file": ("audio.wav", b"fake", "audio/wav")}).json()
    assert result["text"] == "Открой опыс" and result["diagnostics"]["engine"] == "small"
    assert "опс" in received[-1][1]
    app.state.store.patch_settings({"stt_model": "gigaam-v3"})
    result = client.post("/voice/transcribe", files={"file": ("audio.wav", b"fake", "audio/wav")}).json()
    assert result["text"] == "Открой опыс" and received[-1] == ("gigaam-v3", ())
    assert any(event["type"] == "voice_diagnostic" for event in chat(client, result["text"]))


def test_stale_general_settings_form_does_not_erase_rule(catalog):
    client, app, rows = catalog
    old = client.get("/settings").json()
    assert client.post("/voice/pronunciations", json={"application_id": rows[0]["id"], "spoken": "опс"}).status_code == 200
    assert client.put("/settings", json=old).status_code == 200
    assert len(client.get("/voice/pronunciations").json()) == 1


def test_repeated_transcription_is_not_treated_as_single_command(catalog, monkeypatch):
    from core.intents import opening_request
    client, app, rows = catalog
    monkeypatch.setattr(commands, "execute", lambda *args, **kwargs: pytest.fail("Repeated phrase must not launch"))
    phrase = "Открой OBS Studio. Открой OBS Studio."
    assert interpret(phrase) is None and opening_request(phrase) is None and commands.resolve(phrase, []) is None


@pytest.mark.parametrize("name", ["OBS", "Blender", "RPGReactor", "VS Code", "AIMP", "Firefox", "Codex", "Telegram", "Krita", "Audacity"])
@pytest.mark.parametrize("template", [
    "Не открывай {}", "Никогда не запускай {}", "Как открыть {}?", "Если я скажу открыть {}", "Он попросил открыть {}", "Она сказала запустить {}", "Расскажи про {}", "Объясни как запустить {}", "Почему не работает {}?", "\"Открой {}\"", "Открой {} и удали файл", "Открой {} на телефоне",
])
def test_non_commands_and_phone_do_not_become_pc_open(name, template):
    intent = interpret(template.format(name))
    assert intent is None or intent.device == "phone"
