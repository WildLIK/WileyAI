"""Stateful owner sequences: real routing/manager/connect with fake OS and CDP."""
from contextlib import contextmanager
import json
from pathlib import Path
import time
from types import SimpleNamespace

import psutil
import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.yandex_music import MusicError
from tests.test_music_natural_c3_c4 import chat


class Process:
    def __init__(self, world, pid, port):
        self.world, self.pid, self.port = world, pid, port
        self.info = {'pid':pid,'exe':str(world.exe)}
    def exe(self): return str(self.world.exe)
    def create_time(self): return self.pid + .25
    def cmdline(self): return [str(self.world.exe), *([f'--remote-debugging-port={self.port}'] if self.port else [])]
    def children(self, recursive=False): return []
    def terminate(self): self.world.terminated.append(self.pid); self.world.processes.pop(self.pid,None)


class World:
    def __init__(self, exe):
        self.exe=exe; self.processes={}; self.started=[]; self.terminated=[]
        self.state={'available':True,'id':'1','title':'Numb','artists':'Linkin Park','playing':False,'position':0}
        self.active=None; self.selected=None; self.calls=[]; self.pointers=0; self.loss=0; self.llm=0
        self.rows=[{'id':'2','title':'Numb','artists':'Linkin Park'}, {'id':'3','title':'Numb','artists':'U2'}]
    def add(self,pid,port):
        p=Process(self,pid,port);self.processes[pid]=p;return p
    def start(self,exe,port):
        assert Path(exe)==self.exe
        self.started.append(port);self.add(100+len(self.started),port);self.active=None
    def action(self,kind,**args):
        self.calls.append((kind,args))
        if kind=='status':
            if self.loss: self.loss-=1;raise MusicError('cdp_unavailable','Связь с Яндекс Музыкой потеряна')
            if self.state['playing']:self.state['position']+=.3
            return dict(self.state)
        if kind=='wave_target':self.selected={'id':'42','title':'Моя волна','artists':'Исполнитель'};return {'x':20,'y':20}
        if kind=='next':self.state.update(id=str(int(self.state['id'])+1),position=0,playing=True);return {'dispatched':True}
        if kind=='search':self.active=(args['query'],args['search_id']);return {'searching':True}
        if kind in {'results','select_target'}:
            if self.active is None:raise MusicError('search_session_missing','Поисковый запрос изменился или устарел. Повторите поиск песни','search')
            if self.active!=(args['query'],args['search_id']):raise MusicError('search_id_changed','Поисковый запрос изменился или устарел. Повторите поиск песни','search')
            if kind=='results':return {'ready':True,'rows':self.rows}
            self.selected=next(r for r in self.rows if r['id']==args['id']);return {'x':20,'y':20}
        return {'dispatched':True}
    def pointer(self,*coords):self.pointers+=1;self.state.update(**self.selected,playing=True,position=0)
    def hover(self,*coords):pass


