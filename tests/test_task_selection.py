from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from core.api import create_app
from core import providers
from core.chatspaces import Spaces
from core.storage import Store
from core.task_selection import snapshot
from core.workflows import Workflows

ZONE = "Asia/Yekaterinburg"
NOW = datetime(2026, 10, 18, 9, tzinfo=ZoneInfo(ZONE))
TOKEN = "task-selection-test-token-0123456789"


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    def handle(text, now=NOW):
        return Workflows(Store(tmp_path)).handle(text, ZONE, now)
    return store, handle


def seed(store, title="Купить хлеб", due="2026-10-19T05:00:00+00:00", kind="reminder", **kwargs):
    return store.save_task(title, kind, due, **kwargs)


@pytest.mark.parametrize("text", [
    "Перенеси напоминание купить хлеб на 11", "Перенеси напоминание «Купить хлеб» на 11",
    'Уайли, перенеси напоминание "купить хлеб" на одиннадцать часов',
])
def test_old_named_task_moves_without_recent_context(setup, text):
    store, handle = setup
    selected = seed(store)
    recent = seed(store, "Другая запись")
    store.save_dialogue({"last_task": recent["id"], "updated": NOW.timestamp(), "zone": ZONE})
    result = handle(text)
    assert result.changed == ["tasks"], result.text
    assert store.task(selected["id"])["due"] == "2026-10-19T06:00:00+00:00"
    assert store.task(recent["id"])["due"] == recent["due"]


def test_duplicate_titles_need_number_and_resume_after_restart(setup):
    store, handle = setup
    first = seed(store)
    second = seed(store, due="2026-10-20T05:00:00+00:00")
    result = handle("Перенеси напоминание купить хлеб на 11")
    assert result.changed == [] and "1." in result.text and "2." in result.text
    assert store.task(first["id"])["due"] == first["due"]
    assert handle("да").changed == []
    assert handle("9").changed == []
    assert handle("второе").changed == ["tasks"]
    assert store.task(second["id"])["due"] == "2026-10-20T06:00:00+00:00"
    assert store.task(first["id"])["due"] == first["due"]


def test_lookup_by_title_and_day_then_recent_command(setup):
    store, handle = setup
    first = seed(store)
    second = seed(store, due="2026-10-20T05:00:00+00:00")
    result = handle("Найди напоминание хлеб на завтра")
    assert "Выбрана запись" in result.text
    assert handle("Перенеси на 12").changed == ["tasks"]
    assert store.task(first["id"])["due"] == "2026-10-19T07:00:00+00:00"
    assert store.task(second["id"])["due"] == second["due"]


def test_move_selector_can_include_original_date(setup):
    store, handle = setup
    first = seed(store)
    second = seed(store, due="2026-10-20T05:00:00+00:00")
    assert handle("Перенеси напоминание хлеб с 20.10.2026 на завтра в 12").changed == ["tasks"]
    assert store.task(first["id"])["due"] == first["due"]
    assert store.task(second["id"])["due"] == "2026-10-19T07:00:00+00:00"


def test_quoted_date_like_title_is_literal(setup):
    store, handle = setup
    literal = seed(store, "План на завтра")
    seed(store, "План", due="2026-10-19T06:00:00+00:00")
    assert handle('Удали напоминание «План на завтра»').changed == ["tasks"]
    assert store.task(literal["id"]) is None and len(store.list("tasks")) == 1


def test_past_deadline_moves_to_next_clock_and_past_date_lookup(setup):
    store, handle = setup
    old = seed(store, due="2026-10-17T05:00:00+00:00")
    assert "Выбрана" in handle("Найди напоминание хлеб на вчера").text
    assert handle("Перенеси напоминание хлеб на 11").changed == ["tasks"]
    assert store.task(old["id"])["due"] == "2026-10-18T06:00:00+00:00"


@pytest.mark.parametrize("edit", ["title", "due", "done", "recurrence", "delete"])
def test_changed_choice_is_rejected_instead_of_overwriting(setup, edit):
    store, handle = setup
    first = seed(store)
    second = seed(store, due="2026-10-20T05:00:00+00:00")
    handle("Удали напоминание хлеб")
    if edit == "delete":
        store.remove("tasks", first["id"])
    else:
        value = {"title": "Новое имя", "due": "2026-10-21T05:00:00+00:00", "done": True,
                 "recurrence": '{"rule":"daily"}'}[edit]
        store.revise_task(first["id"], **{edit: value})
    result = handle("1")
    assert result.changed == [] and "изменилась или удалена" in result.text
    assert store.task(second["id"]) is not None
    assert "task_choice" not in store.dialogue()


