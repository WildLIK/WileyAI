import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import app_discovery as discovery, commands
from core.api import create_app


def item(path, name, source="Ярлык меню «Пуск»"):
    return {"id": path.stem + str(path.parent.name), "name": name, "category": "other", "target": str(path), "source": source, "aliases": []}


def test_unknown_registry_candidate_and_broken_shortcut_do_not_run(tmp_path, monkeypatch):
    exe = tmp_path / "RPGReactor.exe"; exe.touch()
    broken = tmp_path / "Broken.lnk"; broken.touch()
    monkeypatch.setattr(discovery, "registry_candidates", lambda: [discovery.Candidate("", str(exe), "Регистрация Windows", "RPGReactor")])
    monkeypatch.setattr(discovery, "installed_registry_candidates", lambda: [])
    monkeypatch.setattr(discovery, "packaged_candidates", lambda: [])
    monkeypatch.setattr(discovery, "location_candidates", lambda: [])
    monkeypatch.setattr(discovery, "menu_links", lambda roots: ([(None, broken)], False))
    monkeypatch.setattr(discovery, "shortcut_targets", lambda paths: {str(broken): str(tmp_path / "missing.exe")})
    monkeypatch.setattr(commands, "execute", lambda *args, **kwargs: pytest.fail("Scanning must never launch programs"))
    result = discovery.discover()
    assert [(row["name"], row["category"], row["target"]) for row in result["items"]] == [("RPGReactor", "other", str(exe))]


def test_unknown_app_paths_registration_is_enumerated(tmp_path, monkeypatch):
    exe = tmp_path / "RPGReactor.exe"; exe.touch()
    class Key:
        def __init__(self, name): self.name = name
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def open_key(parent, name, *args):
        if isinstance(parent, Key):
            if name != "RPGReactor.exe": raise OSError()
            return Key(name)
        return Key("parent")
    def enum_key(parent, index):
        if index: raise OSError()
        return "RPGReactor.exe"
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_64KEY=1, KEY_WOW64_32KEY=2,
                           KEY_READ=4, REG_SZ=1, REG_EXPAND_SZ=2, OpenKey=open_key, EnumKey=enum_key,
                           QueryValueEx=lambda key, name: (str(exe), 1))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    found = discovery.registry_candidates()
    assert found and all(row.name == "RPGReactor" and row.path == str(exe) for row in found)


@pytest.mark.skipif(os.name != "nt", reason="Windows shell-link COM fixture")
def test_real_unknown_start_menu_shortcut_resolves_to_exe_without_arguments(tmp_path, monkeypatch):
    exe = tmp_path / "RPGReactor.exe"; exe.touch()
    link = tmp_path / "RPGReactor.lnk"
    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    import json
    script = "[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false);$p=ConvertFrom-Json ([Console]::In.ReadToEnd());$s=New-Object -ComObject WScript.Shell;$l=$s.CreateShortcut($p.link);$l.TargetPath=$p.exe;$l.Arguments='--dangerous-argument';$l.Save()"
    subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", script], input=json.dumps({"link": str(link), "exe": str(exe)}), encoding="utf-8", check=True, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    monkeypatch.setattr(discovery, "registry_candidates", lambda: [])
    monkeypatch.setattr(discovery, "installed_registry_candidates", lambda: [])
    monkeypatch.setattr(discovery, "packaged_candidates", lambda: [])
    monkeypatch.setattr(discovery, "location_candidates", lambda: [])
    original = discovery.menu_links
    monkeypatch.setattr(discovery, "menu_links", lambda roots: original([tmp_path]))
    rows = discovery.discover()["items"]
    assert len(rows) == 1 and rows[0]["name"] == "RPGReactor"
    assert rows[0]["target"] == str(exe) and rows[0]["source"] == "Ярлык меню «Пуск»"