@pytest.fixture
def scene(tmp_path,monkeypatch):
    app=create_app(tmp_path,'voice365-tests-0123456789abcdef')
    exe=tmp_path/'YandexMusic.exe';exe.touch()
    w=World(exe);w.add(10,32123)
    app.state.store.patch_settings({'music_player':'yandex','allow_audio_control':True,'allow_app_open':True,'yandex_auto_connect':True,'voice_diagnostics':True})
    app.state.store.add_alias('Яндекс Музыка','app',str(exe))
    player=app.state.music
    def process(pid):
        if pid not in w.processes:raise psutil.NoSuchProcess(pid)
        return w.processes[pid]
    monkeypatch.setattr('core.yandex_music.psutil.Process',process)
    monkeypatch.setattr('core.yandex_music.running',lambda p:list(w.processes.values()))
    monkeypatch.setattr('core.yandex_music.start_player',w.start)
    monkeypatch.setattr('core.yandex_music.time.sleep',lambda _:None)
    @contextmanager
    def wait(processes):yield lambda:True
    monkeypatch.setattr('core.yandex_music.exit_waiter',wait)
    def write(p):player.path.write_text(json.dumps({'pid':p.pid,'created':p.create_time(),'port':p.port,'exe':str(exe)}))
    write(w.processes[10])
    @contextmanager
    def descriptor_renderer(data):
        p=process(data['pid'])
        assert p.create_time()==data['created'] and p.port==data['port'] and p.exe()==data['exe']
        if not p.port:raise MusicError('no_cdp','Плеер открыт без CDP')
        yield w
    @contextmanager
    def renderer():
        with descriptor_renderer(player.checked_descriptor()) as page:yield page
    monkeypatch.setattr(player,'renderer',renderer)
    monkeypatch.setattr(player,'_renderer_for_descriptor',descriptor_renderer,raising=False)
    monkeypatch.setattr('core.commands.execute',lambda *a,**k:pytest.fail('No ordinary process launch'))
    async def no_model(*args,**kwargs):
        w.llm+=1
        yield 'Проверка Windows в этом ответе не выполнялась'
    monkeypatch.setattr('core.providers.chat',no_model)
    monkeypatch.setattr('core.windows_media.sessions',lambda:[])
    with TestClient(app,headers={'Authorization':'Bearer voice365-tests-0123456789abcdef'}) as client:
        yield client,app,w,write


def outcome(events):return next((e['action'] for e in events if e['type']=='speech_result'),{'status':'fallback','details':{},'display':''})


def test_A_stale_open_restart_confirmation_checks_new_connection(scene):
    client,app,w,write=scene
    w.processes.clear();w.add(20,None)
    events=chat(client,'Открой Яндекс Музыку')
    assert app.state.store.dialogue()['pending_media']['restart'] and not w.started
    chat(client,'да')
    assert len(w.started)==1 and w.terminated==[20] and not w.llm
    assert app.state.music.status()['connected']
    chat(client,'да')
    assert len(w.started)==1 and w.terminated==[20] and not w.llm


def test_B_artist_search_reports_cdp_failure_not_artist_absence(scene):
    client,app,w,write=scene
    w.processes[10].port=None
    events=chat(client,'Найди Noize MC')
    display=outcome(events)['display']
    assert ('CDP' in display or 'перезапуск' in display) and 'нет в базе' not in display and 'песню не' not in display
    assert not any(kind=='search' for kind,args in w.calls)


def test_C_wave_and_agreement_plus_next_are_real_media_steps(scene):
    client,app,w,write=scene
    assert outcome(chat(client,'Запусти мою волну'))['status']=='confirmed'
    assert outcome(chat(client,'Следующая песня'))['status']=='confirmed'
    assert outcome(chat(client,'Да, включи следующую песню'))['status']=='confirmed'
    assert sum(kind=='next' for kind,args in w.calls)==2 and w.pointers==1


def test_D_explicit_restart_has_pending_and_only_yes_restarts(scene):
    client,app,w,write=scene
    chat(client,'Перезапусти Яндекс Музыку')
    assert not w.started and app.state.store.dialogue()['pending_media']['restart']
    chat(client,'да')
    assert len(w.started)==1 and w.terminated==[10] and app.state.music.status()['connected']
    chat(client,'да')
    assert len(w.started)==1


def test_E_connection_check_uses_fresh_topic_and_actual_status(scene):
    client,app,w,write=scene
    chat(client,'Запусти мою волну')
    w.loss=1
    events=chat(client,'Проверь подключение')
    assert outcome(events)['details']['diagnostics']['reason'] in {'connected','cdp_unavailable'}
    assert w.pointers==1 and not w.started


def test_F_search_selection_binds_current_query_and_id(scene):
    client,app,w,write=scene
    events=chat(client,'Найди песню Numb')
    assert outcome(events)['status']=='needs_clarification' and w.pointers==0
    chat(client,'Включи вторую')
    assert w.state['id']=='3' and w.pointers==1
    chat(client,'Найди песню Numb')
    w.active=('other query','b'*32)
    result=outcome(chat(client,'Включи вторую'))
    assert result['status']!='confirmed' and result['details']['diagnostics']['reason']=='search_id_changed' and w.pointers==1


