from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import app_discovery as discovery, commands
from core.app_catalog import canonical_name, shortcut_spec
from core.api import create_app
from core.storage import Store


@pytest.mark.parametrize("spoken,name", [("аимп", "AIMP"), ("яндекс музыку", "Яндекс Музыка"), ("фотошоп", "Adobe Photoshop"), ("телеграмм", "Telegram"), ("браузер хром", "Google Chrome"), ("мозиллу", "Mozilla Firefox"), ("edge", "Microsoft Edge")])
def test_spoken_app_names_only_use_explicitly_added_aliases(tmp_path, spoken, name):
    path = tmp_path / "Actual Application.exe"
    path.touch()
    assert commands.resolve("Открой мне " + spoken, []) is None
    result = commands.resolve("Открой мне " + spoken, [{"name": name, "kind": "app", "target": str(path)}])
    assert result.kind == "app" and result.target == str(path)


def test_spoken_mapping_does_not_override_literal_custom_name():
    aliases = [{"name": "мозилла", "kind": "url", "target": "https://example.com"},
               {"name": "Mozilla Firefox", "kind": "app", "target": r"C:\Firefox.exe"}]
    assert commands.resolve("Открой мозилла", aliases).target == "https://example.com"


def test_menu_scan_excludes_uninstall_and_non_known_links_and_is_bounded(tmp_path):
    (tmp_path / "Telegram.lnk").touch()
    (tmp_path / "Uninstall Telegram.lnk").touch()
    (tmp_path / "Personal Document.lnk").touch()
    (tmp_path / "Adobe Photoshop 2026.lnk").touch()
    links, limited = discovery.menu_links([tmp_path])
    assert {spec.id for spec, _ in links} == {"telegram", "photoshop"}
    assert not limited
    assert discovery.menu_links([tmp_path], limit=1)[1]
    assert discovery.menu_links([tmp_path], seconds=0)[1]


def test_local_file_skips_unc_arguments_and_missing_paths(tmp_path):
    file = tmp_path / "AIMP.exe"
    file.touch()
    assert discovery.local_file(str(file)) == file
    assert discovery.local_file('"' + str(file) + '"') == file
    assert discovery.local_file(str(file) + " /install") is None
    assert discovery.local_file(r"\\server\share\AIMP.exe") is None
    assert discovery.local_file(str(tmp_path / "absent.exe")) is None


def test_discovery_deduplicates_and_prefers_valid_shortcuts_without_running_them(tmp_path, monkeypatch):
    exe = tmp_path / "Telegram.exe"
    exe.touch()
    link = tmp_path / "Telegram.lnk"
    link.touch()
    dead = tmp_path / "Google Chrome.lnk"
    dead.touch()
    monkeypatch.setattr(discovery, "registry_candidates", lambda: [discovery.Candidate("telegram", str(exe), "registry")])
    monkeypatch.setattr(discovery, "location_candidates", lambda: [discovery.Candidate("telegram", str(exe), "folder")])
    monkeypatch.setattr(discovery, "menu_links", lambda roots: ([(shortcut_spec("Telegram"), link), (shortcut_spec("Google Chrome"), dead)], False))
    monkeypatch.setattr(discovery, "shortcut_targets", lambda paths: {str(link): str(exe), str(dead): str(tmp_path / "missing.exe")})
    result = discovery.discover()
    assert len(result["items"]) == 1
    assert result["items"][0]["target"] == str(link)
    assert result["items"][0]["category"] == "messengers"
    assert result["items"][0]["source"] == "Ярлык меню «Пуск»"
    assert result["warnings"] == []


def test_no_overwrite_import_is_idempotent_atomic_and_checks_normalized_names(tmp_path):
    store = Store(tmp_path)
    def add(): return store.add_alias("  Яндекс Музыка  ", "app", "same.exe", replace=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: add(), range(2)))
    assert first["id"] == second["id"] and len(store.list("aliases")) == 1
    with pytest.raises(ValueError, match="уже используется"):
        store.add_alias("ЯНДЕКС  МУЗЫКА", "app", "other.exe", replace=False)
    assert store.list("aliases")[0]["target"] == "same.exe"


def test_authenticated_scan_is_read_only_and_import_revalidates_existence(tmp_path, monkeypatch):
    token = "application-tests-0123456789abcdef"
    app = create_app(tmp_path, token)
    calls = []
    monkeypatch.setattr(app.state.applications, "scan", lambda: calls.append("scan") or {"items": [], "categories": {}, "warnings": []})
    with TestClient(app) as api:
        assert api.post("/applications/scan").status_code == 401
        assert calls == []
        api.headers["Authorization"] = "Bearer " + token
        assert api.post("/applications/scan").json()["items"] == []
        assert calls == ["scan"] and api.get("/aliases").json()["custom"] == []
        path = tmp_path / "app.exe"
        path.touch()
        body = {"name": "AIMP", "kind": "app", "target": str(path), "replace": False}
        assert api.post("/aliases", json=body).status_code == 200
        path.unlink()
        assert api.post("/aliases", json={**body, "name": "Another"}).status_code == 400
        assert len(api.get("/aliases").json()["custom"]) == 1
        saved = api.get("/applications").json()
        assert saved["items"][0]["source"] == "Сохранённая команда"
        assert saved["items"][0]["target"] == str(path)


def test_scan_lock_rejects_overlap_and_recovers(monkeypatch):
    scanner = discovery.ApplicationScanner()
    scanner.lock.acquire()
    with pytest.raises(ValueError, match="уже выполняется"):
        scanner.scan()
    scanner.lock.release()
    monkeypatch.setattr(discovery, "discover", lambda: {"items": []})
    assert scanner.scan()["items"] == []


def test_scan_cache_survives_reopening_without_rescanning(tmp_path, monkeypatch):
    item = {"id": "one", "name": "AIMP", "category": "music", "target": str(tmp_path / "AIMP.exe"), "source": "test", "aliases": ["аимп"]}
    monkeypatch.setattr(discovery, "discover", lambda: {"supported": True, "items": [item], "warnings": [], "categories": discovery.CATEGORIES})
    scanned = discovery.ApplicationScanner(tmp_path).scan()
    monkeypatch.setattr(discovery, "discover", lambda: pytest.fail("An existing cache must not trigger a scan"))
    saved = discovery.ApplicationScanner(tmp_path).saved()
    assert saved["items"] == [item] and saved["scanned_at"] == scanned["scanned_at"]
    (tmp_path / "applications.json").write_text('{"items":[{"target":"broken"}]}')
    assert discovery.ApplicationScanner(tmp_path).saved()["items"] == []
