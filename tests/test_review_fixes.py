import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from core import providers
from core.api import create_app
from core.commands import Command, validate
from core.scheduler import run_scheduler
from core.storage import Store
from core.timeparse import parse_time

TOKEN = "test-local-session-0123456789abcdef"
HEADERS = {"Authorization": "Bearer " + TOKEN}
ZONE = ZoneInfo("Asia/Yekaterinburg")


def test_scheduler_survives_a_failed_tick():
    calls = []

    class Flaky:
        def queue_due_notifications(self):
            calls.append("queue")
            if len(calls) == 1:
                raise RuntimeError("database is locked")

        def prune_delivered(self):
            pass

    async def run():
        task = asyncio.create_task(run_scheduler(Flaky(), interval=0))
        while len(calls) < 3:
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert len(calls) >= 3


@pytest.mark.parametrize("text, clock", [("позвонить маме в 10.30", time(10, 30)), ("встреча в 9.05", time(9, 5))])
def test_dotted_clock_after_v_is_a_time(text, clock):
    result = parse_time(text, datetime(2026, 10, 24, 8, 0, tzinfo=ZONE))
    assert not result.error
    assert result.clock == clock


def test_dotted_date_without_v_stays_a_date():
    result = parse_time("отчёт 10.05", datetime(2026, 10, 24, 8, 0, tzinfo=ZONE))
    assert result.day is not None and (result.day.day, result.day.month) == (10, 5)


def test_same_weekday_after_the_hour_means_next_week():
    monday = datetime(2026, 10, 26, 12, 0, tzinfo=ZONE)
    result = parse_time("в понедельник в 9", monday)
    assert not result.error
    assert result.day.isoformat() == "2026-11-02"


@pytest.mark.parametrize("name", ["x.hta", "x.wsf", "x.cpl", "x.reg", "x.jse"])
def test_script_files_are_not_opened_as_documents(name, tmp_path):
    target = tmp_path / name
    target.write_text("")
    with pytest.raises(ValueError):
        validate(Command(kind="file", target=str(target), label="x"))


def test_old_tasks_beyond_the_newest_500_are_editable(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "get_key", lambda settings: "")
    store = Store(tmp_path)
    oldest = store.save_task("самая старая", "todo", None)
    for index in range(501):
        store.save_task(f"задача {index}", "todo", None)
    with TestClient(create_app(tmp_path, TOKEN), headers=HEADERS) as client:
        response = client.put(f"/tasks/{oldest['id']}", json={"title": "переименована"})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "переименована"