def test_owned_new_process_is_recovered_without_launch_or_replay(scene):
    client,app,w,write=scene
    chat(client,'Запусти мою волну')
    w.processes.clear();w.add(30,32124)
    result=outcome(chat(client,'Следующая песня'))
    assert result['status']=='confirmed' and app.state.music.checked_descriptor()['pid']==30
    assert not w.started and not w.terminated and sum(kind=='next' for kind,args in w.calls)==1


@pytest.mark.parametrize('text',['Не включай следующую песню','Да, не включай следующую песню','Да, включи следующую песню и перезапусти Яндекс Музыку','«Перезапусти Яндекс Музыку»','Если перезапусти Яндекс Музыку','Запусти мою волну и перезапусти Яндекс Музыку'])
def test_negation_mentions_and_multiple_actions_never_dispatch(scene,text):
    client,app,w,write=scene
    # Scripted conversation is allowed for mentions but has no executor.
    async def conversation(*a,**k):yield 'Действие не выполнялось'
    app.state.store.patch_settings({'semantic_commands':False})
    from unittest.mock import patch
    with patch('core.providers.chat',conversation):chat(client,text)
    assert not w.started and not w.terminated and w.pointers==0


def test_search_unknown_artist_is_factual_without_random_play(scene):
    client,app,w,write=scene
    w.rows=[{'id':'2','title':'Du Hast','artists':'Rammstein'}]
    result=outcome(chat(client,'Найди Rammstein'))
    assert result['status']=='needs_clarification' and w.pointers==0 and not w.llm
    assert any(kind=='search' and args['query']=='Rammstein' for kind,args in w.calls)


def test_no_results_is_not_connection_failure_or_catalogue_absence(scene):
    client,app,w,write=scene;w.rows=[]
    result=outcome(chat(client,'Найди Noize MC'))
    assert result['details']['diagnostics']['reason']=='search_no_results'
    assert 'Связь' not in result['display'] and 'отсутствие исполнителя' in result['display']
    assert w.pointers==0 and not w.llm


def test_check_after_unrelated_topic_does_not_guess_or_inspect_windows(scene):
    client,app,w,write=scene
    chat(client,'Запусти мою волну')
    async def talk(*a,**k):yield 'Обычный разговор'
    from unittest.mock import patch
    with patch('core.providers.chat',talk):chat(client,'Расскажи о дождливом дне')
    before=len(w.calls)
    result=outcome(chat(client,'Проверь подключение'))
    assert result['status']=='needs_clarification' and len(w.calls)==before


def test_connection_context_expires_without_using_saved_preference(scene):
    client,app,w,write=scene
    app.state.store.save_dialogue({'music_context':{'target':'Яндекс Музыка','created':time.time()-301}})
    result=outcome(chat(client,'Проверь подключение'))
    assert result['status']=='needs_clarification' and not w.calls


def test_restart_confirmation_expires_or_loses_permission(scene):
    client,app,w,write=scene
    chat(client,'Перезапусти Яндекс Музыку')
    state=app.state.store.dialogue();state['pending_media']['created']=time.time()-301;app.state.store.save_dialogue(state)
    assert 'устарело' in outcome(chat(client,'да'))['display']
    chat(client,'Перезапусти Яндекс Музыку')
    app.state.store.patch_settings({'allow_app_open':False})
    result=outcome(chat(client,'да'))
    assert result['details']['diagnostics']['reason']=='denied' and not w.started and not w.terminated


def test_pending_and_topic_are_not_reused_in_another_chat(scene):
    client,app,w,write=scene
    chat(client,'Перезапусти Яндекс Музыку')
    response=client.post('/conversations',json={'title':'Other'});assert response.status_code==200,response.text
    other=response.json()['id']
    chat(client,'да',conversation_id=other)
    assert not w.started and not w.terminated
    assert app.state.store.dialogue()['pending_media']['restart']


