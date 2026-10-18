from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core import providers
from core.storage import Store
from core.timeparse import parse_time, due_time
from core.workflows import Workflows


ZONE = "Asia/Yekaterinburg"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=ZoneInfo(ZONE))
TOKEN = "workflow-tests-token-0123456789"


def test_local_timezone_with_surrogates_after_native_speech_still_saves_pending_question(tmp_path, monkeypatch):
    from core import workflows
    broken_zone = timezone(timedelta(hours=5), "RTZ 4 (\udce7\udce8\udcec\udce0)")
    class LocalClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 18, 12, tzinfo=tz or broken_zone)
        def astimezone(self, tz=None):
            return super().astimezone(tz or broken_zone)
    monkeypatch.setattr(workflows, "datetime", LocalClock)
    store = Store(tmp_path)
    result = Workflows(store).handle("напомни купить хлеб")
    assert "Когда" in result.text
    assert store.dialogue()["zone"] == "UTC+05:00"
    completed = Workflows(store).handle("завтра в 10")
    assert completed.changed == ["tasks"]
    assert store.list("tasks")[0]["title"] == "купить хлеб"


@pytest.fixture
def workflow(tmp_path):
    store = Store(tmp_path)
    return store, lambda text, now=NOW: Workflows(store).handle(text, ZONE, now)


@pytest.mark.parametrize("text,title,due", [
    ("Напомни завтра в 10 купить хлеб", "купить хлеб", "2026-10-17T05:00:00+00:00"),
    ("Уайли, пожалуйста, напомни мне купить хлеб завтра в десять тридцать", "купить хлеб", "2026-10-17T05:30:00+00:00"),
    ("Напомни сегодня в 6 вечера позвонить", "позвонить", "2026-10-16T13:00:00+00:00"),
    ("Напомни через двадцать пять минут отдохнуть", "отдохнуть", "2026-10-16T04:25:00+00:00"),
    ("Поставь таймер на 1 час 30 минут", "Таймер", "2026-10-16T05:30:00+00:00"),
    ("Запусти таймер пять минут", "Таймер", "2026-10-16T04:05:00+00:00"),
    ("Поставь будильник на 7:15", "Будильник", "2026-10-17T02:15:00+00:00"),
    ("Напомни 20.10.2026 в 10:05 отправить отчёт", "отправить отчёт", "2026-10-20T05:05:00+00:00"),
    ("Напомни в субботу в 12 купить хлеб или молоко", "купить хлеб или молоко", "2026-10-17T07:00:00+00:00"),
    ("Создай напоминание на 20.10.2026 в 10 купить хлеб", "купить хлеб", "2026-10-20T05:00:00+00:00"),
    ("Напомни, пожалуйста, на завтра в 10 купить хлеб", "купить хлеб", "2026-10-17T05:00:00+00:00"),
    ("Поставь будильник на одиннадцать часов", "Будильник", "2026-10-16T06:00:00+00:00"),
    ("Поставь таймер на одиннадцать часов", "Таймер", "2026-10-16T15:00:00+00:00"),
])
def test_create_actions_without_llm(workflow, text, title, due):
    store, handle = workflow
    result = handle(text)
    assert result.changed == ["tasks"]
    assert "UTC+05:00" in result.text
    task, = store.list("tasks")
    assert task["title"] == title
    assert task["due"] == due


def test_missing_time_is_durable_and_does_not_create_a_partial_task(workflow):
    store, handle = workflow
    result = handle("Напомни купить 10 яблок")
    assert "Когда" in result.text and "не создана" in result.text
    assert store.list("tasks") == []
    # A new runtime instance uses the same saved clarification.
    result = Workflows(Store(store.root)).handle("завтра в одиннадцать", ZONE, NOW)
    assert result.changed == ["tasks"]
    task, = store.list("tasks")
    assert task["title"] == "купить 10 яблок"
    assert task["due"] == "2026-10-17T06:00:00+00:00"


def test_missing_title_preserves_original_relative_deadline(workflow):
    store, handle = workflow
    assert "о чём" in handle("Напомни через 15 минут").text.casefold()
    handle("Проверить чайник", NOW + timedelta(minutes=2))
    assert store.list("tasks")[0]["due"] == "2026-10-16T04:15:00+00:00"


def test_plain_todo_and_note_content_are_not_interpreted_as_another_action(workflow):
    store, handle = workflow
    assert handle("Добавь задачу проверить сборку").changed == ["tasks"]
    assert store.list("tasks")[0]["due"] is None
    assert handle("Создай заметку Идеи: напомни завтра в 10 открыть браузер").changed == ["notes"]
    note, = store.list("notes")
    assert note["title"] == "Идеи"
    assert note["content"] == "напомни завтра в 10 открыть браузер"
    assert len(store.list("tasks")) == 1


