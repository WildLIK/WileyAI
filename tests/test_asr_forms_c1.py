"""Contextual C1 normalization via /chat; every executor is fake."""
import json
import time

import pytest

from core.device_audio import request_form, ASR_FORMS
from core.media_manager import parse
from core.music_intents import compound_request
from core.launch_verification import ExecutionText
from tests.test_media_manager import ctx


FORMS = [
    ('Продолжим музыку','продолжи музыку','play'),
    ('Поставим на паузу','поставь на паузу','pause'),
    ('Убавим громкость на 10','убавь громкость на 10','change_volume'),
    ('Прибавим громкость на двадцать','прибавь громкость на двадцать','change_volume'),
    ('Переключим трек','переключи трек','next'),
    ('Возобновим музыку','возобнови музыку','play'),
    ('Остановим музыку','останови музыку','pause'),
    ('Включим мою волну','включи мою волну','wave'),
    ('Запустим мою волну','запусти мою волну','wave'),
    ('Откроем калькулятор','открой калькулятор','app'),
]


@pytest.fixture
def c1(ctx, monkeypatch):
    client, app, rows, mixer, sent, writes, special, apps = ctx
    store=app.state.store
    store.patch_settings({'music_player':'yandex','voice_diagnostics':True})
    monkeypatch.setattr(app.state.music,'status',lambda: {'connected':True})
    opened,audio,model=[],[],[]
    monkeypatch.setattr('core.commands.execute',lambda command,**kw: opened.append(command) or ExecutionText('Fixture process confirmed',{'status':'process_started'}))
    def execute_audio(self,command,**kw):
        audio.append(command)
        return {'text':'Фикстурная громкость подтверждена','state':{'volume':40,'muted':False}}
    monkeypatch.setattr('core.device_audio.AudioTools.execute',execute_audio)
    def forbidden(*a,**k): pytest.fail('Unmocked endpoint must never be used')
    monkeypatch.setattr('core.windows_audio.endpoint',forbidden)
    async def conversation(*a,**k):
        model.append(1)
        yield 'Фикстурный разговор без действий'
    monkeypatch.setattr('core.providers.chat',conversation)
    return client,app,rows,sent,special,opened,audio,model


def chat(client,text,**extra):
    response=client.post('/chat',json={'text':text,'mode':'conversation',**extra})
    assert response.status_code==200 and '"done"' in response.text,response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


@pytest.mark.parametrize('original,normalized,action',FORMS)
def test_ten_asr_forms_route_once_without_llm_or_argument_loss(c1,original,normalized,action):
    client,app,rows,sent,special,opened,audio,model=c1
    assert request_form(original)==normalized
    events=chat(client,original)
    diagnostic=next(e for e in events if e['type']=='asr_normalization')
    assert diagnostic['original']==original and diagnostic['normalized']==normalized and diagnostic['decision']['applied']
    assert next(e['message'] for e in events if e['type']=='user')['content']==original
    if action=='app': assert len(opened)==1 and opened[0].kind=='app'
    elif action=='change_volume':
        assert len(audio)==1 and audio[0].value==(-10 if original.startswith('Убавим') else 20)
    else: assert len(special)==1 and special[0].action==action
    assert not model and not sent


@pytest.mark.parametrize('text',[
    'Не продолжим музыку','Я сказал продолжим музыку','Если продолжим музыку',
    'Почему мы продолжим музыку?','Песня называется „Продолжим музыку“',
    '«Продолжим музыку»','Продолжим музыку?','Продолжим?',
    'Убавим зарплату','Откроем неизвестную цель','Продолжым музыку',
])
def test_negative_reported_conditional_questions_and_unknown_targets_do_not_execute(c1,text):
    client,app,rows,sent,special,opened,audio,model=c1
    assert request_form(text)==text
    chat(client,text)
    assert not sent and not special and not opened and not audio


@pytest.mark.parametrize('text',['Продолжим музыку и откроем Blender','Убавим громкость и включим мою волну','Давай поставим песню Numb, затем откроем Blender','Поставим песню Numb и отправим письмо','Не продолжим музыку, а откроем Blender','Ну, продолжим музыку и откроем Blender'])
def test_asr_compounds_are_rejected_by_c5_before_any_executor(c1,text):
    client,app,rows,sent,special,opened,audio,model=c1
    assert compound_request(text) and parse(text) is None
    events=chat(client,text)
    assert next(e['action'] for e in events if e['type']=='speech_result')['status']=='needs_clarification'
    assert not sent and not special and not opened and not audio and not model


