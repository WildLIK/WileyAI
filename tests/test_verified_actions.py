import json
from pathlib import Path
import subprocess
import os

import psutil
import pytest
from fastapi.testclient import TestClient

from core import launch_verification as launches, windows_media, commands, providers
from core.api import create_app
from core.storage import Store
from core.device_audio import AudioAction, AudioTools, resolve


@pytest.mark.parametrize("before,after,status", [(set(), {42}, "process_started"), ({42}, {42}, "already_running"), (set(), set(), "dispatched")])
def test_launch_reports_only_observed_processes(tmp_path, monkeypatch, before, after, status):
    executable = tmp_path / "Actual App.exe"
    executable.touch()
    snapshots = iter([before, after])
    monkeypatch.setattr(launches, "process_ids", lambda path: next(snapshots))
    dispatched = []
    monkeypatch.setattr(launches, "shell_launch", dispatched.append)
    times = iter([0, 4])
    monkeypatch.setattr(launches.time, "monotonic", lambda: next(times))
    result = launches.application(str(executable), "Приложение")
    assert dispatched == [str(executable)]
    assert result.evidence["status"] == status
    assert result.evidence.get("pid") == (42 if after else None)
    assert ("PID 42" in result) == bool(after)
    assert status != "dispatched" or "не подтверждён" in result


def test_exact_executable_not_merely_same_process_name(monkeypatch, tmp_path):
    class Process:
        info = {"pid": 10, "exe": str(tmp_path / "Other" / "app.exe")}
    monkeypatch.setattr(launches.psutil, "process_iter", lambda attrs: [Process()])
    assert launches.process_ids(tmp_path / "Mine" / "app.exe") == set()


@pytest.mark.skipif(os.name != "nt", reason="Windows ShellExecuteEx")
def test_native_shell_launch_confirms_an_isolated_windowless_helper(tmp_path):
    executable = tmp_path / "VerifiedHelper.exe"
    script = r"$p=[Console]::In.ReadToEnd(); Add-Type -TypeDefinition 'class VerifiedHelper { static void Main() { System.Threading.Thread.Sleep(10000); } }' -OutputAssembly $p -OutputType WindowsApplication"
    powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], input=str(executable), encoding="utf-8", capture_output=True, timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = launches.application(str(executable), "Изолированный помощник теста")
        assert result.evidence["status"] == "process_started"
        assert result.evidence["pid"] in launches.process_ids(executable)
    finally:
        for pid in launches.process_ids(executable):
            process = psutil.Process(pid)
            assert Path(process.exe()).resolve() == executable.resolve()
            process.terminate()
            process.wait(5)


@pytest.mark.parametrize("text,action", [("Запустим музыку", None), ("Поставь музыку на паузу", "pause"), ("Поставь на паузу", "pause"), ("Продолжи музыку", "play"), ("Где музыка?", "media_status")])
def test_natural_media_commands_are_typed(text, action):
    found = resolve(text)
    assert (found.action if found else None) == action


def test_aimp_pause_is_idempotent_and_does_not_resume_paused_player():
    player = object.__new__(windows_media.Aimp)
    state, sent = {"code": 1}, []
    player.read = lambda: {**state, "state": windows_media.STATES[state["code"]], "player": "AIMP", "available": True}
    def send(message, command):
        sent.append(command)
        state["code"] = 2 if state["code"] == 1 else 1
    player.send = send
    assert player.perform("pause")["confirmed"]
    assert sent == []
    state["code"] = 2
    assert player.perform("pause")["confirmed"]
    assert sent == [15]
    assert player.perform("pause")["confirmed"]
    assert sent == [15]


def test_media_refusal_and_no_session_never_claim_playback(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(windows_media, "perform", lambda action="read": {"available": False})
    result = AudioTools(store).execute(AudioAction(action="play"))
    assert "не найден" in result["text"] and "не отправлена" in result["text"]
    assert store.list("actions")[0]["status"] == "unconfirmed"
    assert "не принял" in windows_media.describe({"available": True, "backend": "smtc", "player": "Player", "state": "Пауза", "accepted": False, "action": "play"})


@pytest.mark.parametrize("claim", ["Музыка запущена.", "Запускаю «Имп».", "Поставила музыку на паузу.", "Выключу музыку.", "Проверю наличие Яндекс Браузера в системе.", "Проверила: браузер не найден."])
def test_unexecuted_model_claims_do_not_reach_chat_or_speech(tmp_path, monkeypatch, claim):
    async def fake(*args):
        for character in claim:
            yield character
    monkeypatch.setattr(providers, "chat", fake)
    token = "verified-actions-tests-0123456789"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        result = api.post("/chat", json={"text": "Программа IIMP"})
        events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
        text = "".join(event["text"] for event in events if event["type"] == "delta")
        assert claim not in text and "не выполнялась" in text
        assert api.get("/actions").json() == []
        assert api.get("/messages").json()[-1]["content"] == text


def test_yandex_music_spoken_dot_uses_added_app(tmp_path):
    target = str(tmp_path / "Music.exe")
    aliases = [{"name": "Яндекс Музыка", "target": target, "kind": "app"}]
    assert commands.resolve("Открой Яндекс.Музыку", aliases).target == target


def test_lets_start_music_controls_existing_player_without_model(tmp_path, monkeypatch):
    calls = []
    def media(action="read"):
        calls.append(action)
        return {"available": True, "player": "Test Player", "state": "Воспроизведение", "confirmed": action == "play", "accepted": True}
    monkeypatch.setattr(windows_media, "perform", media)
    async def forbidden(*args):
        pytest.fail("A real media command must not be answered by the model")
        yield ""
    monkeypatch.setattr(providers, "chat", forbidden)
    token = "verified-actions-tests-0123456789"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        response = api.post("/chat", json={"text": "Запустим музыку"})
        assert "Плеер подтвердил" in response.text and calls == ["read", "play"]
        entry = api.get("/actions").json()[0]
        assert entry["status"] == "confirmed" and entry["details"]["media"]["player"] == "Test Player"
        store = Store(tmp_path)
        store.patch_settings({"allow_audio_control": False})
        api.post("/chat", json={"text": "Поставь музыку на паузу"})
        assert "pause" not in calls


def test_failed_media_response_does_not_send_a_second_toggle(tmp_path, monkeypatch):
    def media(action="read"):
        if action == "read": return {"available": True}
        raise ValueError("Ответ потерян после запроса")
    monkeypatch.setattr(windows_media, "perform", media)
    monkeypatch.setattr("core.windows_audio.send_media", lambda action: pytest.fail("Must not toggle twice after an uncertain player response"))
    with pytest.raises(ValueError, match="Ответ потерян"):
        AudioTools(Store(tmp_path)).execute(AudioAction(action="play_pause"))
