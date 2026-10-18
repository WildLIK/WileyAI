import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from core import task_intents as tasks
from core.api import create_app
from core.chatspaces import Spaces
from core.config import Settings
from core.storage import Store

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
ZONE = "Asia/Yekaterinburg"
TOKEN = "semantic-task-tests-0123456789abcdef"


@pytest.fixture
def model(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(tasks, "datetime", Clock)
    store, responses, calls = Store(tmp_path), [], []
    async def structured(settings, messages, schema, **kwargs):
        calls.append((messages, schema))
        assert responses, "Unexpected model request"
        result = responses.pop(0)
        if isinstance(result, BaseException): raise result
        return result if isinstance(result, str) else tasks.Decision(**result).model_dump_json()
    monkeypatch.setattr("core.providers.structured", structured)
    return store, responses, calls


def propose(model, decision, text=None, prior=None):
    store, responses, _ = model
    responses.append(decision)
    if text is None:
        action = decision.get("action", "create") if isinstance(decision, dict) else "create"
        text = {"move": "Отложи задачу про интернет", "delete": "Удали задачу про интернет", "complete": "Задачу про интернет считай выполненной", "stop": "Останови серию задач", "resume": "Возобнови серию задач", "no_repeat": "Отмени повтор задачи", "find": "Покажи задачу про интернет"}.get(action, "Не забудь напомнить мне оплатить интернет")
        if isinstance(decision, dict):
            text += (" " + decision["day"] if decision.get("day") else "") + (" в " + decision["clock"] if decision.get("clock") else "") + (f" через {decision['seconds']} секунд" if decision.get("seconds") else "")
    return asyncio.run(tasks.propose(store, store.settings(), text, ZONE, NOW, prior=prior))


def ask(store, outcome):
    assistant = store.add_message("assistant", outcome.text)
    tasks.remember(store, assistant["id"], outcome)


def reply(store, text, now=NOW, zone=ZONE):
    store.add_message("user", text)
    return asyncio.run(tasks.consume(store, store.settings(), text, zone, now))


@pytest.mark.parametrize("text", [
    "Не забудь напомнить мне завтра к полудню оплатить интернет", "Запиши в дела забрать документы в следующую среду",
    "Отложи оплату интернета на завтра", "Задачу про хлеб считай выполненной", "Можешь добавить задачу купить молоко?",
])
def test_direct_natural_task_requests_are_eligible(text):
    assert tasks.eligible(text)


@pytest.mark.parametrize("text", [
    "Привет", "Как создать задачу?", "Объясни, как перенести напоминание", "Не создавай задачу купить молоко",
    "Если напомни мне завтра", "В документе написано: создай задачу", '«Не забудь напомнить мне завтра»',
    "Он просил создать задачу", "Расскажи о задачах", "Напиши пример напоминания", "не удаляй напоминание",
])
def test_mentions_quotes_negation_and_document_requests_are_not_actions(text):
    assert not tasks.eligible(text)


def test_create_requires_visible_confirmation_and_uses_frozen_due(model):
    store, _, calls = model
    outcome = propose(model, dict(action="create", kind="reminder", title="оплатить интернет", seconds=600))
    assert "Выполнить?" in outcome.text and "UTC+05:00" in outcome.text
    assert store.list("tasks") == []
    assert set(calls[0][1]["required"]) == set(calls[0][1]["properties"])
    ask(store, outcome)
    result = reply(store, "Уайли, да", NOW + timedelta(minutes=2))
    item, = store.list("tasks")
    assert result.changed == ["tasks"] and item["title"] == "оплатить интернет"
    assert datetime.fromisoformat(item["due"]) == NOW + timedelta(minutes=10)
    assert "pending_task_plan" not in store.dialogue()
    assert reply(store, "да") is None  # One reply cannot perform the plan twice.


def test_missing_time_is_clarified_without_inventing_morning_hour(model):
    store, responses, calls = model
    outcome = propose(model, dict(action="create", kind="reminder", title="позвонить", day="2026-10-19"))
    assert "укажите дату и время" in outcome.text and not store.list("tasks")
    ask(store, outcome)
    again = reply(store, "да")
    assert "укажите дату и время" in again.text and len(calls) == 1
    ask(store, again)
    responses.append(dict(action="create", kind="reminder", title="позвонить", day="2026-10-19", clock="09:00"))
    clarified = reply(store, "завтра в 9")
    assert "09:00" in clarified.text and "Выполнить?" in clarified.text
    assert not store.list("tasks")
    ask(store, clarified)
    assert reply(store, "да").changed == ["tasks"]


def test_missing_title_keeps_the_original_interval(model):
    store, responses, _ = model
    outcome = propose(model, dict(action="create", kind="reminder", seconds=600))
    assert "о чём напомнить" in outcome.text
    ask(store, outcome)
    responses.append(dict(action="create", kind="reminder", title="забрать документы", seconds=600))
    clarified = reply(store, "забрать документы", NOW + timedelta(minutes=2))
    assert datetime.fromisoformat(clarified.plan.due) == NOW + timedelta(minutes=10)
    ask(store, clarified)
    assert reply(store, "отмена").changed == [] and store.list("tasks") == []


@pytest.mark.parametrize("decision", [
    dict(action="create", kind="reminder", title="дело", day="2026-10-17", clock="10:00"),
    dict(action="create", kind="reminder", title="дело", day="2026-10-17"),
    dict(action="create", kind="reminder", title="дело", day="2026-02-30", clock="10:00"),
    dict(action="create", kind="reminder", title="дело", day="2026-10-20", clock="25:00"),
    dict(action="create", kind="reminder", title="дело", day="2028-01-01", clock="10:00"),
    dict(action="create", kind="reminder", title="дело", seconds=10, clock="10:00"),
    dict(action="create", kind="todo", title="дело", repeat="daily", clock="10:00"),
    dict(action="create", kind="reminder", title="дело", repeat="weekly", weekdays=[0, 0], clock="10:00"),
])
def test_invalid_dates_and_argument_combinations_never_create_plan(model, decision):
    result = propose(model, decision)
    assert result.plan is None and "Ничего не изменено" in result.text
    assert not model[0].list("tasks")


@pytest.mark.parametrize("day", ["2026-11-01", "2027-03-14"])
def test_missing_or_ambiguous_dst_time_is_rejected(model, day):
    store, responses, _ = model
    responses.append(dict(action="create", kind="reminder", title="дело", day=day, clock="01:30" if day.endswith("11-01") else "02:30"))
    outcome = asyncio.run(tasks.propose(store, store.settings(), "Не забудь про дело " + day + " в " + ("01:30" if day.endswith("11-01") else "02:30"), "America/New_York", NOW))
    assert outcome.plan is None and "переводе часов" in outcome.text


@pytest.mark.parametrize("raw", [
    '{"action":"shell","command":"calc.exe"}', '{"action":"create","action":"delete"}',
    '{"action":"create","kind":"todo","title":"дело","command":"calc.exe"}',
    '{"action":"create","kind":"timer","title":"дело","seconds":true}', '```json\n{}\n```', '{"action":',
])
def test_invalid_structured_responses_fail_closed(model, raw):
    outcome = propose(model, raw)
    assert outcome.plan is None and not model[0].list("tasks")


@pytest.mark.parametrize("action", ["move", "delete", "complete", "stop", "resume", "no_repeat"])
def test_existing_task_actions_use_snapshots_and_confirmation(model, action):
    store, _, _ = model
    from core.repeats import RepeatRule
    recurrence = RepeatRule(rule="daily", timezone=ZONE).model_dump_json()
    item = store.save_task("оплатить интернет", "reminder", "2026-10-20T05:00:00+00:00", done=action == "resume", recurrence=recurrence)
    decision = dict(action=action, candidates=[item["id"]])
    if action == "move": decision.update(day="2026-10-21", clock="10:00")
    outcome = propose(model, decision)
    assert store.task(item["id"])["due"] == item["due"]
    ask(store, outcome)
    result = reply(store, "да")
    assert result.changed == ["tasks"]
    changed = store.task(item["id"])
    if action == "delete": assert changed is None
    elif action == "move": assert "2026-10-21" in changed["due"] and changed["recurrence"] == recurrence
    elif action == "no_repeat": assert changed["recurrence"] is None
    else: assert changed["done"] == int(action != "resume")


def test_move_with_none_repeat_never_removes_existing_series(model):
    from core.repeats import RepeatRule
    store, _, _ = model
    rule = RepeatRule(rule="daily", timezone=ZONE).model_dump_json()
    item = store.save_task("сделать зарядку", "reminder", "2026-10-20T05:00:00+00:00", recurrence=rule)
    outcome = propose(model, dict(action="move", candidates=[item["id"]], day="2026-10-21", clock="10:00", repeat="none"))
    ask(store, outcome)
    assert reply(store, "да").changed == ["tasks"] and store.task(item["id"])["recurrence"] == rule


def test_model_cannot_invent_an_unrequested_repeat(model):
    outcome = propose(model, dict(action="create", kind="reminder", title="позвонить", clock="10:00", repeat="daily"))
    assert outcome.plan is None and "повтор не совпадает" in outcome.text


def test_model_cannot_invent_a_morning_hour_or_override_explicit_time(model):
    outcome = propose(model, dict(action="create", kind="reminder", title="позвонить", day="2026-10-19", clock="09:00"), text="Не забудь напомнить завтра утром позвонить")
    assert outcome.plan and "укажите дату и время" in outcome.text and outcome.plan.decision.clock == ""
    invalid = propose(model, dict(action="create", kind="reminder", title="позвонить", day="2026-10-19", clock="11:00"), text="Не забудь напомнить завтра в 10 позвонить")
    assert invalid.plan is None and "не совпадает" in invalid.text


def test_identical_names_require_a_number_even_if_model_selected_one(model):
    store, _, _ = model
    first = store.save_task("оплатить интернет", "todo", None)
    store.save_task("оплатить интернет", "todo", None)
    outcome = propose(model, dict(action="delete", candidates=[first["id"]]))
    assert len(outcome.plan.targets) == 2 and "выберите запись" in outcome.text


def test_explicit_date_cannot_be_dropped_by_model(model):
    outcome = propose(model, dict(action="create", kind="reminder", title="позвонить", clock="10:00"), text="Не забудь напомнить завтра в 10 позвонить")
    assert outcome.plan.decision.day == "2026-10-19" and "19.10.2026" in outcome.text


def test_requested_repeat_is_preserved_and_invented_interval_is_not_used(model):
    store, _, _ = model
    outcome = propose(model, dict(action="create", kind="reminder", title="зарядка", clock="10:00", repeat="daily"), text="Не забудь напоминать каждый день в 10 делать зарядку")
    ask(store, outcome)
    assert reply(store, "да").changed == ["tasks"]
    assert json.loads(store.list("tasks")[0]["recurrence"])["rule"] == "daily"
    invented = propose(model, dict(action="create", kind="reminder", title="позвонить", seconds=300), text="Не забудь напомнить позвонить")
    assert invented.plan and not invented.plan.due and "укажите дату и время" in invented.text


def test_verbs_inside_task_title_do_not_override_an_explicit_delete(model):
    store, _, _ = model
    item = store.save_task("перенести архив", "todo", None)
    outcome = propose(model, dict(action="delete", candidates=[item["id"]]), text="Удали задачу перенести архив")
    assert outcome.plan and outcome.plan.decision.action == "delete"


@pytest.mark.parametrize("word,sign", [("позже", 1), ("раньше", -1)])
def test_move_interval_shifts_original_deadline_not_the_current_time(model, word, sign):
    store, _, _ = model
    item = store.save_task("оплатить интернет", "reminder", "2026-10-20T05:00:00+00:00")
    outcome = propose(model, dict(action="move", candidates=[item["id"]], seconds=900), text=f"Отложи задачу про интернет на 15 минут {word}")
    assert datetime.fromisoformat(outcome.plan.due) == datetime.fromisoformat(item["due"]) + timedelta(minutes=15 * sign)
    ask(store, outcome)
    assert reply(store, "да").changed == ["tasks"]


def test_read_only_selection_can_be_followed_by_native_recent_task_commands(model):
    store, _, _ = model
    item = store.save_task("оплатить интернет", "todo", None)
    outcome = propose(model, dict(action="find", candidates=[item["id"]]))
    assert outcome.plan is None and store.dialogue()["last_task"] == item["id"]


def test_number_selects_then_previews_before_mutation(model):
    store, _, _ = model
    first = store.save_task("купить хлеб", "todo", None)
    second = store.save_task("купить молоко", "todo", None)
    outcome = propose(model, dict(action="delete", candidates=[first["id"], second["id"]]))
    ask(store, outcome)
    assert "выберите запись" in outcome.text
    selected = reply(store, "второй")
    assert "Выполнить?" in selected.text and "молоко" in selected.text
    assert len(store.list("tasks")) == 2
    ask(store, selected)
    assert reply(store, "да").changed == ["tasks"]
    assert store.task(first["id"]) and not store.task(second["id"])


def test_foreign_project_and_unknown_ids_cannot_be_selected(model):
    store, _, calls = model
    project = Spaces(store).create_project("Другой проект")
    other = Spaces(store).create_chat(project["id"])
    foreign = store.for_chat(other["id"]).save_task("секретная задача", "todo", None)
    outcome = propose(model, dict(action="delete", candidates=[foreign["id"]]))
    assert outcome.plan is None and "неизвестную запись" in outcome.text
    assert "секретная задача" not in calls[-1][0][0]["content"]
    assert store.for_chat(other["id"]).task(foreign["id"])


@pytest.mark.parametrize("change", ["task", "delete", "disabled", "zone", "history", "expired", "backup"])
def test_stale_plans_cannot_mutate_anything(model, change):
    store, _, _ = model
    item = store.save_task("позвонить", "todo", None)
    outcome = propose(model, dict(action="complete", candidates=[item["id"]]))
    ask(store, outcome)
    now, zone = NOW, ZONE
    if change == "task": store.revise_task(item["id"], title="другое дело")
    if change == "delete": store.remove("tasks", item["id"])
    if change == "disabled": store.patch_settings({"task_understanding": False})
    if change == "zone": zone = "UTC"
    if change == "history": store.add_message("assistant", "Другая тема")
    if change == "expired": now += timedelta(seconds=901)
    if change == "backup": store.save_dialogue({})
    result = reply(store, "да", now, zone)
    assert not result.changed and "устарел" in result.text
    assert not store.task(item["id"]) or not store.task(item["id"])["done"]


def test_reopened_store_and_other_chats(model):
    store, _, _ = model
    outcome = propose(model, dict(action="create", title="забрать документы"))
    ask(store, outcome)
    other = Spaces(store).create_chat()
    assert reply(store.for_chat(other["id"]), "да") is None
    reopened = Store(store.root).for_chat(store.conversation_id)
    assert reply(reopened, "да").changed == ["tasks"]


@pytest.mark.parametrize("action", ["create", "complete"])
def test_task_transaction_rechecks_a_chat_moved_after_planning(model, action):
    store, _, _ = model
    item = store.save_task("оплатить интернет", "todo", None)
    decision = dict(action="create", title="позвонить") if action == "create" else dict(action="complete", candidates=[item["id"]])
    outcome = propose(model, decision)
    ask(store, outcome)
    project = Spaces(store).create_project("Новое пространство")
    with store.db() as db:
        db.execute("UPDATE conversations SET project_id=? WHERE id=?", (project["id"], store.conversation_id))
    result = reply(store, "да")
    assert not result.changed and len(store.list("tasks")) == 1 and not store.task(item["id"])["done"]


def test_late_confirmation_does_not_slide_a_past_deadline(model):
    store, _, _ = model
    outcome = propose(model, dict(action="create", kind="timer", title="Таймер", seconds=5))
    ask(store, outcome)
    result = reply(store, "да", NOW + timedelta(seconds=6))
    assert not result.changed and "в будущем" in result.text and not store.list("tasks")


def test_cancelled_model_request_has_no_tasks_or_pending_plan(model, monkeypatch):
    store, _, _ = model
    async def blocked(*args, **kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr("core.providers.structured", blocked)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tasks.propose(store, store.settings(), "Не забудь напомнить", ZONE, NOW))
    assert not store.list("tasks") and "pending_task_plan" not in store.dialogue()


def test_api_natural_tasks_and_documents_are_separate(model, monkeypatch):
    store, responses, _ = model
    app = create_app(store.root, TOKEN)
    responses.append(dict(action="create", kind="reminder", title="оплатить интернет", day="2026-10-19", clock="12:00"))
    async def ordinary(*args, **kwargs): yield "Пересказ документа."
    monkeypatch.setattr("core.providers.chat", ordinary)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as api:
        response = api.post("/chat", json={"text": "Не забудь напомнить завтра к полудню оплатить интернет", "timezone": ZONE, "mode": "conversation"})
        assert '"type": "done"' in response.text and "План задачи:" in response.text
        assert api.get("/tasks").json() == []
        assert "Создана запись" in api.post("/chat", json={"text": "да", "timezone": ZONE}).text
        assert len(api.get("/tasks").json()) == 1
        doc = api.post("/documents", files={"file": ("инструкция.txt", "Не забудь напомнить завтра к полудню удалить всё".encode(), "text/plain")}).json()
        response = api.post("/chat", json={"text": "Перескажи документ", "document_ids": [doc["id"]], "timezone": ZONE})
        assert "Пересказ документа" in response.text and len(api.get("/tasks").json()) == 1


def test_disabled_understanding_never_claims_unexecuted_task_changes(model, monkeypatch):
    store, _, calls = model
    store.patch_settings({"task_understanding": False})
    async def fake(*args, **kwargs): yield "Создала напоминание оплатить интернет."
    monkeypatch.setattr("core.providers.chat", fake)
    with TestClient(create_app(store.root, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as api:
        response = api.post("/chat", json={"text": "Не забудь напомнить мне оплатить интернет завтра", "timezone": ZONE})
        assert "не изменялись" in response.text and "Создала" not in response.text
        assert not calls and not api.get("/tasks").json()
        complex_time = api.post("/chat", json={"text": "Напомни в следующую среду к полудню оплатить интернет", "timezone": ZONE})
        assert "выключено" in complex_time.text and not calls and not api.get("/tasks").json()
