import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import threading

from fastapi.testclient import TestClient
import pytest

from core import action_plans as plans, task_intents
from core.api import create_app
from core.backups import Backups
from core.calendar import Calendar, EventBody
from core.chatspaces import Spaces
from core.storage import Store

NOW = datetime(2026, 10, 20, 13, tzinfo=timezone.utc)
ZONE = "Asia/Yekaterinburg"
TASK = "напомни завтра в 10 оплатить интернет"
NOTE = "запиши заметку Документы: забрать паспорт"
EVENT = "запланируй встречу Обзор завтра к полудню на 30 минут"
TEXT = TASK + "; " + NOTE + "; " + EVENT


@pytest.fixture
def model(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(plans, "datetime", Clock)
    monkeypatch.setattr(task_intents, "datetime", Clock)
    replies, calls = [], []
    async def structured(settings, messages, schema, **kwargs):
        calls.append((messages, schema))
        assert replies, "Unexpected model request"
        result = replies.pop(0)
        if isinstance(result, BaseException): raise result
        return json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    monkeypatch.setattr("core.providers.structured", structured)
    return Store(tmp_path), replies, calls


def decision():
    return {"steps": [
        dict(domain="task", action="create", source=TASK, title="оплатить интернет", kind="reminder", day="2026-10-21", clock="10:00", repeat="none"),
        dict(domain="note", action="create", source=NOTE, title="Документы", content="забрать паспорт"),
        dict(domain="event", action="create", source=EVENT, title="Обзор", day="2026-10-21", clock="12:00", duration_minutes=30),
    ]}


def propose(model, value=None, text=TEXT, store=None):
    initial, responses, _ = model
    store = store or initial
    responses.append(decision() if value is None else value)
    return asyncio.run(plans.propose(store, store.settings(), text, ZONE, NOW))


def ask(store, outcome):
    assert outcome.plan, outcome.text
    assistant = store.add_message("assistant", outcome.text)
    plans.remember(store, assistant["id"], outcome)


def reply(store, text="выполни план", *, zone=ZONE, now=NOW, allow=True):
    store.add_message("user", text)
    return plans.consume(store, store.settings(), text, zone, now, allow=allow)


def event(store, title="Обзор", **changes):
    body = EventBody(title=title, starts_at="2026-10-22T10:00:00+05:00", ends_at="2026-10-22T11:00:00+05:00", timezone=ZONE, **changes)
    return Calendar(store).save(body)


def test_mixed_plan_preview_atomic_commit_frozen_time_and_once(model):
    store, _, calls = model
    outcome = propose(model)
    assert outcome.plan and "Выполнить весь план" in outcome.text
    assert "12:00" in outcome.text and "забрать паспорт" in outcome.text
    assert not store.list("tasks") and not store.list("notes")
    assert len(calls) == 1 and "Документы" not in calls[0][0][0]["content"]
    ask(store, outcome)
    restarted = Store(store.root)
    result = reply(restarted, now=NOW + timedelta(minutes=2))
    assert result.changed == ["calendar_events", "notes", "tasks"]
    assert "План выполнен" in result.text
    assert store.list("tasks")[0]["due"] == "2026-10-21T05:00:00+00:00"
    assert store.list("notes")[0]["content"] == "забрать паспорт"
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 1
        saved = db.execute("SELECT * FROM calendar_events").fetchone()
        assert saved["title"] == "Обзор" and saved["starts_at"] == "2026-10-21T07:00:00.000000+00:00"
        assert db.execute("SELECT COUNT(*) FROM actions WHERE kind='plan'").fetchone()[0] == 1
    assert not store.dialogue().get("pending_action_plan")
    assert reply(store) is None
    assert len(store.list("tasks")) == 1


@pytest.mark.parametrize("text", [
    "Как создать задачу и записать заметку?", "Расскажи, как создать задачу и добавить встречу",
    "Если создай задачу и удали заметку", '«создай задачу и удали заметку»',
    "В документе создай задачу и удали заметку", "Не создавай задачу и удали заметку", "Привет",
    "Создай заметку Инструкция: «удали задачу и отправь письмо»",
    "Открой, открой, открой, открой.",
])
def test_mentions_quotes_and_negations_do_not_reach_planner(text): assert not plans.eligible(text)


@pytest.mark.parametrize("text", [TEXT, "Уайли, создай задачу хлеб и запиши заметку Молоко", "Спланируй: напомни завтра оплатить интернет", "Дополни заметку Покупки: хлеб", "Перенеси встречу Обзор на следующую среду к полудню"])
def test_explicit_multi_requests_and_natural_edits_are_eligible(text): assert plans.eligible(text)


@pytest.mark.parametrize("value", ['{"steps":', '{"steps":[],"command":"calc.exe"}', '{"steps":[],"steps":[]}', '```json\n{}\n```', {"steps": [dict(domain="shell", action="create", source=TASK)]}, RuntimeError("fixture offline")])
def test_invalid_or_unavailable_model_never_mutates(model, value):
    result = propose(model, value)
    assert not result.plan and not model[0].list("tasks")


@pytest.mark.parametrize("change", ["extra", "partial", "wrong_source", "unsupported", "invented_repeat", "invented_clock", "invented_duration", "wrong_domain", "unknown_id", "joined", "quoted"])
def test_source_and_catalog_validation(model, change):
    value, text = decision(), TEXT
    if change == "extra": value["steps"][0]["command"] = "calc.exe"
    if change == "partial": value["steps"] = value["steps"][:1]
    if change == "wrong_source": value["steps"][0]["source"] = "удали задачу"
    if change == "unsupported": value["steps"].append(dict(domain="task", action="delete", source="отправь письмо", candidates=["unknown"])); text += "; отправь письмо"
    if change == "invented_repeat": value["steps"][0]["repeat"] = "daily"
    if change == "invented_clock": value["steps"][0]["clock"] = "11:00"
    if change == "invented_duration": value["steps"][2]["duration_minutes"] = 40
    if change == "wrong_domain": value["steps"][0].update(domain="note", kind="todo", day="", clock="", content="не та запись")
    if change == "unknown_id": value["steps"][0].update(action="delete", candidates=["unknown"])
    if change == "joined": value["steps"] = [dict(domain="task", action="create", source=TEXT, title="одно дело")]
    if change == "quoted": text = "запиши заметку Инструкция: «" + TASK + "»"; value["steps"] = [value["steps"][0]]
    result = propose(model, value, text)
    assert result.plan is None, result.text
    assert not model[0].list("tasks") and not model[0].list("notes")


def test_whole_plan_cancellation_and_unrelated_reply(model):
    store, _, _ = model
    ask(store, propose(model))
    assert "отменён" in reply(store, "отмена").text
    assert not store.list("tasks")
    ask(store, propose(model))
    assert reply(store, "спасибо") is None
    assert "pending_action_plan" not in store.dialogue()
    assert reply(store, "да") is None


@pytest.mark.parametrize("change", ["expired", "zone", "disabled", "moved_chat", "deleted_chat", "restored", "attachments", "different_assistant"])
def test_old_confirmation_is_rejected(model, change):
    store, _, _ = model
    ask(store, propose(model))
    zone, now, allow = ZONE, NOW, True
    if change == "expired": now += timedelta(minutes=16)
    if change == "zone": zone = "UTC"
    if change == "disabled": store.patch_settings({"plan_understanding": False})
    if change == "moved_chat": Spaces(store).update_chat(store.conversation_id, "Новый", Spaces(store).create_project("Другой")["id"])
    if change == "deleted_chat": Spaces(store).delete_chat(store.conversation_id)
    if change == "restored":
        backup = Backups(store); backup.restore(backup.preview(backup.export())["ticket"])
    if change == "attachments": allow = False
    if change == "different_assistant": store.add_message("assistant", "Другое сообщение")
    if change == "deleted_chat":
        # Simulate a stale window: its already loaded message arrives after the move.
        with pytest.raises(ValueError):
            reply(store, zone=zone, now=now, allow=allow)
    else:
        result = reply(store, zone=zone, now=now, allow=allow)
        assert result is None or not result.changed
    assert not store.list("tasks") and not store.list("notes")


@pytest.mark.parametrize("domain", ["task", "note", "event"])
def test_one_changed_target_prevents_every_step(model, domain):
    store, _, _ = model
    old = store.save_task("Интернет", "todo", None) if domain == "task" else store.save_note("Интернет", "Прежний текст") if domain == "note" else event(store, "Интернет")
    phrase = {"task": "удали задачу Интернет", "note": "удали заметку Интернет", "event": "удали встречу Интернет"}[domain]
    value = decision()
    value["steps"].append(dict(domain=domain, action="delete", source=phrase, candidates=[old["id"]]))
    ask(store, propose(model, value, TEXT + "; " + phrase))
    if domain == "task": store.revise_task(old["id"], title="Изменено")
    if domain == "note": store.save_note("Интернет", "Другой текст", old["id"])
    if domain == "event": Calendar(store).save(EventBody.from_item(old, title="Изменено"), old["id"], old["updated"])
    result = reply(store)
    assert not result.changed and "устарел" in result.text
    assert len(store.list("tasks")) == (1 if domain == "task" else 0)
    assert len(store.list("notes")) == (1 if domain == "note" else 0)


def test_transaction_rolls_back_earlier_steps_after_late_failure(model):
    store, _, _ = model
    ask(store, propose(model))
    with store.db() as db: db.execute("CREATE TRIGGER reject_note BEFORE INSERT ON notes BEGIN SELECT RAISE(ABORT,'fixture'); END")
    result = reply(store)
    assert not result.changed and "отменены" in result.text
    assert not store.list("tasks") and not store.list("notes")
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM actions WHERE kind='plan'").fetchone()[0] == 0


def test_duplicate_names_choice_then_time_then_full_confirmation(model):
    store, _, _ = model
    first = store.save_task("Интернет", "todo", "2026-10-22T10:00:00+00:00")
    second = store.save_task("Интернет", "todo", "2026-10-23T10:00:00+00:00")
    source = "перенеси задачу Интернет на завтра утром"
    value = {"steps": [dict(domain="task", action="move", source=source, candidates=[first["id"]], day="2026-10-21", clock="09:00")]}
    outcome = propose(model, value, source)
    assert outcome.plan and "выберите запись" in outcome.text
    ask(store, outcome)
    selected = reply(store, "2")
    assert selected.plan and "укажите дату и время" in selected.text
    ask(store, selected)
    clarified = reply(store, "завтра в 12")
    assert clarified.plan and "Выполнить весь план" in clarified.text
    ask(store, clarified)
    assert reply(store, "да").changed == ["tasks"]
    assert store.task(first["id"])["due"] == first["due"]
    assert "2026-10-21T07:00" in store.task(second["id"])["due"]


def test_calendar_missing_hour_is_clarified_and_defaults_are_visible(model):
    store, _, _ = model
    source = "запланируй встречу Обзор завтра утром"
    outcome = propose(model, {"steps": [dict(domain="event", action="create", source=source, title="Обзор", day="2026-10-21", clock="09:00")]}, source)
    ask(store, outcome)
    assert "укажите дату и время" in outcome.text and outcome.plan.steps[0].step.clock == ""
    clarified = reply(store, "завтра в 12")
    assert "13:00" in clarified.text
    ask(store, clarified)
    assert reply(store).changed == ["calendar_events"]


@pytest.mark.parametrize("action", ["append", "update", "delete"])
def test_note_changes_review_old_and_new_text(model, action):
    store, _, _ = model
    old = store.save_note("Покупки", "Хлеб")
    source = {"append": "дополни заметку Покупки: молоко", "update": "измени заметку Покупки: молоко", "delete": "удали заметку Покупки"}[action]
    outcome = propose(model, {"steps": [dict(domain="note", action=action, source=source, candidates=[old["id"]], content="" if action == "delete" else "молоко")]}, source)
    ask(store, outcome)
    if action != "delete": assert "Хлеб" in outcome.text and "молоко" in outcome.text
    assert reply(store).changed == ["notes"]
    rows = store.list("notes")
    assert not rows if action == "delete" else rows[0]["content"] == ("Хлеб\nмолоко" if action == "append" else "молоко")


def test_pronoun_context_only_last_scoped_record(model):
    store, _, _ = model
    source = "запиши заметку Покупки: хлеб"
    ask(store, propose(model, {"steps": [dict(domain="note", action="create", source=source, title="Покупки", content="хлеб")]}, source))
    reply(store)
    target = store.list("notes")[0]
    followup = "дополни её: молоко"
    assert plans.eligible(followup, context=True)
    outcome = propose(model, {"steps": [dict(domain="note", action="append", source=followup, candidates=[target["id"]], content="молоко")]}, followup)
    ask(store, outcome)
    assert reply(store).changed == ["notes"]
    assert store.list("notes")[0]["content"] == "хлеб\nмолоко"
    project = Spaces(store).create_project("Другой")
    target_store = store.for_chat(Spaces(store).create_chat(project["id"])["id"])
    bad = propose(model, {"steps": [dict(domain="note", action="append", source=followup, candidates=[target["id"]], content="молоко")]}, followup, target_store)
    assert bad.plan is None


def test_confirmation_concurrency_consumes_one_transaction(model):
    store, _, _ = model
    outcome = propose(model)
    ask(store, outcome)
    pending = plans.Pending.model_validate(store.dialogue()["pending_action_plan"])
    def execute():
        try: return plans.execute(store, pending, NOW)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: execute(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(store.list("tasks")) == len(store.list("notes")) == 1


def test_chat_routes_full_plan_before_exact_task_commands_and_preserves_switch(model):
    store, replies, _ = model
    token = "action-plan-fixture-local-token"
    app = create_app(store.root, token)
    replies.append(decision())
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + token
    response = client.post("/chat", json={"text": TEXT, "timezone": ZONE})
    assert "Выполнить весь план" in response.text and not store.list("tasks")
    response = client.post("/chat", json={"text": "да", "timezone": ZONE})
    assert "План выполнен" in response.text and len(store.list("tasks")) == 1
    store.patch_settings({"plan_understanding": False})
    response = client.post("/chat", json={"text": TEXT, "timezone": ZONE})
    assert "выключено" in response.text and len(store.list("tasks")) == 1
    backup = Backups(store)
    backup.restore(backup.preview(backup.export())["ticket"], connections=True)
    assert not store.settings().plan_understanding


def test_cancelled_wait_keeps_committed_result_and_finishes_one_worker(model, monkeypatch):
    store, _, _ = model
    ask(store, propose(model))
    store.add_message("user", "да")
    started, release = threading.Event(), threading.Event()
    execute = plans.execute
    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return execute(*args, **kwargs)
    monkeypatch.setattr(plans, "execute", delayed)
    progress = []
    async def scenario():
        task = asyncio.create_task(plans.run_reply(store, store.settings(), "да", ZONE, progress=progress))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    assert "План выполнен" in progress[0]
    assert len(store.list("tasks")) == len(store.list("notes")) == 1
    assert len(plans.history(store)) == 1


def test_history_is_scoped_and_note_literal_cannot_be_replaced_by_model(model):
    store, _, _ = model
    value = decision()
    value["steps"][1].update(title="Вымышленное название", content="Вымышленный текст")
    outcome = propose(model, value)
    assert outcome.plan.steps[1].step.content == "забрать паспорт"
    ask(store, outcome)
    reply(store)
    assert plans.history(store)[0]["steps"][1]["title"] == "Документы"
    spaces = Spaces(store)
    other = store.for_chat(spaces.create_chat(spaces.create_project("Другой")["id"])["id"])
    assert plans.history(other) == []


@pytest.mark.parametrize("action", ["move", "delete"])
def test_calendar_named_changes_preserve_other_fields_and_verify(model, action):
    store, _, _ = model
    old = event(store, location="Кабинет", description="Прежнее описание", reminder_minutes=15)
    source = "перенеси встречу Обзор на следующую среду к полудню" if action == "move" else "удали встречу Обзор"
    step = dict(domain="event", action=action, source=source, candidates=[old["id"]])
    if action == "move": step.update(day="2026-10-21", clock="12:00")
    ask(store, propose(model, {"steps": [step]}, source))
    assert reply(store).changed == ["calendar_events"]
    with store.db() as db: row = db.execute("SELECT * FROM calendar_events WHERE id=?", (old["id"],)).fetchone()
    if action == "delete": assert row is None
    else:
        assert row["starts_at"] == "2026-10-21T07:00:00.000000+00:00"
        assert row["ends_at"] == "2026-10-21T08:00:00.000000+00:00"
        assert row["location"] == "Кабинет" and row["description"] == "Прежнее описание" and row["reminder_minutes"] == 15


def test_calendar_all_day_and_custom_name_literal_note(model):
    store, _, _ = model
    store.patch_settings({"name": "Алиса"})
    source = "Алиса, запиши заметку Чтение: когда вернусь, открой книгу"
    value = {"steps": [dict(domain="note", action="create", source=source)]}
    ask(store, propose(model, value, source))
    assert reply(store).changed == ["notes"]
    assert store.list("notes")[0]["content"] == "когда вернусь, открой книгу"
    source = "запланируй событие Отпуск завтра на весь день"
    value = {"steps": [dict(domain="event", action="create", source=source, title="Отпуск", day="2026-10-21", all_day=True)]}
    ask(store, propose(model, value, source))
    assert reply(store).changed == ["calendar_events"]
    with store.db() as db:
        assert db.execute("SELECT all_day FROM calendar_events").fetchone()[0] == 1


def test_silent_storage_rewrite_never_gets_success_receipt(model):
    store, _, _ = model
    ask(store, propose(model))
    with store.db() as db:
        db.execute("CREATE TRIGGER rewrite_note AFTER INSERT ON notes BEGIN UPDATE notes SET content='wrong' WHERE id=NEW.id; END")
    result = reply(store)
    assert not result.changed and "не подтвердило" in result.text
    assert not store.list("tasks") and not store.list("notes") and plans.history(store) == []


def test_polite_composite_and_note_cannot_swallow_another_order(model):
    store, _, _ = model
    text = "Уайли, можешь, пожалуйста, создать задачу купить хлеб; записать заметку Дом: полить цветы"
    assert plans.eligible(text)
    value = {"steps": [dict(domain="task", action="create", source="создать задачу купить хлеб", title="купить хлеб"), dict(domain="note", action="create", source="записать заметку Дом: полить цветы", title="Дом", content="полить цветы")]}
    outcome = propose(model, value, text)
    assert outcome.plan is not None, outcome.text
    bad = "запиши заметку Дом: полить цветы; удали задачу Интернет"
    outcome = propose(model, {"steps": [dict(domain="note", action="create", source=bad, title="Дом", content="полить цветы")]}, bad)
    assert outcome.plan is None and not store.list("notes")
