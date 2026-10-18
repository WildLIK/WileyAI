import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from core import commands, intents, providers
from core.api import create_app
from core.backups import Backups
from core.chatspaces import Spaces
from core.storage import Store

TOKEN = "intent-tests-0123456789abcdef"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def context(tmp_path, monkeypatch):
    store = Store(tmp_path)
    first, second = tmp_path / "private-first.exe", tmp_path / "private-second.exe"
    first.write_text("test"); second.write_text("test")
    store.add_alias("редактор заметок", "app", str(first))
    store.add_alias("редактор кода", "app", str(second))
    opened, captured = [], []
    monkeypatch.setattr(commands, "execute", lambda command, dry_run=False: opened.append(command) or "Передал Windows: " + command.label)
    monkeypatch.setattr(providers, "get_key", lambda config: "")
    async def chat(config, messages):
        captured.append(messages)
        if "Каталог:\n" not in messages[0]["content"]:
            yield "Обычный ответ без действий"
            return
        catalog = json.loads(messages[0]["content"].split("Каталог:\n")[1])
        chosen = next(item for item in catalog if item["name"] == "редактор заметок")
        yield json.dumps({"candidates": [chosen["id"]]})
    monkeypatch.setattr(providers, "chat", chat)
    with TestClient(create_app(tmp_path, TOKEN), headers=HEADERS) as api:
        yield api, store, opened, captured


def enable(api, value=True):
    access = api.get("/tools").json()["access"]
    assert api.put("/tools/access", json={**access, "command_understanding": value}).status_code == 200


def send(api, text, **extra):
    response = api.post("/chat", json={"text": text, **extra})
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert not any(item["type"] == "error" for item in events), events
    return next(item["message"] for item in events if item["type"] == "done")


@pytest.mark.parametrize("text,expected", [
    ("Открой программу для заметок", True), ("Уайли, запусти мой редактор", True),
    ("Можешь открыть редактор?", True), ("Пожалуйста, открой программу для заметок", True),
    ("Как открыть программу для заметок?", False), ("Не открывай редактор", False),
    ('Он сказал: "открой редактор"', False), ("Открой редактор, но не запускай его", False),
    ("Если я скажу открой редактор", False), ("Привет, поговорим", False),
])
def test_bounded_opening_request(text, expected):
    assert bool(intents.opening_request(text)) is expected


def test_opt_in_exact_commands_and_addressing_remain_fast(context):
    api, store, opened, captured = context
    send(api, "Открой программу для заметок")
    assert captured == [] and opened == []
    send(api, "Уайли, открой редактор заметок")
    assert len(opened) == 1 and captured == []
    enable(api)
    send(api, "Открой редактор кода")
    assert len(opened) == 2 and captured == []


def test_screenshot_requests_execute_or_clarify_without_model_claims(context):
    api, store, opened, captured = context
    for phrase, url in [("Открой мне сайт YouTube.", "https://www.youtube.com"),
                        ("Открой мне сайт GitHub.", "https://github.com"),
                        ("Открой кит-хаб.", "https://github.com")]:
        answer = send(api, phrase, mode="conversation")
        assert opened[-1].target == url
        assert "Передала Windows" in answer["content"]
    enable(api)
    answer = send(api, "Открой, открой, открой, открой.")
    assert "Что открыть?" in answer["content"] and "ничего не открыто" in answer["content"]
    assert captured == [] and len(opened) == 3


def test_natural_site_command_still_checks_access(context):
    api, store, opened, captured = context
    store.save_settings(store.settings().model_copy(update={"allow_web_open": False}))
    answer = send(api, "Открой мне сайт GitHub.")
    assert "отключено" in answer["content"]
    assert opened == [] and captured == []


def test_known_music_app_runs_with_one_choice_and_asks_with_multiple(context):
    api, store, opened, captured = context
    aimp = store.root / "AIMP.exe"
    yandex = store.root / "YandexMusic.exe"
    aimp.touch(); yandex.touch()
    store.add_alias("AIMP", "app", str(aimp))
    answer = send(api, "Включи мне музыку.")
    assert opened[-1].target == str(aimp)
    assert "не проверялось" in answer["content"]
    store.add_alias("Яндекс Музыка", "app", str(yandex))
    question = send(api, "Включи музыку")
    assert "Выберите музыкальное приложение" in question["content"]
    assert len(opened) == 1 and captured == []
    assert store.settings().command_understanding is False
    assert store.dialogue()["pending_open"]["model_assisted"] is False
    send(api, "да")  # More than one local source still needs a choice.
    assert store.dialogue()["pending_open"]["model_assisted"] is False
    send(api, "второй")
    assert len(opened) == 2 and captured == []
    assert opened[-1].target in {str(aimp), str(yandex)}


