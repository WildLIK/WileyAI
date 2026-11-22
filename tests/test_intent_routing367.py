"""3.6.7 domain boundaries: actual parsers/API; fake installed apps/media/audio."""
import json

import pytest

from core import commands, media_manager, music_intents
from core.launch_verification import ExecutionText
from tests.test_media_manager import ctx
from tests.test_music_natural_c3_c4 import natural


def chat(client,text):
    response=client.post('/chat',json={'text':text,'mode':'conversation'})
    assert response.status_code==200,response.text
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert any(e['type']=='done' for e in events),[e for e in events if e['type']=='error']
    return events


APP_SEARCH = [
    'Найди подходящую программу для пиксельного рисунка',
    'Найди программу для редактирования фотографий',
    'Найди удобное приложение для моделирования',
    'Найди мне хороший редактор изображений',
    'Найди новый рисунок',
    'Поставь подходящую программу для рисования',
    'Включи установленный графический редактор',
]
PREVIOUS = [
    'Предыдущий трек', 'Переключи на предыдущую', 'Верни прошлую песню',
    'Поставь предыдущую композицию', 'Пожалуйста, поставь предшествующую композицию',
    'Верни предыдущую песню', 'Поставь предшествующий трек',
]


@pytest.mark.parametrize('text',APP_SEARCH)
@pytest.mark.parametrize('explicit',[False,True])
def test_non_musical_objects_veto_free_query_even_with_player_context(text,explicit):
    value,_=music_intents.request(text)
    assert music_intents.free_query(value,music_context=True,explicit=explicit) is None
    assert media_manager.parse(text,music_context=True) is None
    assert music_intents.resolve(text,preferred=True) is None


@pytest.mark.parametrize('text',PREVIOUS)
def test_transport_uses_one_shared_direction_grammar(text):
    request=media_manager.parse(text,music_context=True)
    assert request.action=='previous' and not request.query and request.scope=='player'
    assert music_intents.resolve(text,preferred=True).action=='previous'


@pytest.mark.parametrize('text',[
    'Включи песню «Предыдущая композиция»',
    'Включи песню «Программа для рисования»',
    'Поставь песню «Верни прошлую песню»',
    'Поставь «Программа для рисования»',
])
def test_explicit_titles_stay_search_data(text):
    request=media_manager.parse(text,music_context=True)
    assert request.action=='search_play' and request.query
    assert request.action not in {'previous','next'}


def latest_trace(app):
    return json.loads(next(r['details'] for r in reversed(app.state.store.list('actions',100)) if r['kind']=='command.trace'))


@pytest.mark.parametrize('enabled',[False,True])
def test_app_search_reaches_c7_only_on_real_inspection_miss(natural,monkeypatch,enabled):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    for item in apps:item.setdefault('source','fixture')
    app.state.store.patch_settings({'intent_gate':enabled,'semantic_commands':False})
    decisions=[]
    async def decide(*args,**kw):
        decisions.append(1);return '{"kind":"ambiguous"}'
    monkeypatch.setattr('core.providers.structured',decide)
    events=chat(client,APP_SEARCH[0])
    assert not sent and not writes and not special and not calls['opened'] and not calls['audio']
    assert 'pending_media' not in app.state.store.dialogue()
    assert len(decisions)==int(enabled)
    trace=latest_trace(app)
    assert trace['route']['tool'] in {'applications.search','conversation'}
    assert any(e.get('action',{}).get('status')=='needs_clarification' for e in events)


def test_existing_purpose_catalog_is_read_without_launch_or_model(natural,monkeypatch):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    app.state.store.patch_settings({'intent_gate':True})
    candidate={'name':'Krita','target':apps[0]['target'],'source':'fixture'}
    monkeypatch.setattr(app.state.applications,'purpose_matches',lambda purpose:[candidate] if purpose=='для рисования' else None)
    async def forbidden(*args,**kw):pytest.fail('Verified purpose read needs no classifier')
    monkeypatch.setattr('core.providers.structured',forbidden)
    events=chat(client,'Найди программу для рисования')
    assert latest_trace(app)['route']['tool']=='applications.search'
    assert any('Krita' in e.get('text','') for e in events)
    assert not any(k.startswith('pending_') for k in app.state.store.dialogue())
    assert not sent and not writes and not special and not calls['opened']


@pytest.mark.parametrize('text',PREVIOUS)
@pytest.mark.parametrize('source',['smtc:AIMP','auto'])
def test_previous_reaches_selected_executor_once_without_c7(natural,monkeypatch,text,source):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    app.state.store.patch_settings({'media_source':source,'intent_gate':True})
    async def forbidden(*args,**kwargs):pytest.fail('Known transport must not call C7')
    monkeypatch.setattr('core.providers.structured',forbidden)
    chat(client,text)
    if source=='smtc:AIMP':assert sent==[('smtc:AIMP','previous')] and not special
    else:assert [c.action for c in special]==['previous'] and not sent
    assert not writes and not any(calls.values())
    trace=latest_trace(app)
    assert trace['route']['tool']=='media.manager' and trace['route']['intent']=='previous'