@pytest.mark.parametrize('text',['Давай продолжим музыку','Ну, продолжим, музыку.','Продолжим. музыку','Уайли, продолжим, музыку!'])
def test_wrappers_and_one_asr_punctuation_error_preserve_target(c1,text):
    client,app,rows,sent,special,opened,audio,model=c1
    chat(client,text)
    assert len(special)==1 and special[0].action=='play' and not model


def test_titles_and_user_history_are_never_rewritten(c1):
    client,app,rows,sent,special,opened,audio,model=c1
    text='Включи песню Продолжим музыку'
    assert request_form(text)==text
    chat(client,text)
    assert special[-1].query=='Продолжим музыку'
    chat(client,'Поставим песню Numb Linkin Park')
    assert special[-1].query=='Numb Linkin Park'
    assert app.state.store.list('messages',2)[0]['content']=='Поставим песню Numb Linkin Park'


@pytest.mark.parametrize('context',['none','yandex','explicit_session','fresh_choice','expired_choice','missing_selected_session'])
def test_bare_resume_obeys_existing_player_selection(c1,context):
    client,app,rows,sent,special,opened,audio,model=c1
    store=app.state.store
    store.patch_settings({'music_player':'auto','media_source':'auto'})
    rows[0]['state']='Paused'
    if context=='none': rows.clear()
    if context=='yandex': store.patch_settings({'music_player':'yandex'})
    if context=='explicit_session': store.patch_settings({'media_source':'smtc:AIMP'})
    if context in {'fresh_choice','expired_choice'}:
        store.save_dialogue({'media_choice':{'id':'smtc:AIMP','created':time.time()-(301 if context=='expired_choice' else 0)}})
    if context=='missing_selected_session': store.patch_settings({'media_source':'smtc:Missing'})
    events=chat(client,'Продолжим')
    if context=='yandex': assert len(special)==1 and special[0].action=='play' and not sent
    elif context in {'explicit_session','fresh_choice'}: assert sent==[('smtc:AIMP','play')] and not special
    else: assert not sent and not special and not opened and not audio
    if context in {'none','expired_choice'}:
        assert next(e['action'] for e in events if e['type']=='speech_result')['status']=='needs_clarification'


def test_permissions_and_request_id_dedup_are_preserved(c1):
    client,app,rows,sent,special,opened,audio,model=c1
    app.state.store.patch_settings({'allow_audio_control':False})
    chat(client,'Продолжим музыку')
    assert not special and not sent
    app.state.store.patch_settings({'allow_audio_control':True,'allow_app_open':False})
    chat(client,'Откроем калькулятор')
    assert not opened
    app.state.store.patch_settings({'allow_app_open':True})
    chat(client,'Продолжим музыку',request_id='asr-single-request')
    repeated=client.post('/chat',json={'text':'Продолжим музыку','request_id':'asr-single-request'})
    assert repeated.status_code==409 and len(special)==1


def test_diagnostics_do_not_duplicate_transcripts_into_action_journal(c1):
    client,app,rows,sent,special,opened,audio,model=c1
    original='Поставим песню Numb Linkin Park'
    events=chat(client,original)
    assert any(e['type']=='voice_diagnostic' and 'поставим → поставь' in e['text'] for e in events)
    trace=next(json.loads(row['details']) for row in app.state.store.list('actions',100) if row['kind']=='command.trace')
    info=trace['asr_normalization']
    assert info['source_verb']=='поставим' and info['normalized_verb']=='поставь'
    assert 'original' not in info and 'normalized' not in info and original not in json.dumps(info,ensure_ascii=False)


@pytest.mark.parametrize('text',['Не продолжим музыку','Я сказал продолжим музыку','Если продолжим музыку','Песня называется „Продолжим музыку“'])
def test_non_action_diagnostics_keep_raw_text_and_explain_refusal(c1,text):
    client,app,rows,sent,special,opened,audio,model=c1
    events=chat(client,text)
    diagnostic=next(e for e in events if e['type']=='asr_normalization')
    assert diagnostic['normalized']==diagnostic['original']==text
    assert not diagnostic['decision']['applied'] and diagnostic['decision']['reason']=='non_command_context'
    assert not sent and not special and not opened and not audio


def test_bare_open_requires_a_target_even_with_a_selected_player(c1):
    client,app,rows,sent,special,opened,audio,model=c1
    events=chat(client,'Откроем')
    diagnostic=next(e for e in events if e['type']=='asr_normalization')
    assert diagnostic['decision']['reason']=='missing_target' and diagnostic['normalized']=='Откроем'
    assert not sent and not special and not opened and not audio and not model