def test_music_choice_rechecks_permissions_before_launch(context):
    api, store, opened, captured = context
    for name in ("AIMP", "Spotify"):
        target = store.root / (name + ".exe")
        target.touch()
        store.add_alias(name, "app", str(target))
    send(api, "Включи мне музыку")
    store.save_settings(store.settings().model_copy(update={"allow_app_open": False}))
    answer = send(api, "первый")
    assert "доступ изменились" in answer["content"] and opened == []


def test_model_only_proposes_id_then_voice_yes_executes_once(context):
    api, store, opened, captured = context
    enable(api)
    store.add_memory("ПРИВАТНАЯ-ПАМЯТЬ")
    store.add_document("private.txt", "ПРИВАТНЫЙ-ДОКУМЕНТ")
    store.add_message("user", "ПРИВАТНАЯ-ИСТОРИЯ")
    question = send(api, "Открой программу для заметок", mode="conversation")
    assert "редактор заметок" in question["content"] and "Ответьте «да»" in question["content"]
    assert "private-first.exe" not in question["content"] and opened == []
    payload = str(captured[-1])
    assert all(secret not in payload for secret in ["ПРИВАТНАЯ-ПАМЯТЬ", "ПРИВАТНЫЙ-ДОКУМЕНТ", "ПРИВАТНАЯ-ИСТОРИЯ", str(store.root), "private-first.exe"])
    assert "Передала Windows" in send(api, "да", mode="conversation")["content"]
    assert len(opened) == 1 and opened[0].label == "редактор заметок" and len(captured) == 1
    send(api, "да")
    assert len(opened) == 1


@pytest.mark.parametrize("reply", ["Да, открывай", "Уайли, да, пожалуйста", "открой первый вариант"])
def test_natural_voice_confirmation_forms(context, reply):
    api, store, opened, captured = context
    enable(api)
    send(api, "Открой программу для заметок", mode="conversation")
    send(api, reply, mode="conversation")
    assert len(opened) == 1 and len(captured) == 1


@pytest.mark.parametrize("response", ["отмена", "нет", "не надо", "передумал", "Привет"])
def test_cancellation_or_unrelated_message_retires_proposal(context, response):
    api, store, opened, captured = context
    enable(api)
    send(api, "Открой программу для заметок")
    send(api, response)
    assert "pending_open" not in store.dialogue()
    send(api, "да")
    assert opened == []


def test_multiple_candidates_require_number_and_not_yes(context, monkeypatch):
    api, store, opened, captured = context
    async def chat(config, messages):
        data = json.loads(messages[0]["content"].split("Каталог:\n")[1])
        yield '```json\n' + json.dumps({"candidates": [next(item["id"] for item in data if item["name"] == name) for name in ("редактор заметок", "редактор кода")]}) + '\n```'
    monkeypatch.setattr(providers, "chat", chat)
    enable(api)
    send(api, "Открой мой редактор")
    assert "номером" in send(api, "да")["content"] and opened == []
    assert "номером" in send(api, "9")["content"] and opened == []
    send(api, "второй", mode="conversation")
    assert len(opened) == 1 and opened[0].label == "редактор кода"


def test_opening_request_does_not_become_title_of_pending_reminder(context):
    api, store, opened, captured = context
    enable(api)
    send(api, "Напомни завтра в 11", timezone="Asia/Yekaterinburg")
    assert store.dialogue().get("pending") is not None
    question = send(api, "Можешь открыть программу для заметок")
    assert "Пока ничего не открыто" in question["content"] and store.list("tasks") == []
    assert "pending" not in store.dialogue() and opened == []


@pytest.mark.parametrize("output", [
    'Открываю редактор', '{"candidates":["made-up-id"]}', '{"candidates":[],"command":"notepad.exe"}',
    '{"candidates":[],"candidates":[]}', '[]', '{"candidates":[1]}', 'x' * 2001, "duplicate",
])
def test_bad_model_output_cannot_create_pending_or_execute(context, monkeypatch, output):
    api, store, opened, captured = context
    closed = []
    async def chat(config, messages):
        try:
            if output == "duplicate":
                data = json.loads(messages[0]["content"].split("Каталог:\n")[1])
                yield json.dumps({"candidates": [data[0]["id"], data[0]["id"]]})
            else: yield output
        finally: closed.append(True)
    monkeypatch.setattr(providers, "chat", chat)
    enable(api)
    answer = send(api, "Открой программу для заметок")
    assert "Не удалось подобрать" in answer["content"] and opened == []
    assert "pending_open" not in store.dialogue()
    assert closed == [True]


