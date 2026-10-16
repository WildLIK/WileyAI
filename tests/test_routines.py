from concurrent.futures import ThreadPoolExecutor
import json
import threading

from fastapi.testclient import TestClient
import pytest

from core import commands, providers
from core.api import create_app
from core.backups import Backups, encode
from core.chatspaces import Spaces
from core.routines import Routines, RoutineBody, requested_name
from core.storage import Store


TOKEN = "routine-tests-0123456789abcdef"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "get_key", lambda config: "")
    async def no_model(*args):
        raise AssertionError("A routine must not call a model")
        yield ""
    monkeypatch.setattr(providers, "chat", no_model)
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as client:
        yield client


def steps(count=3):
    return [{"kind": "url", "label": f"Сайт {index}", "target": f"https://example.com/{index}"} for index in range(count)]


def create(api, name="Работа", **kwargs):
    result = api.post("/routines", json={"name": name, "steps": steps()}, **kwargs)
    assert result.status_code == 200, result.text
    return result.json()


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("text,expected", [
    ("Запусти сценарий Работа", "работа"), ("Выполни сценарий Учёба, пожалуйста.", "учеба, пожалуйста"),
    ("Не запускай сценарий Работа", None), ("Запусти сценарий Работа?", None),
    ('Он сказал "запусти сценарий Работа"', None), ("Расскажи про сценарий Работа", None),
])
def test_exact_intent_not_questions_quotes_or_negations(text, expected):
    assert requested_name(text) == expected


def test_crud_normalized_names_and_project_boundaries(api, tmp_path):
    general = create(api)
    assert api.post("/routines", json={"name": "РАБОТА!", "steps": steps()}).status_code == 400
    project = api.post("/projects", json={"name": "Альтаир"}).json()
    chat = api.post("/conversations", json={"project_id": project["id"]}).json()
    scope = "?conversation_id=" + chat["id"]
    own = create(api, params={"conversation_id": chat["id"]})
    assert api.get("/routines" + scope).json()[0]["id"] == own["id"]
    assert api.put("/routines/" + general["id"] + scope, json={"name": "Чужое", "steps": steps()}).status_code == 400
    assert api.post("/routines/" + general["id"] + "/check" + scope).status_code == 404
    api.delete("/routines/" + general["id"] + scope)
    assert api.get("/routines").json()[0]["id"] == general["id"]
    assert api.put("/routines/" + own["id"] + scope, json={"name": "Учёба", "steps": list(reversed(steps()))}).status_code == 200
    scoped = Store(tmp_path).for_chat(chat["id"])
    assert Routines(scoped).list()[0]["steps"][0]["label"] == "Сайт 2"
    api.delete("/projects/" + project["id"])
    assert Routines(scoped).list() == [] and api.get("/routines").json()[0]["id"] == general["id"]
    api.delete("/routines/" + general["id"])
    assert api.get("/routines").json() == []


@pytest.mark.parametrize("body", [
    {"name": "Пустой", "steps": []}, {"name": "Длинный", "steps": steps(13)},
    {"name": "Чужой инструмент", "steps": [{"kind": "shell", "target": "echo hi", "label": "Команда"}]},
    {"name": 'Сценарий "Работа"', "steps": steps()},
    {"name": "!!!", "steps": steps()},
])
def test_invalid_definitions_are_rejected(api, body):
    assert api.post("/routines", json=body).status_code == 422


def test_check_runs_nothing_and_preflight_covers_every_step(api, tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False: launched.append(command.target) or "Передано Windows")
    item = create(api)
    assert api.post("/routines/" + item["id"] + "/check").status_code == 200
    assert launched == []

    path = tmp_path / "document.txt"
    path.write_text("text")
    body = {"name": "Работа", "steps": [steps()[0], {"kind": "file", "target": str(path), "label": "Документ"}]}
    assert api.put("/routines/" + item["id"], json=body).status_code == 200
    path.unlink()
    answer = events(api.post("/chat", json={"text": "Запусти сценарий Работа"}))[-1]["message"]["content"]
    assert "не запущен" in answer and "Шаг 2" in answer and launched == []


def test_order_fail_fast_audit_and_no_llm(api, tmp_path, monkeypatch):
    launched = []
    def execute(command, dry_run=False):
        launched.append(command.target)
        if len(launched) == 2:
            raise ValueError("Приложение недоступно")
        return "Передано браузеру: " + command.label
    monkeypatch.setattr(commands, "execute", execute)
    create(api)
    result = events(api.post("/chat", json={"text": "Запусти сценарий Работа"}))[-1]
    assert result["type"] == "done"
    assert launched == [step["target"] for step in steps()[:2]]
    assert "Приложение недоступно" in result["message"]["content"] and "Остальные" in result["message"]["content"]
    assert {item["status"] for item in api.get("/actions").json()} == {"launched", "error"}
    assert "Сценарий не найден" in events(api.post("/chat", json={"text": "Запусти сценарий Нет"}))[-1]["message"]["content"]


