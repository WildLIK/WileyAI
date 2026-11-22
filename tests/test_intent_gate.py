"""C7 integration: real API/Pending/manager with fake OS, CDP and model only."""
import asyncio
import json
import time
from contextlib import contextmanager

import pytest

from core import intent_gate, providers, windows_audio
from core.config import Settings
from tests.test_voice365_e2e import scene, chat, outcome
from tests.test_voice365a import AudioDevice


@pytest.fixture
def gate(scene,monkeypatch):
    client,app,w,write=scene
    app.state.store.patch_settings({'intent_gate':True,'semantic_commands':False})
    device=AudioDevice();calls=[]
    @contextmanager
    def endpoint():yield device
    monkeypatch.setattr(windows_audio,'endpoint',endpoint)
    def model(payload):
        async def decide(settings,messages,schema,**kwargs):
            calls.append({'messages':messages,'schema':schema,'kwargs':kwargs})
            return json.dumps(payload) if not isinstance(payload,str) else payload
        monkeypatch.setattr(providers,'structured',decide)
    model({'kind':'ambiguous'})
    return client,app,w,device,calls,model


def trace(app):return json.loads(next(r['details'] for r in reversed(app.state.store.list('actions',100)) if r['kind']=='command.trace'))


def test_defaults_off_and_disabled_mode_does_not_classify(gate):
    client,app,w,d,calls,model=gate
    assert Settings().intent_gate is False
    app.state.store.patch_settings({'intent_gate':False})
    chat(client,'Мне хотелось бы приглушить общий уровень звука')
    assert not calls and not d.calls and not app.state.store.dialogue().get('pending_audio')


@pytest.mark.parametrize('text',['Убавь громкость','Следующий трек','Найди песню Numb','Запусти мою волну','Поставь музыку на паузу','Продолжи музыку'])
def test_fast_paths_never_call_gate(gate,text):
    client,app,w,d,calls,model=gate
    chat(client,text)
    assert not calls and trace(app)['intent_gate']['fast_path']


def test_volume_uses_existing_pending_once_and_verified_result(gate):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'system','value':-10})
    assert outcome(chat(client,'Можно слегка приглушить общий уровень на ПК'))['status']=='clarification'
    pending=app.state.store.dialogue()['pending_audio']
    assert pending['intent_gate'] and pending['semantic'] and d.volume==40 and not d.calls
    assert calls[0]['kwargs']['max_tokens']==192 and calls[0]['kwargs']['max_chars']==1800
    assert outcome(chat(client,'да'))['status']=='confirmed' and d.volume==30
    chat(client,'да')
    assert d.calls==[30] and len(calls)==1


def test_gate_context_comes_from_confirmed_fast_path_and_needs_confirmation(gate):
    client,app,w,d,calls,model=gate
    chat(client,'Убавь громкость')
    assert app.state.store.dialogue()[intent_gate.CONTEXT_KEY]['value']==-10
    model({'kind':'context','tool':'audio.volume','source':'system','value':-5})
    chat(client,'Ещё совсем капельку в ту же сторону')
    assert d.volume==30 and len(calls)==1
    chat(client,'да')
    assert d.volume==25 and d.calls==[30,25]


@pytest.mark.parametrize('condition',['expired','different_chat','ended','wrong_direction'])
def test_context_cannot_be_reused_unsafely(gate,condition):
    client,app,w,d,calls,model=gate
    chat(client,'Убавь громкость')
    if condition=='expired':
        state=app.state.store.dialogue();state[intent_gate.CONTEXT_KEY]['created']-=121;app.state.store.save_dialogue(state)
    if condition=='ended':client.post('/voice/conversation/end',json={})
    fields={}
    if condition=='different_chat':fields['conversation_id']=client.post('/conversations',json={'title':'Other'}).json()['id']
    model({'kind':'context','tool':'audio.volume','source':'system','value':5 if condition=='wrong_direction' else -5})
    response=outcome(chat(client,'Ещё маленькую ступень',**fields))
    assert response['status']=='needs_clarification' and d.calls==[30]
    assert len(calls)==(1 if condition=='wrong_direction' else 0)


@pytest.mark.parametrize('text',[
    'Я не давал согласия запускать редактор','Если захочу, приглуши аудио','Я хотел вернуться к музыке, но передумал',
    'Он сказал: запусти Blender','Почему эта мелодия так громко звучит','Как включить Bluetooth?',
    'Открой браузер и включи музыку','Не надо ничего делать',
])
def test_protected_requests_cannot_be_reinterpreted(gate,text):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'system','value':10})
    chat(client,text)
    assert not calls and not d.calls and not w.pointers and not w.started
    assert not any(k.startswith('pending_') for k in app.state.store.dialogue())