def test_versions_duplicates_cache_and_stale_target(tmp_path, monkeypatch):
    first = tmp_path / "v1" / "RPGReactor.exe"; first.parent.mkdir(); first.touch()
    second = tmp_path / "v2" / "RPGReactor.exe"; second.parent.mkdir(); second.touch()
    rows = [item(first, "RPGReactor 1.0"), item(second, "RPGReactor 2.0")]
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": rows, "warnings": []})
    scanner = discovery.ApplicationScanner(tmp_path); scanner.scan()
    assert {x["target"] for x in scanner.find_matches("RPGReactor")} == {str(first), str(second)}
    assert [x["target"] for x in scanner.find_matches("RPGReactor 2.0")] == [str(second)]
    assert scanner.find("RPGReactor") is None
    first.unlink()
    assert [x["target"] for x in scanner.find_matches("RPGReactor")] == [str(second)]
    assert scanner.find_matches("Несуществующая программа") == []


def test_phonetic_candidates_are_suggestions_only(tmp_path, monkeypatch):
    first = tmp_path / "obs.exe"; first.touch()
    second = tmp_path / "RPGReactor.exe"; second.touch()
    code = tmp_path / "code.exe"; code.touch()
    firefox = tmp_path / "firefox.exe"; firefox.touch()
    aimp = tmp_path / "aimp.exe"; aimp.touch()
    rows = [item(first, "OBS Studio"), item(second, "RPGReactor"), item(code, "VS Code"), item(firefox, "Firefox"), item(aimp, "AIMP")]
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": rows, "warnings": []})
    scanner = discovery.ApplicationScanner(tmp_path); scanner.scan()
    assert scanner.find_matches("ОПС") == []
    assert scanner.suggest_matches("ОПС")[0]["target"] == str(first)
    assert scanner.suggest_matches("опыс")[0]["target"] == str(first)
    assert scanner.suggest_matches("APS")[0]["target"] == str(first)
    assert scanner.find_matches("рпг реактор") == []
    assert scanner.suggest_matches("рпг реактор")[0]["target"] == str(second)
    for spoken, target in [("ви эс код", code), ("файрфокс", firefox), ("аимп", aimp)]:
        assert scanner.suggest_matches(spoken)[0]["target"] == str(target)


def test_legacy_cache_with_safe_executable_remains_readable(tmp_path):
    exe = tmp_path / "OldApp.exe"; exe.touch()
    import json
    old = {"items": [item(exe, "OldApp")], "scanned_at": None, "warnings": []}
    (tmp_path / "applications.json").write_text(json.dumps(old), encoding="utf-8")
    assert discovery.ApplicationScanner(tmp_path).find("OldApp")["target"] == str(exe)


def test_legacy_shortcuts_are_batched_and_unc_is_not_read(tmp_path, monkeypatch):
    import json
    exe = tmp_path / "OldApp.exe"; exe.touch()
    first = tmp_path / "first.lnk"; first.touch()
    second = tmp_path / "second.lnk"; second.touch()
    rows = [item(first, "OldApp"), item(second, "OldApp 2"), item(Path(r"\\server\share\remote.lnk"), "Remote")]
    (tmp_path / "applications.json").write_text(json.dumps({"items": rows}), encoding="utf-8")
    calls = []
    def read_links(paths):
        calls.append(paths)
        return {str(path): str(exe) for path in paths}
    monkeypatch.setattr(discovery, "shortcut_targets", read_links)
    assert len(discovery.ApplicationScanner(tmp_path).valid_items()) == 2
    assert len(calls) == 1 and len(calls[0]) == 2


def test_packaged_id_must_be_registered_and_never_becomes_shell_text(tmp_path, monkeypatch):
    target = "aumid:Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    assert discovery.is_packaged_target(target)
    assert not discovery.is_packaged_target(target + ";cmd")
    monkeypatch.setattr(discovery, "packaged_candidates", lambda: [discovery.Candidate("", target, "Microsoft Store", "Калькулятор Store")])
    command = commands.Command("app", target, "Калькулятор Store")
    commands.validate(command)
    monkeypatch.setattr(discovery, "packaged_candidates", lambda: [])
    with pytest.raises(ValueError, match="регистрация"):
        commands.validate(command)


