from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import threading
import asyncio

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core.backups import Backups, encode, parse
from core.config import Settings
from core.storage import Store


def content(root):
    store = Store(root)
    store.save_settings(Settings(name="Уайли из копии", personality="Кратко и тепло", provider="compatible", base_url="https://example.com/v1", model="other-model", audio_input_device_id="another-mic", avatar_path="D:/avatar.vrm"))
    user = store.add_message("user", "Я предпочитаю примеры на Python")
    proposal, = store.suggest_memories(user["id"])
    memory = store.accept_memory(proposal["id"], proposal["content"], None, pinned=True)
    store.add_message("assistant", "Хорошо", [memory])
    pending = store.add_message("user", "Мой проект называется Альтаир")
    store.suggest_memories(pending["id"])
    store.save_note("Идея", "Собрать ассистента")
    store.save_task("Проверить сборку", "reminder", (datetime.now(timezone.utc) + timedelta(days=3)).isoformat())
    store.save_task("Уже сработало", "timer", (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    notifications = store.queue_due_notifications()
    store.acknowledge_notification(notifications[0]["id"])
    store.add_document("план.txt", "Контрольный код СОКОЛ-73")
    store.add_alias("репозиторий", "url", "https://github.com/WildLIK/WileyAI")
    return store


def state(manager):
    value = json.loads(manager.export())
    return value["settings"], value["data"]


def test_complete_roundtrip_sources_versions_index_notifications_and_recovery(tmp_path):
    source = content(tmp_path / "source")
    source_manager = Backups(source)
    archive = source_manager.export()
    target = Store(tmp_path / "target")
    target.add_memory("Текущее воспоминание")
    target.save_dialogue({"pending": "черновик"})
    manager = Backups(target)
    old_state = state(manager)
    preview = manager.preview(archive)
    assert preview["counts"]["messages"] == 3 and preview["pending_suggestions"] == 1
    result = manager.restore(preview["ticket"], connections=True, aliases=True)
    assert state(manager) == state(source_manager)
    assert target.memory_context("Python")[0]["content"] == "Я предпочитаю примеры на Python"
    assert target.messages()[1]["memory_context"][0]["content"] == "Я предпочитаю примеры на Python"
    assert target.memories()[0]["source_text"] == "Я предпочитаю примеры на Python"
    assert target.dialogue() == {} and target.queue_due_notifications() == []
    recovery = parse(Path(result["recovery_path"]).read_bytes())
    assert (recovery.settings, recovery.data.model_dump()) == old_state
    assert Path(result["recovery_path"]).parent == target.root / "backups"
    assert state(Backups(Store(target.root))) == state(manager)
    with pytest.raises(ValueError, match="устарел"):
        manager.restore(preview["ticket"])


def test_default_restore_keeps_connections_devices_paths_and_commands(tmp_path):
    archive = Backups(content(tmp_path / "source")).export()
    target = Store(tmp_path / "target")
    target.save_settings(Settings(name="Текущее имя", model="my-local", audio_input_device_id="usb-mic", avatar_path="C:/my.vrm"))
    target.add_alias("заметку", "file", "C:/my-note.txt")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    config = target.settings()
    assert config.name == "Уайли из копии" and config.personality == "Кратко и тепло"
    assert config.provider == "ollama" and config.model == "my-local"
    assert config.audio_input_device_id == "usb-mic" and config.avatar_path == "C:/my.vrm"
    assert target.list("aliases")[0]["name"] == "заметку"


def test_migrated_legacy_memory_is_not_truncated_or_renamed(tmp_path):
    source_root = tmp_path / "legacy"
    source_root.mkdir()
    text = "Старое длинное воспоминание " * 120
    with sqlite3.connect(source_root / "wileyai.db") as db:
        db.execute("CREATE TABLE memories (id TEXT PRIMARY KEY,content TEXT NOT NULL,created TEXT NOT NULL)")
        db.execute("INSERT INTO memories VALUES (?,?,?)", ("legacy", text, "2026-10-01T10:00:00+00:00"))
    archive = Backups(Store(source_root)).export()
    target = Store(tmp_path / "target")
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.memories()[0]["id"] == "legacy"
    assert target.memories()[0]["content"] == text


@pytest.mark.parametrize("invalid", [b"not-json", b'{"version":1,"version":1}', b"[]", b'{"version": NaN}', b'{"version": true}', b'{"format":"other","version":2}'])
def test_broken_files_do_not_stage_or_change_data(tmp_path, invalid):
    manager = Backups(Store(tmp_path))
    before = state(manager)
    with pytest.raises(ValueError, match="Не удалось проверить"):
        manager.preview(invalid)
    assert manager.pending is None and state(manager) == before


@pytest.mark.parametrize("change", ["duplicate", "reference", "source", "hash", "settings", "table", "due"])
def test_import_checks_structures_relationships_and_configuration(tmp_path, change):
    manager = Backups(content(tmp_path))
    value = json.loads(manager.export())
    if change == "duplicate":
        value["data"]["messages"].append(value["data"]["messages"][0])
    elif change == "reference":
        value["data"]["message_memories"][0]["memory_id"] = "a" * 32
    elif change == "source":
        value["data"]["memories"][0]["source_message_id"] = value["data"]["messages"][1]["id"]
    elif change == "hash":
        value["data"]["memory_candidates"][1]["fingerprint"] = "a" * 64
    elif change == "settings":
        value["settings"]["api_key"] = "MUST-NOT-IMPORT-KEY"
    elif change == "table":
        value["data"]["execute_sql"] = "DROP TABLE memories"
    else:
        value["data"]["tasks"][0]["due"] = "2026-11-01T10:00:00"
    with pytest.raises(ValueError):
        manager.preview(encode(value))
    assert manager.pending is None


@pytest.mark.parametrize("change", ["message", "task", "draft"])
def test_stale_preview_cannot_erase_new_work(tmp_path, change):
    target = Store(tmp_path)
    manager = Backups(target)
    preview = manager.preview(manager.export())
    if change == "message":
        target.add_message("user", "Новое сообщение")
    elif change == "task":
        target.save_task("Новая задача", "todo", None)
    else:
        target.save_dialogue({"pending": "новый черновик"})
    before = state(manager)
    with pytest.raises(ValueError, match="данные изменились"):
        manager.restore(preview["ticket"])
    assert state(manager) == before
    assert not (target.root / "backups").exists()


def test_expiry_and_new_preview_revoke_old_ticket(tmp_path, monkeypatch):
    manager = Backups(Store(tmp_path))
    data = manager.export()
    first = manager.preview(data)
    second = manager.preview(data)
    with pytest.raises(ValueError, match="устарел"):
        manager.restore(first["ticket"])
    monkeypatch.setattr("core.backups.time.monotonic", lambda: manager.pending[1] + 1)
    with pytest.raises(ValueError, match="устарел"):
        manager.restore(second["ticket"])


def test_protective_copy_failure_preserves_database(tmp_path, monkeypatch):
    manager = Backups(content(tmp_path))
    before = state(manager)
    preview = manager.preview(manager.export())
    def fail(_fd):
        raise OSError("Disk full")
    monkeypatch.setattr("core.backups.os.fsync", fail)
    with pytest.raises(ValueError, match="Текущие данные не изменены"):
        manager.restore(preview["ticket"])
    assert state(manager) == before and list((tmp_path / "backups").iterdir()) == []


def test_sql_failure_rolls_back_whole_replacement_and_keeps_recovery(tmp_path):
    store = content(tmp_path)
    manager = Backups(store)
    before = state(manager)
    preview = manager.preview(manager.export())
    with store.db() as db:
        db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON memories BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        manager.restore(preview["ticket"])
    assert state(manager) == before
    recovery, = (tmp_path / "backups").glob("*.wileyai.json")
    saved = parse(recovery.read_bytes())
    assert (saved.settings, saved.data.model_dump()) == before


def test_concurrent_restore_consumes_preview_only_once(tmp_path):
    manager = Backups(Store(tmp_path))
    preview = manager.preview(manager.export())
    def restore(_):
        try:
            return manager.restore(preview["ticket"])
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(restore, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(list((tmp_path / "backups").glob("*.wileyai.json"))) == 1


def test_size_limit_never_returns_a_truncated_copy(tmp_path, monkeypatch):
    manager = Backups(Store(tmp_path))
    monkeypatch.setattr("core.backups.MAX_BYTES", 10)
    with pytest.raises(ValueError, match="лимит"):
        manager.export()
    with pytest.raises(ValueError, match="превышает"):
        manager.preview(b" " * 11)


def test_api_backup_does_not_read_or_write_keyring_or_execute_commands(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Backup must not access keys or execute commands")
    monkeypatch.setattr("core.providers.get_key", forbidden)
    monkeypatch.setattr("core.providers.set_key", forbidden)
    monkeypatch.setattr("core.commands.execute", forbidden)
    token = "backup-test-token-0123456789abcdef"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        assert api.get("/backups/export", headers={"Authorization": ""}).status_code == 401
        api.post("/chat", json={"text": "Запомни: данные для копии"})
        archive = api.get("/backups/export")
        assert archive.status_code == 200 and archive.headers["cache-control"] == "no-store"
        assert "api_key" not in archive.json()["settings"]
        assert "models" not in archive.json()["data"]
        preview = api.post("/backups/preview", files={"file": ("copy.json", archive.content)}).json()
        result = api.post("/backups/restore", json={"ticket": preview["ticket"], "aliases": True, "connections": True})
        assert result.status_code == 200, result.text
        assert api.get("/memories").json()[0]["content"] == "данные для копии"
        assert api.post("/backups/preview", files={"file": ("copy.json", b"broken")}).status_code == 400


def test_api_restore_refuses_while_model_is_generating(tmp_path, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    async def chat(*args):
        started.set()
        while not finish.is_set():
            await asyncio.sleep(0.01)
        yield "Ответ"
    monkeypatch.setattr("core.providers.chat", chat)
    token = "backup-test-token-0123456789abcdef"
    with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
        archive = api.get("/backups/export").content
        preview = api.post("/backups/preview", files={"file": ("copy.json", archive)}).json()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(api.post, "/chat", json={"text": "Привет"})
            try:
                assert started.wait(5)
                response = api.post("/backups/restore", json={"ticket": preview["ticket"]})
                assert response.status_code == 409
            finally:
                finish.set()
            assert '"type": "done"' in future.result(timeout=5).text
