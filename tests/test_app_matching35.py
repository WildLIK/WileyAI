"""Small app-discovery regressions; all installations and launches are fixtures."""
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import app_discovery as discovery, commands
from core.api import create_app
from core.app_catalog import canonical_name
from core.launch_verification import ExecutionText


@pytest.mark.parametrize("key,target_name,spec,name", [
    ("Telegram.exe", "64Gram.exe", "", "64Gram"),
    ("Telegram.exe", "blender.exe", "", "blender"),
    ("Telegram.exe", "Telegram.exe", "telegram", "Telegram"),
    ("notepad++.exe", "notepad++.exe", "notepad-plus-plus", "notepad++"),
    ("OddApp.exe", "OddApp.exe", "", "OddApp"),
])
def test_app_paths_uses_actual_target_without_requiring_standard_location(tmp_path, monkeypatch, key, target_name, spec, name):
    exe = tmp_path / "portable" / target_name; exe.parent.mkdir(); exe.touch()
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def enum_key(parent, index):
        if index: raise OSError()
        return key
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_64KEY=1, KEY_WOW64_32KEY=2, KEY_READ=4,
                           REG_SZ=1, REG_EXPAND_SZ=2, OpenKey=lambda *args: Key(), EnumKey=enum_key,
                           QueryValueEx=lambda *args: ('"' + str(exe) + '"', 1))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    found = discovery.registry_candidates()
    assert found and all((row.spec_id, row.name, row.path) == (spec, name, str(exe)) for row in found)
    monkeypatch.setattr(discovery, "registry_candidates", lambda: found)
    monkeypatch.setattr(discovery, "installed_registry_candidates", lambda: [])
    monkeypatch.setattr(discovery, "location_candidates", lambda: [])
    monkeypatch.setattr(discovery, "menu_links", lambda roots: ([], False))
    monkeypatch.setattr(discovery, "shortcut_targets", lambda paths: {})
    monkeypatch.setattr(discovery, "packaged_candidates", lambda: [])
    rows = discovery.discover()["items"]
    assert len(rows) == 1
    if not spec: assert rows[0]["name"] == name and rows[0]["aliases"] == []
    if target_name == "64Gram.exe":
        scanner = discovery.ApplicationScanner(tmp_path); scanner.scan()
        assert scanner.find_matches("64Gram")[0]["target"] == str(exe)
        assert scanner.find_matches("Telegram") == []


@pytest.fixture
def apps(tmp_path, monkeypatch):
    paths, rows = {}, []
    for name, filename in [("Paint", "mspaint.exe"), ("Notepad++", "notepad++.exe"), ("Блокнот", "notepad.exe"),
                           ("64Gram", "64Gram.exe"), ("Telegram", "Telegram.exe"), ("Blender", "blender.exe"),
                           ("Blender", "blender-launcher.exe"), ("Adobe Photoshop", "Photoshop.exe"), ("Steam", "steam.exe")]:
        path = tmp_path / filename; path.touch(); paths[filename] = str(path)
        rows.append({"id": filename, "name": name, "category": "other", "target": str(path), "source": "fixture", "aliases": []})
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": list(rows), "warnings": []})
    monkeypatch.setattr(discovery, "package_registered", lambda target: True)
    calls = []
    def execute(command, dry_run=False, **kwargs):
        if not dry_run: calls.append(command)
        return ExecutionText("Запуск проверен фикстурой", {"status": "process_started"})
    monkeypatch.setattr(commands, "execute", execute)
    async def forbidden(*args, **kwargs):
        pytest.fail("Exact app commands must not call an LLM")
        yield ""
    monkeypatch.setattr("core.providers.chat", forbidden)
    monkeypatch.setattr("core.providers.structured", forbidden)
    app = create_app(tmp_path, "app-matching35-token-0123456789")
    app.state.applications.scan()
    with TestClient(app, headers={"Authorization": "Bearer app-matching35-token-0123456789"}) as client:
        yield client, app, paths, rows, calls