@pytest.mark.parametrize("change", ["alias", "access", "disabled", "expired", "missing", "corrupt", "source"])
def test_stale_or_disabled_proposals_never_open(context, change):
    api, store, opened, captured = context
    enable(api)
    send(api, "Открой программу для заметок")
    if change == "alias":
        store.add_alias("редактор заметок", "app", str(store.root / "other.exe"))
    elif change == "access":
        store.save_settings(store.settings().model_copy(update={"allow_app_open": False}))
    elif change == "disabled": enable(api, False)
    elif change == "missing": (store.root / "private-first.exe").unlink()
    elif change == "source": store.add_message("assistant", "Другой вопрос")
    else:
        state = store.dialogue()
        if change == "expired": state["pending_open"]["created"] = time.time() - intents.TTL - 1
        else: state["pending_open"] = {"bad": True}
        store.save_dialogue(state)
    send(api, "да")
    assert opened == [] and "pending_open" not in store.dialogue()


def test_proposal_is_per_chat_cleared_on_move_and_restore(context):
    api, store, opened, captured = context
    enable(api)
    send(api, "Открой программу для заметок")
    second = Spaces(store).create_chat()
    send(api, "да", conversation_id=second["id"])
    assert opened == []
    send(api, "да")
    assert len(opened) == 1
    send(api, "Открой программу для заметок")
    project = Spaces(store).create_project("Проект")
    Spaces(store).update_chat(store.conversation_id, "Перенесённый", project["id"])
    send(api, "да")
    assert len(opened) == 1
    send(api, "Открой программу для заметок")
    manager = Backups(store)
    manager.restore(manager.preview(manager.export())["ticket"], connections=True)
    send(api, "да")
    assert len(opened) == 1 and store.settings().command_understanding is True
    archive = manager.export()
    enable(api, False)
    manager.restore(manager.preview(archive)["ticket"], connections=True)
    assert store.settings().command_understanding is False


def test_large_catalog_is_bounded_and_relevant_names_are_not_cut_off(context):
    api, store, opened, captured = context
    for index in range(50):
        store.add_alias(f"aaa справочник {index}", "url", f"https://example.com/{index}")
    store.add_alias("zzz личные заметки", "url", "https://example.com/notes")
    enable(api)
    send(api, "Открой личные заметки")
    values = json.loads(captured[-1][0]["content"].split("Каталог:\n")[1])
    assert len(values) <= 40 and values[0]["name"] == "zzz личные заметки"
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in values) <= 5000
    assert opened == []


def test_pending_choice_survives_runtime_restart(context):
    api, store, opened, captured = context
    enable(api)
    send(api, "Открой программу для заметок")
    with TestClient(create_app(store.root, TOKEN), headers=HEADERS) as restarted:
        send(restarted, "да")
    assert len(opened) == 1


def test_messages_and_pending_choice_keep_order_when_windows_clock_ticks_match(context, monkeypatch):
    api, store, opened, captured = context
    monkeypatch.setattr("core.storage.now", lambda: "2026-10-16T10:00:00+00:00")
    enable(api)
    send(api, "Открой программу для заметок")
    send(api, "да")
    assert len(opened) == 1
    assert [item["role"] for item in store.messages()] == ["user", "assistant", "user", "assistant"]
    assert [item["role"] for item in store.list("messages", 2)] == ["user", "assistant"]


def test_stopping_classification_has_no_late_pending_or_action(context, monkeypatch):
    api, store, opened, captured = context
    started, stopped = threading.Event(), threading.Event()
    async def chat(*args):
        started.set()
        try:
            await asyncio.sleep(30)
            yield '{"candidates":[]}'
        finally: stopped.set()
    monkeypatch.setattr(providers, "chat", chat)
    enable(api)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api.post, "/chat", json={"text": "Открой программу для заметок", "request_id": "intent-turn"})
        assert started.wait(5)
        assert api.post("/chat/stop", json={"request_id": "intent-turn"}).status_code == 200
        future.result(timeout=5)
    assert stopped.is_set() and opened == [] and "pending_open" not in store.dialogue()
    assert send(api, "Запомни: отмена разбора работает")["content"]