@pytest.mark.parametrize('text',[
    'Не включай музыку','Не открывай Blender','Расскажи, как переключить песню',
    'Если откроешь браузер, закрой его','Включи песню и поставь на паузу',
    'Не поставь предшествующую композицию','Если понадобится, верни прошлую песню',
    'Он сказал: поставь предшествующую композицию','Поставь предшествующую композицию?',
    'Найди программу и включи музыку',
    'Подбери рисовалку и переключи композицию',
    'Пожалуйста, открой браузер и приглуши колонки',
    'Запусти редактор и ещё подбери песню',
])
def test_conflicting_language_never_dispatches(natural,text):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    chat(client,text)
    assert not sent and not writes and not special and not calls['opened'] and not calls['audio']
    assert not any(k.startswith('pending_') for k in app.state.store.dialogue())


@pytest.mark.parametrize('text,action,query',[
    ('Найди песню Fall Out Boy','search','Fall Out Boy'),
    ('Включи Noize MC Вояджер','search_play','Noize MC Вояджер'),
    ('Найди композицию Numb','search','Numb'),
    ('Включи мою волну','wave',''),
    ('Включи песню «Предыдущая композиция»','search_play','Предыдущая композиция'),
    ('Найди песню Blender','search','Blender'),
])
def test_explicit_music_never_becomes_app_open(natural,text,action,query):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    chat(client,text)
    assert [(c.action,c.query) for c in special]==[(action,query)]
    assert not calls['opened'] and not calls['audio'] and not sent and not writes


def test_previous_failure_cannot_be_reported_as_success(natural,monkeypatch):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    monkeypatch.setattr(app.state.music,'execute',lambda c,*args,**kw:{'confirmed':False,'text':'Переключение не подтверждено'})
    events=chat(client,PREVIOUS[4])
    assert any(e.get('action',{}).get('status')=='unconfirmed' for e in events)
    assert latest_trace(app)['route']['intent']=='previous'


@pytest.mark.parametrize('text,offer_open',[
    ('Подбери программу для рисования',True),
    ('Хочу что-нибудь для 3D-моделирования',True),
    ('Найди подходящую программу для пиксельного рисунка',False),
])
def test_app_miss_keeps_existing_verified_catalog_and_pending(natural,monkeypatch,text,offer_open):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    for item in apps:item.setdefault('source','fixture')
    label='Blender' if '3D' in text else 'Krita'
    exe=app.state.store.root/(label+'.exe');exe.touch()
    app.state.store.add_alias(label,'app',str(exe))
    app.state.store.patch_settings({'intent_gate':True,'semantic_commands':False})
    invoked=[]
    async def choose(cfg,messages,schema,**kw):
        invoked.append(1);catalog=json.loads(messages[0]['content'].split('Каталог: ')[1])
        key=next(x['id'] for x in catalog if x['name'].casefold()==label.casefold())
        return json.dumps({'kind':'indirect','tool':'applications.search','choices':[key]})
    monkeypatch.setattr('core.providers.structured',choose)
    chat(client,text)
    assert len(invoked)==1 and not special and not sent and not writes and not calls['opened']
    pending=app.state.store.dialogue().get('pending_open')
    if offer_open:
        assert pending['intent_gate'] and pending['choices'][0]['target']==str(exe)
    else:
        # C7's existing authority check treats a read-only find differently
        # from a request to open. Preserve this conservative clarification.
        assert pending is None and latest_trace(app)['intent_gate']['reason']=='insufficient_authority'


@pytest.mark.parametrize('enabled',[False,True])
def test_known_app_open_is_not_captured_by_preferred_player(natural,enabled):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    exe=app.state.store.root/'Blender.exe';exe.touch()
    app.state.store.add_alias('Blender','app',str(exe))
    app.state.store.patch_settings({'intent_gate':enabled})
    chat(client,'Открой Blender')
    assert len(calls['opened'])==1 and calls['opened'][0].target==str(exe)
    assert not calls['model'] and not special and not sent and not writes


@pytest.mark.parametrize('text,action',[
    ('Следующий трек','next'),('Продолжи музыку','play'),('Поставь на паузу','pause'),
])
def test_existing_transport_still_uses_media_manager(natural,text,action):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    app.state.store.patch_settings({'intent_gate':True,'media_source':'smtc:AIMP'})
    rows[0]['state']='Paused' if action=='play' else 'Playing'
    chat(client,text)
    assert sent==[('smtc:AIMP',action)] and not special and not writes and not any(calls.values())
    assert latest_trace(app)['route']['tool']=='media.manager'


def test_previous_without_an_available_source_never_searches(natural,monkeypatch):
    client,app,rows,mixer,sent,writes,special,apps,calls=natural
    rows.clear();app.state.store.patch_settings({'music_player':'auto','media_source':'auto'})
    events=chat(client,'Поставь предшествующую композицию')
    assert not sent and not writes and not special and not calls['opened']
    assert latest_trace(app)['route']['intent']=='previous'
    assert not any(e.get('action',{}).get('status')=='confirmed' for e in events)
