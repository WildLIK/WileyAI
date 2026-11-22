"""Owner selection/volume regressions; fake CDP and Windows Audio only."""
from contextlib import contextmanager

import pytest

from core import media_manager, windows_audio
from core.action_response import audio_result
from core.device_audio import AudioAction, AudioTools
from tests.test_voice365_e2e import scene, chat, outcome


def songs(w):
    w.rows=[{'id':'41','title':'7 Minutes In Heaven (Atavan Halen)','artists':'Fall Out Boy'},
            {'id':'42','title':"This Ain't a Scene, It's an Arms Race (Live)",'artists':'Fall Out Boy'}]
    w.state.update(id='1',title='Into My Hands',artists='Final Thought',playing=False)


def test_A_nominative_first_executes_exact_candidate_once(scene):
    client,app,w,write=scene;songs(w)
    chat(client,'Найди мне песню Fall Out Boy')
    result=outcome(chat(client,'Первая'))
    assert result['status']=='confirmed' and w.state['id']=='41' and w.pointers==1 and not w.llm
    assert result['details']['selected']==w.rows[0]
    assert result['details']['selection_index']==1 and result['details']['verification']['reason']=='confirmed'
    chat(client,'Первая')
    assert w.pointers==1 and not w.llm


@pytest.mark.parametrize('phrase',['Найди мне песню Fall Out Boy','Найди песню Fall Out Boy','Поищи у меня Fall Out Boy','Найди трек Fall Out Boy','Поставь мне Fall Out Boy','Найди в Яндекс Музыке Fall Out Boy'])
def test_E_search_request_wrappers_are_not_query_data(scene,phrase):
    client,app,w,write=scene;songs(w)
    chat(client,phrase)
    assert next(args['query'] for kind,args in w.calls if kind=='search')=='Fall Out Boy'
    assert any(m['content']==phrase for m in app.state.store.list('messages',10))


@pytest.mark.parametrize('defect',['old_paused','old_playing','wrong_metadata','no_progress'])
def test_B_selected_song_requires_exact_playback_readback(scene,defect):
    client,app,w,write=scene;songs(w)
    chat(client,'Найди песню Fall Out Boy')
    pointer=w.pointer
    def click(*args):
        if defect.startswith('old_'):
            w.pointers+=1;w.state['playing']=defect=='old_playing'
        else:
            pointer(*args)
            if defect=='wrong_metadata':w.state['title']='Other song'
    w.pointer=click
    if defect=='no_progress':
        action=w.action
        def read(kind,**args):
            result=action(kind,**args)
            if kind=='status':result['position']=0
            return result
        w.action=read
    result=outcome(chat(client,'Включи первую'))
    assert result['status']!='confirmed' and w.pointers==1
    assert 'не подтвержд' in result['display']


def test_D_dom_reordering_does_not_change_the_shown_first_candidate(scene):
    client,app,w,write=scene;songs(w)
    chat(client,'Найди песню Fall Out Boy');first=dict(w.rows[0])
    w.rows.reverse()
    assert outcome(chat(client,'Включи первую'))['status']=='confirmed'
    assert w.state['id']==first['id'] and w.state['title']==first['title']


def test_C_missing_search_result_never_dispatches_a_pointer(scene):
    from core.yandex_music import MusicError
    client,app,w,write=scene;songs(w)
    chat(client,'Найди песню Fall Out Boy');action=w.action
    def missing(kind,**args):
        if kind=='select_target':raise MusicError('search_results_changed','Результаты поиска изменились','selection')
        return action(kind,**args)
    w.action=missing
    result=outcome(chat(client,'Первая'))
    assert result['status']=='failed' and not w.pointers and result['details']['diagnostics']['reason']=='search_results_changed'


@pytest.mark.parametrize('query',['Мне песню','Первая','Трек','Песня про меня'])
def test_quoted_real_titles_keep_their_words(query):
    request=media_manager.parse(f'Найди песню «{query}»',music_context=True)
    assert request.query==query


@pytest.mark.parametrize('phrase',['Не найди мне песню Fall Out Boy','Найди мне песню Fall Out Boy и открой Paint','Как найти мне песню Fall Out Boy?'])
def test_natural_wrappers_do_not_bypass_whole_request_safety(phrase):
    assert media_manager.parse(phrase,music_context=True) is None


def test_local_search_wrapper_requires_music_context():
    assert media_manager.parse('Поищи у меня Fall Out Boy',music_context=False) is None


class AudioDevice:
    def __init__(self):
        self.volume=40;self.muted=False;self.id='speakers';self.default='speakers';self.ignore=False;self.switch=False;self.calls=[]
    def read(self):return {'volume':self.volume,'muted':self.muted,'endpoint':self.id,'default_endpoint':self.default}
    def set_volume(self,value):
        self.calls.append(value)
        if not self.ignore:self.volume=value
        if self.switch:self.default='headphones'
    def set_mute(self,value):
        if not self.ignore:self.muted=value