def test_model_offer_is_not_a_phantom_pending_and_yes_cannot_execute_it(scene):
    client,app,w,write=scene
    chat(client,'Запусти мою волну')
    model_calls=[]
    async def offer(*a,**k):model_calls.append(1);yield 'Хотите, чтобы я выполнила поиск?'
    from unittest.mock import patch
    with patch('core.providers.chat',offer):
        events=chat(client,'Давай обсудим музыку')
        assert not any('Хотите' in e.get('text','') for e in events)
        assert 'pending_media' not in app.state.store.dialogue()
        assert outcome(chat(client,'да'))['status']=='no_pending'
    assert len(model_calls)==1 and w.pointers==1 and not w.started


def test_old_model_offer_without_pending_gets_local_explanation(scene):
    client,app,w,write=scene
    app.state.store.add_message('user','Поиск музыки')
    app.state.store.add_message('assistant','Хотите, чтобы я выполнила поиск?')
    assert outcome(chat(client,'да'))['status']=='no_pending'
    assert not w.llm and not w.calls and not w.started


def test_verification_loss_never_repeats_dispatched_wave(scene):
    client,app,w,write=scene
    old=w.pointer
    def pointer(*args):old(*args);w.loss=1
    w.pointer=pointer
    result=outcome(chat(client,'Запусти мою волну'))
    assert result['status']=='unconfirmed' and result['details']['diagnostics']['reason']=='verification_unavailable'
    assert result['details']['diagnostics']['dispatched'] and w.pointers==1 and not w.started


def test_cancellation_before_restart_and_pid_reuse_fail_closed(scene):
    client,app,w,write=scene
    import threading
    cancel=threading.Event();cancel.set()
    with pytest.raises(MusicError,match='отменено'):app.state.music.connect_with_cancel(True,cancel)
    assert not w.terminated and not w.started
    snapshot=Process(w,35,None);snapshot.create_time=lambda:1
    replacement=w.add(35,None);replacement.create_time=lambda:2
    w.processes[10].children=lambda **kw:[snapshot]
    with pytest.raises(MusicError,match='изменился'):app.state.music.connect(True)
    assert not w.terminated and not w.started


def test_restart_never_terminates_foreign_executable_child(scene):
    client,app,w,write=scene
    child=w.add(35,None);child.exe=lambda:str(w.exe.with_name('other.exe'))
    w.processes[10].children=lambda **kw:[child]
    # The independent root list contains only Yandex browser roots.
    from unittest.mock import patch
    with patch('core.yandex_music.running',lambda p:[r for r in w.processes.values() if r.exe()==str(w.exe)]):app.state.music.connect(True)
    assert w.terminated==[10] and 35 in w.processes


@pytest.mark.parametrize('foreign',[False,True])
def test_recovery_validates_actual_socket_owner_before_saving(scene,monkeypatch,foreign):
    from core.yandex_music import YandexMusic
    import httpx
    client,app,w,write=scene;player=app.state.music
    player.path.write_text(json.dumps({'pid':999,'created':1,'exe':str(w.exe),'port':39999}))
    monkeypatch.setattr(player,'_renderer_for_descriptor',YandexMusic._renderer_for_descriptor.__get__(player))
    probed=[]
    def listeners(port):
        probed.append(port)
        return [SimpleNamespace(pid=9999 if foreign else 10,laddr=SimpleNamespace(ip='127.0.0.1',port=port))]
    monkeypatch.setattr(player,'listeners',listeners)
    class Client:
        def __init__(self,**kw):assert kw=={'trust_env':False,'follow_redirects':False,'timeout':3}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):return httpx.Response(200,json=[{'type':'page','url':'music-application://desktop/','webSocketDebuggerUrl':'ws://127.0.0.1:32123/devtools/page/fake'}],request=httpx.Request('GET',url))
    monkeypatch.setattr('core.yandex_music.httpx.Client',Client)
    class Socket:
        def send(self,text):self.id=json.loads(text)['id']
        def recv(self,**kw):return json.dumps({'id':self.id,'result':{'result':{'value':dict(w.state)}}})
    @contextmanager
    def socket(*a,**k):yield Socket()
    monkeypatch.setattr('websockets.sync.client.connect',socket)
    result=player.recover()
    assert result['connected'] is (not foreign) and probed==[32123]
    assert not w.started and not w.terminated
    if foreign:assert result['diagnostics']['reason']=='identity_mismatch' and not player.path.exists()
    else:assert player.checked_descriptor()['pid']==10