def test_date_changes_by_scheduler_invalidate_choice(setup, monkeypatch):
    store, handle = setup
    monkeypatch.setattr("core.storage.now", lambda: "2026-10-18T06:00:00+00:00")
    first = seed(store, due="2026-10-18T05:00:00+00:00", recurrence='{"rule":"daily"}')
    seed(store, due="2026-10-20T05:00:00+00:00")
    handle("Удали напоминание хлеб")
    store.queue_due_notifications()
    assert "изменилась" in handle("1").text
    assert store.task(first["id"]) is not None


def test_scopes_and_moved_chat_never_allow_old_selection(setup):
    store, handle = setup
    common = seed(store)
    spaces = Spaces(store)
    project = spaces.create_project("Личное")
    chat = spaces.create_chat(project["id"])
    scoped = store.for_chat(chat["id"])
    private = seed(scoped)
    assert Workflows(scoped).handle("Удали напоминание хлеб", ZONE, NOW).changed == ["tasks"]
    assert scoped.task(private["id"]) is None and store.task(common["id"]) is not None
    first = seed(store, "Отчёт")
    seed(store, "Отчёт", due="2026-10-20T05:00:00+00:00")
    handle("Удали напоминание отчёт")
    stale = store.for_chat()
    spaces.update_chat(stale.conversation_id, "Перенесён", project["id"])
    with pytest.raises(ValueError, match="перемещён"):
        stale.remove("tasks", first["id"], expected=snapshot(first))
    assert store.task(first["id"]) is not None


def test_record_before_500_newer_tasks_can_be_found(setup):
    store, handle = setup
    old = seed(store, "Проверить старый отчёт")
    with store.db() as db:
        db.executemany("INSERT INTO tasks (id,title,kind,due,created,scope_id) VALUES (?,?, 'todo',NULL,?,'')",
                       [(f"filler-{i}", f"Новое дело {i}", "2026-10-20T00:00:00+00:00") for i in range(510)])
    assert handle("Удали напоминание старый отчет").changed == ["tasks"]
    assert store.task(old["id"]) is None


def test_exact_title_precedes_prefix_matches(setup):
    store, handle = setup
    exact = seed(store, "Чай")
    other = seed(store, "Чайник")
    assert handle("Удали напоминание чай").changed == ["tasks"]
    assert store.task(exact["id"]) is None and store.task(other["id"]) is not None


def test_more_than_eight_matches_requires_narrowing(setup):
    store, handle = setup
    for i in range(9):
        seed(store, "Почта", due=f"2026-11-{i+1:02}T05:00:00+00:00")
    assert "больше восьми" in handle("Удали напоминание почта").text
    assert len(store.list("tasks")) == 9 and "task_choice" not in store.dialogue()


def test_cancel_expiry_and_unrelated_turn_do_not_execute_stale_choice(setup):
    store, handle = setup
    seed(store)
    seed(store, due="2026-10-20T05:00:00+00:00")
    handle("Удали напоминание хлеб")
    assert "отменён" in handle("отмена").text
    assert handle("1") is None
    handle("Удали напоминание хлеб")
    assert handle("1", NOW + timedelta(minutes=16)) is None
    handle("Удали напоминание хлеб")
    assert handle("Привет") is None and handle("2") is None
    assert len(store.list("tasks")) == 2


def test_missing_time_clarification_checks_snapshot(setup):
    store, handle = setup
    task = seed(store)
    assert "На какое время" in handle("Перенеси напоминание «Купить хлеб»").text
    store.revise_task(task["id"], title="Другое название")
    assert "изменилась" in handle("в 11").text
    assert store.task(task["id"])["due"] == task["due"]


def test_delayed_choice_does_not_move_relative_deadline_forward(setup):
    store, handle = setup
    first = seed(store)
    seed(store, due="2026-10-20T05:00:00+00:00")
    handle("Перенеси напоминание хлеб через 10 минут")
    assert handle("1", NOW + timedelta(minutes=2)).changed == ["tasks"]
    assert store.task(first["id"])["due"] == "2026-10-18T04:10:00+00:00"


