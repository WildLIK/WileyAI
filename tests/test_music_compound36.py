"""C5: no partial dispatch or latent confirmation for a multi-action music request."""
import pytest

from core.media_manager import parse
from core.music_intents import compound_request, resolve
from tests.test_media_manager import ctx, chat


COMPOUNDS = [
    'Включи Numb и поставь на паузу', 'Найди песню и включи вторую',
    'Включи музыку и открой Blender', 'Не включай музыку, а открой Яндекс Музыку',
    'Сделай тише и включи следующий трек', 'Включи музыку, потом следующую',
    'Поставь песню Numb, затем выключи звук', 'Включи песню Numb; открой Blender',
    'Найди и включи песню Numb и открой Blender',
]


def test_combined_find_and_play_is_not_split_into_two_independent_actions():
    assert not compound_request('Найди и включи Numb')
    assert resolve('Найди и включи песню Numb',preferred=True).query=='Numb'


@pytest.mark.parametrize('text', COMPOUNDS)
def test_compound_never_becomes_a_partial_song_query(text):
    assert compound_request(text)
    assert parse(text) is None and resolve(text, preferred=True) is None


@pytest.mark.parametrize('text', COMPOUNDS)
def test_chat_clarifies_without_any_executor_or_model_call(ctx, monkeypatch, text):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({'music_player':'yandex'})
    def forbidden(*a, **k): pytest.fail('No executor may receive any part of this request')
    monkeypatch.setattr('core.commands.execute', forbidden)
    monkeypatch.setattr('core.device_audio.AudioTools.execute', forbidden)
    monkeypatch.setattr(app.state.media, 'execute', forbidden)
    events = chat(client, text)
    action = next(e['action'] for e in events if e['type']=='speech_result')
    assert action['status'] == 'needs_clarification' and 'несколько действий' in action['display']
    assert not sent and not writes and not special


@pytest.mark.parametrize('text', [
    'Как включить музыку и открыть Blender?', 'Если включи музыку и открой Blender',
    'Он сказал включи музыку и открой Blender', '«Включи музыку и открой Blender»',
])
def test_quoted_conditional_and_question_are_not_direct_compound_actions(text):
    assert not compound_request(text)
    assert parse(text) is None and resolve(text, preferred=True) is None


@pytest.mark.parametrize('text,action,query', [
    ('Включи песню Numb','search_play','Numb'), ('Найди песню Linkin Park','search','Linkin Park'),
    ('Включи мою волну','wave',''), ('Продолжи музыку','play',''),
    ('Включи песню Любовь и голуби','search_play','Любовь и голуби'),
    ('Включи песню «Встань и включи свет»','search_play','Встань и включи свет'),
    ('Найди и включи песню Numb','search_play','Numb'),
])
def test_single_music_operations_and_titles_with_conjunctions_survive(ctx, monkeypatch, text, action, query):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({'music_player':'yandex'})
    monkeypatch.setattr(app.state.music, 'status', lambda: {'connected':True})
    assert not compound_request(text)
    chat(client, text)
    assert len(special)==1 and special[0].action==action and special[0].query==query
    assert not sent and not writes


def test_existing_search_then_second_selection_still_runs_once(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    app.state.store.patch_settings({'music_player':'yandex'})
    monkeypatch.setattr(app.state.music, 'status', lambda: {'connected':True})
    calls = []
    def execute(command, cancel=None):
        calls.append(command)
        if command.action=='search':
            return {'confirmed':False,'text':'1. Numb 2. Numb Live','candidates':[
                {'id':str(n),'title':title,'artists':'Linkin Park','search_id':'a'*32}
                for n,title in [(1,'Numb'),(2,'Numb Live')]]}
        return {'confirmed':True,'text':'Выбранная песня подтверждена'}
    monkeypatch.setattr(app.state.music,'execute',execute)
    chat(client,'Найди песню Numb')
    chat(client,'Включи вторую')
    assert [c.action for c in calls]==['search','select'] and calls[1].selection.id=='2'
    assert 'pending_media' not in app.state.store.dialogue()


def test_compound_retires_old_confirmation_and_does_not_schedule_later_actions(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    store=app.state.store; store.patch_settings({'music_player':'yandex'})
    store.save_dialogue({key:{'fixture':True} for key in ('pending_open','pending_audio','pending_media','media_choice','pending_task_plan','pending_action_plan')})
    chat(client,'Включи Numb и поставь на паузу')
    assert not store.dialogue()
    async def conversation(*a,**k): yield 'Фикстурный ответ без действий'
    monkeypatch.setattr('core.providers.chat',conversation)
    for text in ('да','отмена','да'): chat(client,text)
    assert not sent and not writes and not special


@pytest.mark.parametrize('dry_run',[True,False])
def test_command_endpoint_cannot_execute_a_compound_request(ctx, monkeypatch, dry_run):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    def forbidden(*a,**k): pytest.fail('No executor may receive a partial command')
    monkeypatch.setattr('core.commands.execute',forbidden)
    monkeypatch.setattr(app.state.media,'execute',forbidden)
    response=client.post('/commands',json={'text':'Включи Numb и поставь на паузу','dry_run':dry_run})
    assert response.status_code==200 and response.json()['status']=='needs_clarification'
    assert not sent and not writes and not special