@pytest.mark.parametrize('payload',[
    '{','{"kind":"action","tool":"cmd"}',
    {'kind':'conversation','tool':'audio.volume','source':'system','value':-10},
    {'kind':'action','tool':'windows.app.open','choices':['unknown']},
    {'kind':'action','tool':'audio.volume','source':'system','value':-20},
    {'kind':'action','tool':'audio.volume','source':'system','value':True},
    {'kind':'action','tool':'media.manager','source':'music','action':'search','query':'hallucinated title'},
    '{"kind":"action","kind":"conversation"}',
])
def test_invalid_model_outputs_fail_closed(gate,payload):
    client,app,w,d,calls,model=gate;model(payload)
    assert outcome(chat(client,'Подумай, какой звуковой инструмент мне сейчас нужен'))['status']=='needs_clarification'
    assert not d.calls and not w.calls and not w.started
    assert trace(app)['intent_gate']['reason']=='invalid_decision'


def test_music_source_cannot_be_changed_to_windows(gate):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'system','value':-10})
    chat(client,'Можно аккуратно приглушить именно музыку плеера')
    assert not d.calls and not app.state.store.dialogue().get('pending_audio')


@pytest.mark.parametrize('change',['disable','permission','source'])
def test_pending_rechecks_feature_permissions_and_source(gate,change):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'system','value':-10})
    chat(client,'Можно чуть ослабить системное аудио')
    app.state.store.patch_settings({'intent_gate':False,'semantic_commands':True} if change=='disable' else {'allow_audio_control':False} if change=='permission' else {'media_source':'smtc:other'})
    chat(client,'да')
    assert not d.calls and len(calls)==1


def test_search_uses_real_manager_and_existing_selection_pending(gate):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'media.manager','source':'music','action':'search','query':'Numb'})
    chat(client,'Помоги отыскать у проигрывателя Numb')
    assert app.state.store.dialogue()['pending_media']['intent_gate'] and w.pointers==0
    assert outcome(chat(client,'Первая'))['status']=='confirmed' and w.pointers==1 and len(calls)==1


def test_application_ids_are_catalog_bound_and_require_real_confirmation(gate,monkeypatch):
    from core.launch_verification import ExecutionText
    client,app,w,d,calls,model=gate
    exe=app.state.store.root/'Krita.exe';exe.touch();app.state.store.add_alias('Krita','app',str(exe))
    opened=[]
    monkeypatch.setattr('core.commands.execute',lambda command,**kw:opened.append(command) or ExecutionText('Процесс запущен',{'status':'process_started'}))
    async def choose(cfg,messages,schema,**kw):
        calls.append(1);catalog=json.loads(messages[0]['content'].split('Каталог: ')[1])
        key=next(r['id'] for r in catalog if r['name'].casefold()=='krita')
        return json.dumps({'kind':'indirect','tool':'applications.search','choices':[key]})
    monkeypatch.setattr(providers,'structured',choose)
    chat(client,'Хочется набросать несколько линий на цифровом холсте')
    assert not opened and app.state.store.dialogue()['pending_open']['intent_gate']
    chat(client,'да');chat(client,'да')
    assert len(opened)==1 and len(calls)==1


@pytest.mark.parametrize('failure',['timeout','unavailable','late_cancel'])
def test_model_failures_do_not_execute_or_create_pending(gate,monkeypatch,failure):
    client,app,w,d,calls,model=gate
    async def slow(*a,**kw):
        calls.append(1)
        if failure=='unavailable':raise ConnectionError('unavailable')
        if failure=='late_cancel':
            app.state.store.patch_settings({'intent_gate':False})
            return json.dumps({'kind':'action','tool':'audio.volume','source':'system','value':-10})
        await asyncio.sleep(.1)
    monkeypatch.setattr(providers,'structured',slow)
    monkeypatch.setattr(intent_gate,'TIMEOUT',.02)
    chat(client,'Можно аккуратно снизить общий уровень аудио')
    assert not d.calls and not any(k.startswith('pending_') for k in app.state.store.dialogue())


def test_fixture_has_frozen_independent_tuning_and_holdout():
    from pathlib import Path
    import hashlib
    folder=Path('tests/fixtures/intent-gate');seal=json.loads((folder/'seal.json').read_text())
    assert hashlib.sha256((folder/'c7.json').read_bytes()).hexdigest()==seal['c7.json']
    cases=json.loads((folder/'c7.json').read_text(encoding='utf-8'))['cases']
    assert len(cases)==150 and len({r['text'] for r in cases})==150
    assert sum(r['expected_effect']=='none' for r in cases)>=75
    assert {r['split'] for r in cases}=={'tuning','holdout'}


