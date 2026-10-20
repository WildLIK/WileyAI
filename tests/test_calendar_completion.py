import json
from datetime import datetime,timedelta,timezone

import pytest

from core.calendar import Calendar, EventBody
from core.storage import Store
from core.backups import Backups
from core.google_calendar import google_body, event_body, digest
from core.google_calendar import GoogleChoice
from test_google_calendar import FakeGoogle,configured,vault,anyio_backend,remote_event,local_body


def body(**changes):
    return EventBody(**{**dict(title="Месячный отчёт", starts_at="2026-01-31T10:00", ends_at="2026-01-31T11:00", timezone="Asia/Yekaterinburg", recurrence={"rule":"monthly"}), **changes})


def test_monthday_skips_short_months_last_day_and_google_roundtrip(tmp_path):
    calendar = Calendar(Store(tmp_path))
    item = calendar.save(body())
    events = calendar.list("2026-01-01T00:00Z", "2026-06-01T00:00Z")["events"]
    assert [item["starts_at"][5:10] for item in events] == ["01-31", "03-31", "05-31"]
    last = body(recurrence={"rule":"monthly", "monthday":-1, "excluded":["2026-02-28"]})
    calendar.save(last,item["id"],item["updated"])
    events = calendar.list("2026-01-01T00:00Z", "2026-06-01T00:00Z")["events"]
    assert [item["starts_at"][5:10] for item in events] == ["01-31", "03-31", "04-30", "05-31"]
    assert digest(event_body(google_body(last),last.timezone)) == digest(last)
    remote=google_body(last)
    remote["recurrence"][1]="EXDATE:20260228T090000Z"
    with pytest.raises(ValueError,match="Время исключения"): event_body(remote,last.timezone)


def test_single_occurrence_move_skip_staleness_backup_and_series_delete(tmp_path):
    store = Store(tmp_path)
    calendar = Calendar(store)
    item = calendar.save(body(starts_at="2026-10-20T10:00",ends_at="2026-10-20T11:00",recurrence={"rule":"daily"}))
    window = ("2026-10-20T00:00Z", "2026-10-23T00:00Z")
    first, second, _ = calendar.list(*window)["events"]
    moved = calendar.occurrence(item["id"],first["starts_at"],item["updated"],body(starts_at="2026-10-20T12:00",ends_at="2026-10-20T13:00",recurrence=None))
    with pytest.raises(ValueError): calendar.occurrence(item["id"], second["starts_at"],item["updated"])
    current = calendar.get(item["id"])
    calendar.occurrence(item["id"],second["starts_at"],current["updated"])
    events = calendar.list(*window)["events"]
    assert len(events) == 2 and any(event["id"] == moved["id"] for event in events)
    target = Store(tmp_path / "restore")
    backup = Backups(target)
    backup.restore(backup.preview(Backups(store).export())["ticket"])
    assert len(Calendar(target).list(*window)["events"]) == 2
    assert Calendar(target).get(moved["id"])["parent_id"] == item["id"]
    calendar.remove(item["id"])
    assert calendar.list(*window)["total"] == 0


@pytest.mark.anyio
async def test_optional_background_import_leaves_writes_and_conflicts_for_review(tmp_path,vault):
    store=Store(tmp_path)
    fake=FakeGoogle()
    moment=datetime.now(timezone.utc)+timedelta(hours=1)
    template=local_body(starts_at=moment.isoformat(),ends_at=(moment+timedelta(hours=1)).isoformat())
    fake.events["remote"]=remote_event("remote",**google_body(template))
    manager=await configured(store,fake)
    await manager.auto_tick()
    assert not Calendar(store).list(moment.isoformat(),(moment+timedelta(days=1)).isoformat())["events"]
    manager.set_auto(store,True)
    await manager.auto_tick()
    events=Calendar(store).list(moment.isoformat(),(moment+timedelta(days=1)).isoformat())["events"]
    assert len(events)==1 and all(request.method=="GET" for request in fake.calls)
    # Changes on both sides must remain pending; automatic import never overwrites.
    item=Calendar(store).get(events[0]["id"])
    Calendar(store).save(local_body(starts_at=moment.isoformat(),ends_at=(moment+timedelta(hours=1)).isoformat(),title="Местная версия"),item["id"],item["updated"])
    fake.events["remote"]["summary"]="Google версия"
    fake.events["remote"]["etag"]='"v2"'
    with store.db() as db: db.execute("UPDATE google_calendar_auto SET last_checked=''")
    await manager.auto_tick()
    assert manager.status(store)["auto"]["pending"]==1
    assert Calendar(store).get(item["id"])["title"]=="Местная версия"
    assert all(request.method=="GET" for request in fake.calls)
    manager.set_auto(store,False)
    await manager.close()


@pytest.mark.anyio
async def test_account_changed_while_getting_token_never_exports_under_new_login(tmp_path,vault,monkeypatch):
    store,fake=Store(tmp_path),FakeGoogle()
    Calendar(store).save(local_body())
    manager=await configured(store,fake)
    preview=await manager.preview(store,"2026-10-19T00:00Z","2026-10-26T00:00Z")
    original=manager.auth.access
    async def changed():
        token,_=await original()
        manager.auth.write({**manager.auth.read(),"epoch":"new-account"})
        return token,"new-account"
    monkeypatch.setattr(manager.auth,"access",changed)
    result=await manager.apply(store,preview["ticket"],[GoogleChoice(id=preview["rows"][0]["id"],direction="local")])
    assert not result["results"][0]["ok"]
    assert not fake.events and all(request.method=="GET" for request in fake.calls)
    await manager.close()