def test_uninstalled_packaged_app_is_not_reported_from_cache(tmp_path, monkeypatch):
    import json
    target = "aumid:Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    record = {"id": "store", "name": "Калькулятор Store", "target": target, "category": "other", "source": "Microsoft Store", "aliases": []}
    (tmp_path / "applications.json").write_text(json.dumps({"items": [record]}), encoding="utf-8")
    monkeypatch.setattr(discovery, "package_registered", lambda value: False)
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": [], "warnings": []})
    assert discovery.ApplicationScanner(tmp_path).find_matches("Калькулятор Store") == []


def test_packaged_launch_uses_activation_api_not_shell(monkeypatch):
    from core import launch_verification
    target = "aumid:Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"
    seen = []
    monkeypatch.setattr(discovery, "package_registered", lambda value: value == target)
    monkeypatch.setattr(launch_verification, "packaged_application", lambda value, label: seen.append((value, label)) or "Windows приняла активацию")
    monkeypatch.setattr(launch_verification, "shell_launch", lambda *args, **kwargs: pytest.fail("Store apps must not use shell commands"))
    assert "активацию" in commands.execute(commands.Command("app", target, "Калькулятор Store"))
    assert seen == [(target, "Калькулятор Store")]


@pytest.mark.parametrize("name", ["Uninstall", "Setup", "Windows PowerShell", "regedit", "cmd"])
def test_dangerous_programs_never_auto_match(tmp_path, name):
    assert not discovery.safe_application_name(name)


def test_chat_ambiguous_choice_rechecks_permission_and_custom_alias_wins(tmp_path, monkeypatch):
    first = tmp_path / "one" / "RPGReactor.exe"; first.parent.mkdir(); first.touch()
    second = tmp_path / "two" / "RPGReactor.exe"; second.parent.mkdir(); second.touch()
    rows = [item(first, "RPGReactor 1.0"), item(second, "RPGReactor 2.0", "Регистрация Windows")]
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": rows, "warnings": []})
    calls = []
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False: (None if dry_run else calls.append(command.target)) or "Проверенный запуск")
    app = create_app(tmp_path, "universal-app-tests-0123456789")
    app.state.applications.scan()
    with TestClient(app, headers={"Authorization": "Bearer universal-app-tests-0123456789"}) as api:
        assert api.post("/commands", json={"text": "Открой RPGReactor", "dry_run": True}).status_code == 409
        check = api.post("/chat", json={"text": "Проверь, установлен ли RPGReactor"}).text
        assert "Запуск не выполнялся" in check and not calls
        response = api.post("/chat", json={"text": "Открой RPGReactor", "mode": "conversation"}).text
        assert "номер" in response and "Регистрация Windows" in response and not calls
        api.post("/chat", json={"text": "второй", "mode": "conversation"})
        assert calls == [str(second)]
        api.post("/chat", json={"text": "Открой RPGReactor"})
        access = api.get("/tools").json()["access"]; access["allow_app_open"] = False
        api.put("/tools/access", json=access)
        api.post("/chat", json={"text": "первый"})
        assert calls == [str(second)]
        access["allow_app_open"] = True; api.put("/tools/access", json=access)
        api.post("/aliases", json={"name": "RPGReactor", "kind": "app", "target": str(first), "replace": False})
        assert api.post("/commands", json={"text": "Открой RPGReactor", "dry_run": True}).json()["target"] == str(first)
        api.post("/chat", json={"text": "Запусти RPGReactor"})
        assert calls == [str(second), str(first)]


def test_recent_request_never_claims_installation_date_or_launch(tmp_path, monkeypatch):
    exe = tmp_path / "RPGReactor.exe"; exe.touch()
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": [item(exe, "RPGReactor")], "warnings": []})
    monkeypatch.setattr(commands, "execute", lambda *args, **kwargs: pytest.fail("No app must be launched"))
    app = create_app(tmp_path, "recent-app-tests-0123456789ab")
    with TestClient(app, headers={"Authorization": "Bearer recent-app-tests-0123456789ab"}) as api:
        response = api.post("/chat", json={"text": "Запусти программу, установленную вчера"}).text
        assert "Дата установки" in response or "дата установки" in response
        assert "RPGReactor" in response and "ничего не запущено" in response