def test_reschedule_keeps_date_and_title_then_cancel_and_complete(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    original, = store.list("tasks")
    assert "Можно перенести" in handle("А если я буду занят?").text
    assert handle("Перенеси на 11").changed == ["tasks"]
    task, = store.list("tasks")
    assert task["id"] == original["id"] and task["title"] == original["title"]
    assert task["due"] == "2026-10-17T06:00:00+00:00"
    handle("Лучше завтра в 12")
    assert store.task(task["id"])["due"] == "2026-10-17T07:00:00+00:00"
    handle("Отмени это напоминание")
    assert store.list("tasks") == []
    handle("Добавь задачу проверить код")
    handle("Отметь задачу выполненной")
    assert store.list("tasks")[0]["done"] == 1


def test_cancelling_pending_creation_does_not_delete_an_older_task(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    handle("Напомни позвонить")
    handle("Отмени напоминание")
    assert store.list("tasks")[0]["title"] == "купить хлеб"
    assert "pending" not in store.dialogue()


def test_relative_reschedule_shifts_existing_deadline_not_current_time(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 позвонить")
    handle("Перенеси на 15 минут позже")
    assert store.list("tasks")[0]["due"] == "2026-10-17T05:15:00+00:00"
    handle("Перенеси на полчаса раньше")
    assert store.list("tasks")[0]["due"] == "2026-10-17T04:45:00+00:00"
    handle("Перенеси через 10 минут")
    assert store.list("tasks")[0]["due"] == "2026-10-16T04:10:00+00:00"


def test_misrecognized_past_tense_never_claims_or_performs_reschedule(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    original = store.list("tasks")[0]["due"]
    result = handle("перенесено 11.")
    assert "Срок не менял" in result.text and result.changed == []
    assert store.list("tasks")[0]["due"] == original
    assert handle("Перенеси напоминание на одиннадцать часов").changed == ["tasks"]
    assert store.list("tasks")[0]["due"] == "2026-10-17T06:00:00+00:00"


@pytest.mark.parametrize("text", [
    "Не напомни завтра в 10 купить хлеб", "Как создать напоминание?", "Напомни завтра в 10?",
    '«Напомни завтра в 10 купить хлеб»', 'Пример команды: "напомни завтра в 10 купить хлеб"',
])
def test_non_commands_have_no_effect(workflow, text):
    store, handle = workflow
    assert handle(text) is None
    assert store.list("tasks") == [] and store.list("notes") == []


@pytest.mark.parametrize("text", [
    "Напомни завтра в 25 купить хлеб", "Напомни 31.02.2027 в 10 позвонить", "Напомни сегодня в 8 позвонить",
    "Поставь таймер на 0 минут", "Напомни завтра в 10 или 11 позвонить",
    "Напомни завтра в 10:5 позвонить", "Напомни завтра в 10 через 5 минут позвонить",
])
def test_invalid_or_ambiguous_times_never_create_records(workflow, text):
    store, handle = workflow
    result = handle(text)
    assert result is not None and result.changed == []
    assert store.list("tasks") == []


def test_context_expires_and_deleted_record_is_not_recreated(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    task, = store.list("tasks")
    assert "Не вижу" in handle("Перенеси на 11", NOW + timedelta(minutes=16)).text
    assert store.task(task["id"])["due"] == task["due"]
    store.remove("tasks", task["id"])
    assert "Не вижу" in handle("Перенеси на 11").text
    assert store.revise_task(task["id"], due=task["due"]) is None
    assert store.list("tasks") == []


def test_reschedule_removes_old_queued_notification(tmp_path):
    store = Store(tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    task = store.save_task("Позвонить", "reminder", past)
    store.queue_due_notifications()
    assert len(store.list("notifications")) == 1
    store.revise_task(task["id"], due=future)
    assert store.list("notifications") == []
    assert store.queue_due_notifications() == []
    # The same fix applies to edits from the tasks form.
    store.save_task("Позвонить", "reminder", past, item_id=task["id"])
    store.queue_due_notifications()
    store.save_task("Позвонить", "reminder", future, item_id=task["id"])
    assert store.list("notifications") == []


@pytest.mark.parametrize("day,clock", [("2027-03-14", "02:30"), ("2026-11-01", "01:30")])
def test_dst_missing_or_ambiguous_wall_time_is_rejected(day, clock):
    zone = ZoneInfo("America/New_York")
    from datetime import date, time
    with pytest.raises(ValueError, match="переводе часов"):
        due_time(date.fromisoformat(day), time.fromisoformat(clock), NOW.astimezone(zone))


def test_chat_actions_do_not_call_llm_and_share_voice_context(tmp_path, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Local actions should not call a model")
        yield ""
    monkeypatch.setattr(providers, "chat", forbidden)
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_app(tmp_path, TOKEN), headers=headers) as api:
        response = api.post("/chat", json={"text": "Напомни завтра в 10 купить хлеб", "mode": "conversation", "timezone": ZONE})
        assert '"type": "error"' not in response.text
        assert '"changed": ["tasks"]' in response.text
        response = api.post("/chat", json={"text": "Перенеси на 11", "timezone": ZONE})
        assert '"type": "error"' not in response.text
        task, = api.get("/tasks").json()
        local = datetime.fromisoformat(task["due"]).astimezone(ZoneInfo(ZONE))
        assert local.hour == 11 and task["title"] == "купить хлеб"
        assert "11:00 (UTC+05:00)" in response.text
        assert api.post("/chat", json={"text": "Привет", "timezone": "Bad/Timezone"}).status_code == 422


# ── Recurring reminders ─────────────────────────────────────────────────────

import json as _json


@pytest.mark.parametrize("text,rule,weekday", [
    ("Напомни ежедневно в 10 купить хлеб", "daily", None),
    ("Напомни каждый день в 9 проверить почту", "daily", None),
    ("Напомни по будням в 9 проверить почту", "weekdays", None),
    ("Напомни по рабочим дням в 9 проверить почту", "weekdays", None),
    ("Напомни каждый понедельник в 14 заполнить отчёт", "weekly", 0),
    ("Напомни каждую пятницу в 18 подвести итоги", "weekly", 4),
])
def test_create_recurring_reminder(workflow, text, rule, weekday):
    store, handle = workflow
    result = handle(text)
    assert result.changed == ["tasks"], result.text
    task, = store.list("tasks")
    assert task["recurrence"] is not None, "recurrence must be saved"
    rec = _json.loads(task["recurrence"])
    assert rec["rule"] == rule
    assert rec.get("weekday") == weekday
    # Confirmation message must mention recurrence
    assert any(kw in result.text for kw in ("ежедневно", "будн", "понедельник", "пятниц", "рабочи")), result.text


def test_recurring_reminder_confirmation_contains_due_and_recurrence(workflow):
    store, handle = workflow
    result = handle("Напомни ежедневно в 10 купить хлеб")
    # Must mention both a due time and the recurrence label
    assert "10:00" in result.text
    assert "ежедневно" in result.text


def test_non_recurring_reminder_has_no_recurrence_field(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    task, = store.list("tasks")
    assert task["recurrence"] is None


def test_cancel_series_clears_recurrence_and_keeps_task(workflow):
    store, handle = workflow
    handle("Напомни ежедневно в 10 купить хлеб")
    task, = store.list("tasks")
    assert task["recurrence"] is not None

    result = handle("Отмени повтор напоминания")
    assert result.changed == ["tasks"], result.text
    assert "Повтор отменён" in result.text
    task_after = store.task(task["id"])
    assert task_after is not None, "task must still exist"
    assert task_after["done"] == 0, "task must not be marked done"
    assert task_after["recurrence"] is None, "recurrence must be cleared"


def test_cancel_series_on_non_recurring_returns_error(workflow):
    store, handle = workflow
    handle("Напомни завтра в 10 купить хлеб")
    result = handle("Отмени повтор")
    assert "не повторяется" in result.text
    assert result.changed == []


def test_queue_due_advances_recurring_reminder(tmp_path):
    store = Store(tmp_path)
    # Create a recurring reminder due 1 min in the past
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    rec_json = _json.dumps({"rule": "daily"})
    task = store.save_task("Купить хлеб", "reminder", past, recurrence=rec_json)

    fired = store.queue_due_notifications()
    assert len(fired) == 1

    updated = store.task(task["id"])
    assert updated is not None
    # due must be in the future
    new_due = datetime.fromisoformat(updated["due"])
    assert new_due > datetime.now(timezone.utc)
    # notified must be reset to 0 so the next firing will work
    assert updated["notified"] == 0
    assert updated["done"] == 0
    # recurrence must be preserved
    assert updated["recurrence"] == rec_json


def test_queue_due_does_not_advance_non_recurring(tmp_path):
    store = Store(tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    task = store.save_task("Купить хлеб", "reminder", past)

    store.queue_due_notifications()
    updated = store.task(task["id"])
    assert updated["notified"] == 1
    # due stays unchanged
    assert updated["due"] == past


def test_reschedule_preserves_recurrence(workflow):
    store, handle = workflow
    handle("Напомни ежедневно в 10 купить хлеб")
    task_before, = store.list("tasks")
    rec = task_before["recurrence"]
    assert rec is not None

    result = handle("Перенеси напоминание на 11")
    assert result.changed == ["tasks"], result.text
    task_after, = store.list("tasks")
    assert task_after["recurrence"] == rec, "recurrence must survive reschedule"
    new_due = datetime.fromisoformat(task_after["due"]).astimezone(ZoneInfo(ZONE))
    assert new_due.hour == 11


def test_revise_task_allows_clearing_recurrence(tmp_path):
    store = Store(tmp_path)
    rec_json = _json.dumps({"rule": "daily"})
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    task = store.save_task("Тест", "reminder", future, recurrence=rec_json)
    assert store.task(task["id"])["recurrence"] == rec_json

    updated = store.revise_task(task["id"], recurrence=None)
    assert updated is not None
    assert updated["recurrence"] is None


def test_revise_task_rejects_unknown_key(tmp_path):
    store = Store(tmp_path)
    task = store.save_task("Тест", "todo", None)
    with pytest.raises(ValueError):
        store.revise_task(task["id"], unknown_field="x")