@pytest.mark.parametrize('reason',['search_session_missing','search_query_changed','search_id_changed','search_input_changed','search_expired','search_not_ready','search_results_changed'])
def test_renderer_preserves_search_failure_reason_instead_of_connection_label(reason):
    from core.yandex_music import Renderer,failure
    class Socket:
        def send(self,text):self.id=json.loads(text)['id']
        def recv(self,**kw):return json.dumps({'id':self.id,'result':{'exceptionDetails':{'exception':{'description':'Error: WILEY_MUSIC/'+reason+'/Поиск изменился'}}}})
    with pytest.raises(MusicError) as error:Renderer(Socket()).action('results',query='Numb',search_id='a'*32)
    assert failure(error.value)['diagnostics']['reason']==reason and error.value.phase=='search'


def test_diagnostics_are_bounded_and_runtime_snapshot_is_stable(scene):
    client,app,w,write=scene
    runtime=client.get('/health').json()['runtime']
    assert runtime['revision']=='voice365' and client.get('/health').json()['runtime']==runtime
    events=chat(client,'Да, включи следующую песню')
    routes=[json.loads(r['details'])['route'] for r in app.state.store.list('actions',100) if r['kind']=='command.trace']
    assert routes[-1]['tool']=='media.manager' and routes[-1]['result']=='confirmed'
    assert 'original' not in routes[-1] and 'normalized' not in routes[-1]
    assert any(e['type']=='command_route' for e in events)


@pytest.mark.parametrize('claim',['Я не могу воспроизводить музыку напрямую','Я могу открыть браузер','Я не запускала приложение','В базе нет точного совпадения','Хотите, чтобы я выполнила поиск?'])
def test_model_cannot_replace_unexecuted_music_tool_with_claims(claim):
    from core.persona import without_unexecuted_claims
    guarded=without_unexecuted_claims(claim,context='music')
    assert guarded!=claim and ('не вызывался' in guarded or 'не подготовлено' in guarded)
    assert without_unexecuted_claims('Мне нравится эта песня.',context='music')=='Мне нравится эта песня.'


def test_connection_question_is_read_only_and_uses_fresh_topic(scene):
    client,app,w,write=scene
    chat(client,'Проверь подключение к Яндекс Музыке')
    result=outcome(chat(client,'Что случилось с подключением?'))
    assert result['details']['diagnostics']['reason']=='connected'
    assert not w.started and not w.terminated and not w.pointers and not w.llm


def test_asr_search_text_reaches_existing_entity_resolver_unchanged(scene):
    client,app,w,write=scene
    chat(client,'Найди Rammstein Tuhast Me')
    searches=[args['query'] for kind,args in w.calls if kind=='search']
    assert searches and searches[0]=='Rammstein Tuhast Me' and len(searches)<=3
    assert not w.pointers and not w.llm


def test_session_end_retires_pending_and_cannot_restart_on_yes(scene):
    client,app,w,write=scene
    chat(client,'Перезапусти Яндекс Музыку')
    assert client.post('/voice/conversation/end',json={}).status_code==200
    chat(client,'да')
    assert 'pending_media' not in app.state.store.dialogue()
    assert not w.started and not w.terminated


@pytest.mark.parametrize('text',['Перезапусти Яндекс Музыку','Найди песню Numb'])
def test_command_endpoint_does_not_offer_a_confirmation_without_pending(scene,text):
    client,app,w,write=scene
    response=client.post('/commands',json={'text':text,'dry_run':False})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['pending']=='not_created' and 'в чате' in result['text'] and 'Ответьте' not in result['text']
    assert 'pending_media' not in app.state.store.dialogue()
    assert not w.started and not w.terminated and not w.pointers