def test_late_choice_does_not_create_past_deadline(setup):
    store, handle = setup
    first = seed(store)
    seed(store, due="2026-10-20T05:00:00+00:00")
    handle("Перенеси напоминание хлеб через 1 минуту")
    assert "прошло" in handle("1", NOW + timedelta(minutes=2)).text
    assert store.task(first["id"])["due"] == first["due"]


def test_named_recurrence_stop_resume_cancel_and_delete(setup):
    store, handle = setup
    task = seed(store, "Почта", recurrence=json.dumps({"rule": "weekdays", "timezone": ZONE}))
    assert handle("Останови серию напоминания почта").changed == ["tasks"]
    assert store.task(task["id"])["done"] == 1
    assert handle("Возобнови серию напоминания почта").changed == ["tasks"]
    assert store.task(task["id"])["done"] == 0
    assert handle("Отмени повтор напоминания почта").changed == ["tasks"]
    assert store.task(task["id"])["recurrence"] is None
    assert handle("Удали напоминание почта").changed == ["tasks"]
    assert store.task(task["id"]) is None


def test_complete_and_delete_completed_todo(setup):
    store, handle = setup
    task = seed(store, "Проверить сборку", due=None, kind="todo")
    assert handle("Отметь задачу проверить сборку выполненной").changed == ["tasks"]
    assert store.task(task["id"])["done"] == 1
    assert handle("Удали задачу проверить сборку").changed == ["tasks"]
    assert store.task(task["id"]) is None


@pytest.mark.parametrize("text", ["Перенеси напоминание нет такой записи на 11", "Удали напоминание нет такой записи"])
def test_no_match_never_falls_back_to_recent_task(setup, text):
    store, handle = setup
    task = seed(store)
    store.save_dialogue({"last_task": task["id"], "updated": NOW.timestamp(), "zone": ZONE})
    assert "Не найдено" in handle(text).text
    assert store.task(task["id"])["due"] == task["due"]


def test_failed_or_completed_lookup_cannot_leave_unrelated_recent_target(setup):
    store, handle = setup
    unrelated = seed(store, "Другое")
    completed = seed(store, "Завершённое", done=True)
    for query in ["Найди напоминание отсутствует", "Найди напоминание завершённое"]:
        store.save_dialogue({"last_task": unrelated["id"], "updated": NOW.timestamp(), "zone": ZONE})
        handle(query)
        assert "Не вижу" in handle("Перенеси на 11").text
        assert store.task(unrelated["id"])["due"] == unrelated["due"]
    assert store.task(completed["id"])["done"] == 1


def test_atomic_snapshot_guard_on_update_and_delete(setup):
    store, _ = setup
    task = seed(store)
    expected = snapshot(task)
    store.revise_task(task["id"], title="Из другого окна")
    with pytest.raises(ValueError, match="изменилась"):
        store.revise_task(task["id"], expected=expected, done=True)
    with pytest.raises(ValueError, match="изменилась"):
        store.remove("tasks", task["id"], expected=expected)
    assert store.task(task["id"])["done"] == 0


def test_api_choices_skip_llm_and_do_not_survive_unrelated_assistant_reply(tmp_path, monkeypatch):
    calls = []
    async def chat(*_args):
        calls.append(True)
        yield "Привет!"
    monkeypatch.setattr(providers, "chat", chat)
    store = Store(tmp_path)
    seed(store)
    seed(store, due="2026-10-20T05:00:00+00:00")
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization": "Bearer " + TOKEN}) as api:
        def send(text, mode="text"):
            response = api.post("/chat", json={"text": text, "timezone": ZONE, "mode": mode})
            assert '"type": "error"' not in response.text, response.text
            return response.text
        assert "Найдено несколько" in send("Удали напоминание хлеб", "conversation")
        assert '"changed": ["tasks"]' in send("второе")
        assert calls == [] and len(store.list("tasks")) == 1
        seed(store)
        send("Удали напоминание хлеб")
        send("Расскажи что-нибудь")
        send("1")
        assert len(store.list("tasks")) == 2