@pytest.mark.parametrize("name", ["Notepad++", "notepad ++", "notepad plus plus", "нотепад++", "нотпад плюс плюс", "ноутпад плюс плюс"])
def test_notepad_variants_remain_separate_from_windows_notepad(apps, name):
    client, app, paths, rows, calls = apps
    result = client.post("/commands", json={"text": "Открой " + name, "dry_run": True})
    assert result.status_code == 200, result.text
    assert result.json()["kind"] == "app" and result.json()["target"] == paths["notepad++.exe"]
    assert canonical_name(name) == "Notepad++"
    assert app.state.applications.find_matches("Блокнот")[0]["target"] == paths["notepad.exe"]
    client.post("/chat", json={"text": "Открой " + name})
    assert [command.target for command in calls] == [paths["notepad++.exe"]]


def test_user_explicitly_maps_telegram_to_64gram_without_global_default(apps):
    client, app, paths, rows, calls = apps
    assert app.state.applications.find_matches("Telegram")[0]["target"] == paths["Telegram.exe"]
    assert app.state.applications.find_matches("64Gram")[0]["target"] == paths["64Gram.exe"]
    assert client.get("/aliases").json()["custom"] == []
    saved = client.post("/aliases", json={"name": "Telegram", "kind": "app", "target": paths["64Gram.exe"], "replace": False})
    assert saved.status_code == 200
    for name in ["Telegram", "телеграм"]:
        result = client.post("/commands", json={"text": "Открой " + name, "dry_run": True})
        assert result.json()["kind"] == "app" and result.json()["target"] == paths["64Gram.exe"]
    client.post("/chat", json={"text": "Открой Telegram"})
    assert [command.target for command in calls] == [paths["64Gram.exe"]]
    # Catalog/scanner identity is not globally rewritten by a personal alias.
    assert canonical_name("64Gram") is None
    assert app.state.applications.find_matches("Telegram")[0]["target"] == paths["Telegram.exe"]


@pytest.mark.parametrize("name,filename", [("Paint", "mspaint.exe"), ("Blender", "blender.exe"), ("Photoshop", "Photoshop.exe"), ("Steam", "steam.exe")])
def test_exact_apps_route_as_app_and_blender_remains_deduplicated(apps, name, filename):
    client, app, paths, rows, calls = apps
    result = client.post("/commands", json={"text": "Открой " + name, "dry_run": True})
    assert result.status_code == 200, result.text
    assert result.json()["kind"] == "app" and result.json()["target"] == paths[filename]
    client.post("/chat", json={"text": "Открой " + name})
    assert [(command.kind, command.target) for command in calls] == [("app", paths[filename])]
    assert len(app.state.applications.find_matches("Blender")) == 1


def test_paint_ambiguity_choice_and_permission_are_preserved(apps):
    client, app, paths, rows, calls = apps
    store_paint = {"id": "packaged-paint", "name": "Paint", "category": "other", "source": "Microsoft Store", "aliases": [],
                   "target": "aumid:Microsoft.Paint_8wekyb3d8bbwe!App"}
    rows.append(store_paint); app.state.applications.scan()
    assert len(app.state.applications.find_matches("Paint")) == 2
    assert client.post("/commands", json={"text": "Открой Paint", "dry_run": True}).status_code == 409
    assert "номер" in client.post("/chat", json={"text": "Открой Paint"}).text and not calls
    client.post("/chat", json={"text": "отмена"}); assert not calls
    client.post("/chat", json={"text": "Открой Paint"})
    app.state.store.patch_settings({"allow_app_open": False})
    client.post("/chat", json={"text": "второй"}); assert not calls


@pytest.mark.parametrize("name", ["Paint", "Notepad++", "64Gram"])
def test_negative_requests_do_not_launch(apps, name):
    client, app, paths, rows, calls = apps
    client.post("/chat", json={"text": "Не открывай " + name})
    assert not calls


def test_explicit_file_alias_named_paint_is_still_respected(apps, tmp_path):
    client, app, paths, rows, calls = apps
    document = tmp_path / "paint.txt"; document.touch()
    assert client.post("/aliases", json={"name": "Paint", "kind": "file", "target": str(document)}).status_code == 200
    result = client.post("/commands", json={"text": "Открой Paint", "dry_run": True})
    assert result.json()["kind"] == "file" and not calls