@pytest.mark.parametrize('stop',['request','voice_end'])
def test_late_model_after_cancellation_cannot_create_pending(gate,monkeypatch,stop):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    client,app,w,d,calls,model=gate;started=threading.Event()
    async def stubborn(*a,**kw):
        calls.append(1);started.set()
        try:await asyncio.sleep(30)
        except asyncio.CancelledError:pass
        return json.dumps({'kind':'action','tool':'audio.volume','source':'system','value':-10})
    monkeypatch.setattr(providers,'structured',stubborn)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(client.post,'/chat',json={'text':'Можно слегка приглушить общее аудио','mode':'conversation','request_id':'c7-cancel'})
        assert started.wait(5)
        response=client.post('/chat/stop',json={'request_id':'c7-cancel'}) if stop=='request' else client.post('/voice/conversation/end',json={})
        assert response.status_code==200
        future.result(timeout=6)
    assert not d.calls and not any(k.startswith('pending_') for k in app.state.store.dialogue())
    chat(client,'да');assert len(calls)==1 and not d.calls


def test_unknown_intent_cannot_turn_a_remark_into_a_proposal(gate):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'music','value':-10})
    result=outcome(chat(client,'Этот музыкальный фон сегодня очень шумный'))
    assert result['status']=='needs_clarification' and not app.state.store.dialogue().get('pending_audio')


def test_feature_disable_retires_only_gate_owned_proposals(gate):
    client,app,w,d,calls,model=gate
    model({'kind':'action','tool':'audio.volume','source':'system','value':-10})
    chat(client,'Прошу слегка ослабить общий звук')
    cfg=client.get('/settings').json();cfg['intent_gate']=False
    assert client.put('/settings',json=cfg).status_code==200
    assert 'pending_audio' not in app.state.store.dialogue()
    app.state.store.patch_settings({'intent_gate':True})
    chat(client,'да');assert not d.calls


def test_existing_provider_bounds_tokens_schema_thinking_and_reports_load(monkeypatch):
    import httpx
    requests=[];timing={}
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,text=json.dumps({'message':{'content':'{"kind":"conversation"}'},'done':True,'load_duration':42,'eval_count':8})+'\n')
    monkeypatch.setattr(providers,'client',lambda cfg:httpx.AsyncClient(base_url=cfg.base_url+'/',transport=httpx.MockTransport(respond)))
    output=asyncio.run(providers.structured(Settings(),[{'role':'user','content':'fixture'}],{'type':'object'},max_tokens=192,diagnostics=timing))
    assert json.loads(output)['kind']=='conversation'
    assert requests[0]['options']['num_predict']==192 and requests[0]['think'] is False and requests[0]['keep_alive']=='5m'
    assert requests[0]['format']=={'type':'object'} and timing=={'load_duration':42,'eval_count':8}


@pytest.mark.parametrize('payload',[
    {'kind':'context','tool':'audio.playback','source':'system','action':'pause'},
    {'kind':'context','tool':'applications.list','source':'system'},
])
def test_context_cannot_change_the_previous_action(gate,payload):
    client,app,w,d,calls,model=gate
    chat(client,'Убавь громкость');model(payload)
    assert outcome(chat(client,'Ещё совсем капельку в ту же сторону'))['status']=='needs_clarification'
    assert len(calls)==1
    assert d.calls==[30] and not app.state.store.dialogue().get('pending_audio')
    assert trace(app)['intent_gate']['reason']=='invalid_decision'


def test_benchmark_network_exception_is_exact_loopback_inference_only():
    import httpx
    from scripts.semantic_test_safety import isolated_boundaries
    async def exercise():
        seen=[]
        async def respond(request):
            seen.append(str(request.url));return httpx.Response(200,json={'ok':True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            with isolated_boundaries(local_model_url='http://127.0.0.1:17434') as blocked:
                assert (await http.post('http://127.0.0.1:17434/api/chat')).status_code==200
                for method,url in [('GET','http://127.0.0.1:17434/api/chat'),('POST','http://127.0.0.1:17434/api/pull'),('POST','http://127.0.0.1:11434/api/chat'),('POST','https://example.com/api/chat'),('POST','http://127.0.0.1:17434/api/chat?x=1')]:
                    with pytest.raises(RuntimeError):await http.request(method,url)
                assert len(blocked)==5
        assert seen==['http://127.0.0.1:17434/api/chat']
    asyncio.run(exercise())


@pytest.mark.parametrize('legacy_enabled',[False,True])
def test_unknown_open_uses_gate_without_legacy_classifier(gate,monkeypatch,legacy_enabled):
    client,app,w,d,calls,model=gate
    app.state.store.patch_settings({'command_understanding':legacy_enabled})
    from core import intents
    async def unexpected(*args,**kwargs):pytest.fail('A gate miss must not use the legacy LLM')
    monkeypatch.setattr(intents,'propose',unexpected)
    model({'kind':'ambiguous'})
    chat(client,'Открой средство для моей необычной работы')
    assert len(calls)==1 and not w.started
    assert trace(app)['intent_gate']['called']
