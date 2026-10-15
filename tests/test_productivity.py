from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from core.api import create_app
from core.storage import Store


TOKEN = "productivity-test-token-0123456789"
HEADERS = {"Authorization": "Bearer " + TOKEN}


def test_note_crud(tmp_path):
    with TestClient(create_app(tmp_path, TOKEN), headers=HEADERS) as api:
        note = api.post('/notes', json={'title': 'Покупки', 'content': '- хлеб\n- молоко'}).json()
        assert api.put('/notes/'+note['id'], json={'title':'Идеи','content':'Новый проект'}).status_code == 200
        assert api.get('/notes').json()[0]['title'] == 'Идеи'
        api.delete('/notes/'+note['id'])
        assert api.get('/notes').json() == []


def test_reminders_are_durable_and_do_not_duplicate(tmp_path):
    store = Store(tmp_path)
    due = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    task = store.save_task('Позвонить', 'reminder', due)
    assert len(store.queue_due_notifications()) == 1
    assert store.queue_due_notifications() == []
    restarted = Store(tmp_path)
    assert restarted.queue_due_notifications() == []
    assert len(restarted.list('notifications')) == 1
    # A changed deadline can fire again; completing the task suppresses queued alerts.
    restarted.save_task('Позвонить позже', 'reminder', (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), item_id=task['id'])
    assert len(restarted.queue_due_notifications()) == 1
    restarted.save_task('Позвонить позже', 'reminder', due, done=True, item_id=task['id'])
    assert restarted.queue_due_notifications() == []
    assert all(item['delivered'] for item in restarted.list('notifications'))


def test_cancelled_task_does_not_notify(tmp_path):
    store = Store(tmp_path)
    due = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    task=store.save_task('Не нужно', 'timer', due)
    store.queue_due_notifications()
    store.remove('tasks',task['id'])
    assert store.list('notifications') == []


def test_task_timezone_validation_and_capability_status(tmp_path):
    with TestClient(create_app(tmp_path,TOKEN), headers=HEADERS) as api:
        assert api.post('/tasks',json={'title':'Встреча','kind':'reminder','due':'2026-10-16T10:00:00'}).status_code == 400
        task=api.post('/tasks',json={'title':'Встреча','kind':'reminder','due':'2026-10-16T10:00:00+05:00'}).json()
        assert task['due'] == '2026-10-16T05:00:00+00:00'
        items={item['id']:item for item in api.get('/capabilities').json()}
        assert len(items) == 14
        assert items['calendar']['status'] == 'planned'
        assert items['tasks']['status'] == 'available'