@pytest.fixture
def volume(tmp_path,monkeypatch):
    from core.storage import Store
    device=AudioDevice()
    @contextmanager
    def endpoint():yield device
    monkeypatch.setattr(windows_audio,'endpoint',endpoint)
    return AudioTools(Store(tmp_path)),device


def test_G_master_volume_returns_same_endpoint_and_before_after(volume):
    tools,d=volume
    result=tools.execute(AudioAction(action='change_volume',value=10))
    assert result['confirmed'] and result['endpoint']=='speakers'
    assert result['before']['volume']==40 and result['volume']==50 and d.calls==[50]


@pytest.mark.parametrize('defect',['ignored','one_percent_only','device_switched'])
def test_H_master_volume_cannot_confirm_an_unchanged_or_different_endpoint(volume,defect):
    tools,d=volume;d.ignore=defect!='device_switched';d.switch=defect=='device_switched'
    if defect=='one_percent_only':
        def almost(value):d.calls.append(value)
        d.set_volume=almost
    with pytest.raises(ValueError):tools.execute(AudioAction(action='change_volume',value=1 if defect=='one_percent_only' else 10))
    assert len(d.calls)==1


def test_J_zero_is_not_described_as_audible_after_unmute(volume):
    tools,d=volume;d.volume=0;d.muted=True
    result=tools.execute(AudioAction(action='unmute'))
    assert 'не слышен' in result['text'] and 'Звук включён' not in result['text']
    spoken=audio_result({'action':'unmute','result':result},result['text'],'feminine').spoken
    assert 'ноль' in spoken or '0' in spoken


def test_I_windows_and_music_volume_are_separate_scopes(scene,monkeypatch):
    from core import audio_sessions, windows_media
    client,app,w,write=scene;d=AudioDevice();mixer=[]
    @contextmanager
    def endpoint():yield d
    monkeypatch.setattr(windows_audio,'endpoint',endpoint)
    monkeypatch.setattr(windows_media,'sessions',lambda:[{'id':'smtc:yandex','app_id':str(w.exe),'player':'Яндекс Музыка','executable':str(w.exe),'state':'Playing','available':True}])
    monkeypatch.setattr(audio_sessions,'snapshot',lambda:[{'id':'mix','pid':10,'created':10.25,'executable':str(w.exe),'active':True,'volume':60,'muted':False}])
    monkeypatch.setattr(audio_sessions,'set_volume',lambda *a,**k:mixer.append(a) or {'volume':70,'confirmed':True})
    for phrase in ('Прибавь громкость','Прибавь громче'):
        assert outcome(chat(client,phrase))['status']=='confirmed'
    assert d.volume==60 and not mixer
    result=outcome(chat(client,'Сделай музыку громче'))
    assert result['status']=='confirmed' and d.volume==60 and len(mixer)==1
    assert 'приложения' in result['display']


def test_native_default_endpoint_identity_uses_render_multimedia_and_frees_ids(monkeypatch):
    import ctypes as c
    from tests.test_device_audio import NativeFunction
    calls=[];released=[];freed=[];buffer=c.create_unicode_buffer('opaque-speakers-id')
    class Ole:
        CoInitializeEx=NativeFunction(lambda *a:0)
        CoUninitialize=NativeFunction(lambda:None)
        CoCreateInstance=NativeFunction(lambda *a:setattr(a[-1]._obj,'value',11) or 0)
        CoTaskMemFree=NativeFunction(lambda value:freed.append(value.value))
    def invoke(pointer,slot,types,*args):
        calls.append((pointer.value,slot,args))
        if slot==4:
            assert args[:2]==(0,1)  # eRender/eMultimedia, not a recording device.
            args[-1]._obj.value=12
        elif slot==3:args[-1]._obj.value=13
        elif slot==5:args[-1]._obj.value=c.addressof(buffer)
        elif slot==9:args[-1]._obj.value=.4
        elif slot==15:args[-1]._obj.value=0
    monkeypatch.setattr(windows_audio.c,'WinDLL',lambda *a,**k:Ole(),raising=False)
    monkeypatch.setattr(windows_audio.os,'name','nt')
    monkeypatch.setattr(windows_audio,'invoke',invoke)
    monkeypatch.setattr(windows_audio,'release',lambda pointer:released.append(pointer.value))
    with windows_audio.endpoint() as device:
        state=device.read()
        assert state['endpoint']==state['default_endpoint']=='opaque-speakers-id'
        assert state['endpoint_role']=='multimedia' and state['volume']==40
    assert len(freed)==2 and released==[12,13,12,11]