def test_successful_voice_mode_routine_and_exact_polite_title(api, tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False: launched.append(command.target) or "Передано браузеру: " + command.label)
    item = create(api, name="Работа пожалуйста")
    result = events(api.post("/chat", json={"text": "Запусти сценарий Работа пожалуйста", "mode": "conversation"}))[-1]
    assert result["type"] == "done" and len(launched) == 3
    assert launched == [step["target"] for step in steps()]
    assert "3. Передано браузеру: Сайт 2" in result["message"]["content"]
    assert Store(tmp_path).messages()[-1]["content"] == result["message"]["content"]
    api.put("/routines/" + item["id"], json={"name": "Работа", "steps": steps(1)})
    assert events(api.post("/chat", json={"text": "Выполни сценарий Работа, пожалуйста."}))[-1]["type"] == "done"
    assert len(launched) == 4


@pytest.mark.parametrize("kind,field", [("file", "allow_file_open"), ("folder", "allow_file_open"), ("app", "allow_app_open"), ("url", "allow_web_open")])
def test_access_is_enforced_for_direct_commands_and_routines(api, tmp_path, monkeypatch, kind, field):
    launched = []
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False: launched.append(command.target) or "Передано")
    path = tmp_path if kind == "folder" else tmp_path / ("app.exe" if kind == "app" else "note.txt")
    if kind not in {"folder", "url"}: path.write_text("test")
    target = "https://example.com" if kind == "url" else str(path)
    assert api.post("/aliases", json={"name": "моя цель", "kind": kind, "target": target}).status_code == 200
    assert api.post("/routines", json={"name": "Работа", "steps": [{"kind": kind, "target": target, "label": "Цель"}]}).status_code == 200
    access = api.get("/tools").json()["access"]
    access[field] = False
    assert api.put("/tools/access", json=access).status_code == 200
    assert api.post("/commands", json={"text": "Открой моя цель", "dry_run": False}).status_code == 400
    assert any("отключено" in item.get("text", "") for item in events(api.post("/chat", json={"text": "Открой моя цель"})))
    assert "не запущен" in events(api.post("/chat", json={"text": "Запусти сценарий Работа"}))[-1]["message"]["content"]
    assert launched == []
    if kind == "url":
        source = Store(tmp_path).add_message("assistant", "Источник", web_search={"query": "test", "provider": "searxng", "checked_at": "2026-10-16T10:00:00+00:00", "results": [{"title": "Источник", "url": "https://example.com", "snippet": "text"}], "partial": False})
        assert api.post("/web/open-source", json={"message_id": source["id"], "index": 0}).status_code == 400
        assert launched == []


def test_permission_change_is_checked_again_between_steps(api, tmp_path, monkeypatch):
    launched = []
    def execute(command, dry_run=False):
        launched.append(command.target)
        store = Store(tmp_path)
        store.save_settings(store.settings().model_copy(update={"allow_web_open": False}))
        return "Передано браузеру"
    monkeypatch.setattr(commands, "execute", execute)
    create(api)
    message = events(api.post("/chat", json={"text": "Запусти сценарий Работа"}))[-1]["message"]
    assert len(launched) == 1 and "отключено" in message["content"]


def test_cancellation_waits_for_dispatch_keeps_lock_and_saves_partial_result(api, monkeypatch):
    started, release = threading.Event(), threading.Event()
    launched = []
    def execute(command, dry_run=False):
        launched.append(command.target)
        started.set()
        assert release.wait(5)
        return "Передано браузеру: первый сайт"
    monkeypatch.setattr(commands, "execute", execute)
    item = create(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(api.post, "/chat", json={"text": "Запусти сценарий Работа", "request_id": "routine-turn"})
        try:
            assert started.wait(5)
            assert api.delete("/routines/" + item["id"]).status_code == 409
            assert api.put("/routines/" + item["id"], json={"name": "Другое", "steps": steps(1)}).status_code == 409
            stopped = pool.submit(api.post, "/chat/stop", json={"request_id": "routine-turn"})
            assert api.post("/chat", json={"text": "Запомни: второй запрос"}).status_code == 409
            assert not stopped.done()
        finally:
            release.set()
        assert stopped.result(timeout=5).status_code == 200
        future.result(timeout=5)
    assert len(launched) == 1
    assert "Сценарий остановлен" in api.get("/messages").json()[-1]["content"]
    assert events(api.post("/chat", json={"text": "Запомни: блокировка снята"}))[-1]["type"] == "done"


def test_backup_roundtrip_old_formats_no_execution_and_current_access_preserved(tmp_path, monkeypatch):
    source = Store(tmp_path / "source")
    project = Spaces(source).create_project("Проект")
    chat = Spaces(source).create_chat(project["id"])
    item = Routines(source.for_chat(chat["id"])).save(RoutineBody(name="Работа", steps=steps()))
    archive = Backups(source).export()
    monkeypatch.setattr(commands, "execute", lambda *args, **kwargs: pytest.fail("Import executed a command"))
    target = Store(tmp_path / "target")
    target.save_settings(target.settings().model_copy(update={"allow_web_open": False}))
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"], connections=True)
    assert Routines(target.for_chat(chat["id"])).get(item["id"])["steps"] == steps()
    assert target.settings().allow_web_open is False
    for version in (1, 2):
        old = json.loads(Backups(Store(tmp_path / f"old-{version}")).export())
        old["version"] = version
        del old["data"]["routines"]
        if version == 1:
            del old["data"]["projects"]
            del old["data"]["conversations"]
        manager.restore(manager.preview(encode(old))["ticket"])
        assert Routines(target.for_chat()).list() == []
    corrupt = json.loads(archive)
    corrupt["data"]["routines"][0]["steps"][0]["kind"] = "shell"
    with pytest.raises(ValueError): manager.preview(encode(corrupt))
