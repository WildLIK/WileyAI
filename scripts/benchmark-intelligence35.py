"""Isolated HTTP corpus. Neutral fake LLM, fake executors; no owner data/actions."""
import argparse
import asyncio
import ctypes
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import types
import zipfile
from contextlib import contextmanager
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from core import app_discovery, commands, providers, windows_media, audio_sessions, windows_audio
from core.api import create_app
from core.launch_verification import ExecutionText

NAMES = ['Blender', 'Chrome', 'Яндекс Браузер', 'Firefox', 'AIMP', 'Яндекс Музыка', 'VLC', 'Paint', 'Krita', 'Visual Studio Code', 'Microsoft Word']

def corpus():
    cases = []
    def add(text, kind, tool='', parameters=None, clarification=False):
        cases.append(dict(text=text, expected_type=kind, tool=tool, parameters=parameters or {}, clarification=clarification, confirmation=clarification, launch_allowed=kind=='open', on_error='Ничего не выполнять; сообщить об ошибке или уточнить'))
    for verb in ['Открой', 'Запусти', 'Открой мне', 'Давай запустим', 'Пожалуйста, открой']:
        for name in ['Blender', 'Chrome', 'Яндекс Браузер', 'AIMP', 'Яндекс Музыку']:
            add(verb+' '+name, 'open', 'windows.app.open', {'name': 'Яндекс Музыка' if name=='Яндекс Музыку' else name})
    for phrase, action, scope in [('Воспроизведи музыку','play','player'),('Продолжи музыку','play','player'),('Продолжи воспроизведение','play','player'),('Поставь музыку на паузу','pause','player'),('Следующий трек','next','player'),('Предыдущий трек','previous','player'),('Сделай музыку потише','change_volume','player'),('Убавь звук','change_volume','system'),('Прибавь звук','change_volume','system'),('Пауза','pause','player')]:
        for suffix in ['', '.']: add(phrase+suffix, 'media', 'media', {'action':action,'scope':scope})
    for phrase in ['Вот ты меня слышишь', 'Ты меня слышишь', 'Расскажи о звёздах', 'Расскажи кратко о звёздах', 'Что такое нейросеть', 'Почему Луна светится', 'Чем отличается Blender от FreeCAD', 'Какие существуют программы для рисования', 'Сегодня хороший день', 'Мне нравится Blender', 'Объясни, как открыть Chrome', 'Что ты умеешь']:
        for suffix in ['', '?']: add(phrase+suffix, 'conversation')
    for phrase in ['Не открывай Blender', 'Не запускай ничего', 'Не надо открывать Chrome', 'Никогда не запускай AIMP', 'Если попрошу, открой Blender', 'Он сказал открой Chrome', 'Расскажи, как открыть приложение, но пока не запускай его', 'Не запускай музыку', 'Не включай песню', 'Не удаляй файлы']:
        add(phrase,'blocked')
    for phrase in ['Открой мне браузер','Открой браузер','Запусти браузер','Открой плеер','Открой мне плеер','Открой программу для рисования','Открой графический редактор','Запусти видеоплеер','Открой IDE','Открой текстовый редактор']:
        add(phrase,'clarify','applications.search',clarification=True)
    for phrase in ['Хочу что-нибудь нарисовать','Хочу поработать в Blender','Мне нужно заняться моделированием','Хочу поработать с текстом','Подготовь мне рабочее окружение','Открой вторую','Нет, другую','Ещё немного потише','Отмена','Закрой то, что только что открыл','Запусти песню','Найди музыку','Включи песню Кино','Открой блендир','Открой неизвестныйРедактор','Открой браузер и сделай музыку потише','Открой браузер, но музыку не трогай','Запусти калькулятор','Открой. Blender','Ты можешь открыть Blender?']:
        if phrase in {'Запусти калькулятор','Открой. Blender','Ты можешь открыть Blender?','Открой браузер, но музыку не трогай'}:
            name='калькулятор' if 'калькулятор' in phrase else 'браузер' if 'браузер' in phrase else 'Blender'
            add(phrase,'open','windows.app.open' if name!='браузер' else 'browser.open',{'name':name})
        elif phrase=='Включи песню Кино':add(phrase,'media','media',{'action':'search_play','scope':'song','query':'Кино'})
        elif phrase in {'Открой вторую','Нет, другую','Ещё немного потише','Отмена'}:add(phrase,'context_missing',clarification=True)
        else:add(phrase,'clarify',clarification=True)
    return cases

@contextmanager
def harness(root):
    with pytest.MonkeyPatch.context() as patch:
        rows=[]
        for i,name in enumerate(NAMES):
            path=root/(name+'.exe');path.touch()
            rows.append(dict(id=str(i),name=name,target=str(path),category='other',source='fixture',aliases=[]))
        patch.setattr(app_discovery,'discover',lambda:dict(supported=True,items=rows,warnings=[]))
        patch.setattr(providers,'get_key',lambda _: '')
        patch.setattr(windows_media,'sessions',lambda:[]);patch.setattr(audio_sessions,'snapshot',lambda:[])
        def blocked(*a,**kw): raise AssertionError('Unmocked native side effect')
        patch.setattr(ctypes,'WinDLL',blocked);patch.setattr(commands.webbrowser,'open',blocked)
        patch.setattr(commands.os,'startfile',blocked,raising=False)
        app=create_app(root,'intel35-fixture-0123456789');app.state.applications.scan()
        app.state.store.patch_settings(dict(semantic_commands=True,voice_diagnostics=True,yandex_auto_connect=False))
        state=dict(opened=[],media=[],ordinary=0,structured=0)
        class Device:
            volume=50
            def read(self): return dict(volume=self.volume,muted=False)
            def set_volume(self,value):
                state['media'].append(dict(action='change_volume',scope='system'));self.volume=value
        device=Device()
        @contextmanager
        def endpoint():yield device
        patch.setattr(windows_audio,'endpoint',endpoint)
        def execute(command,**kw):
            state['opened'].append(command.label)
            return ExecutionText('Процесс подтверждён: '+command.label,dict(status='process_started',pid=123))
        def media(request,*a,**kw):
            if request.scope=='song' and not request.query:return dict(text='Какую песню включить?',status='needs_clarification')
            state['media'].append(vars(request));return dict(text='Команда подтверждена стендом.',spoken='Готово.',status='confirmed')
        patch.setattr(commands,'execute',execute);patch.setattr(app.state.media,'execute',media)
        async def chat(*a,**kw): state['ordinary']+=1;yield 'Ответ для изолированного стенда.'
        async def structured(settings,messages,schema,**kw):
            state['structured']+=1
            return json.dumps({'intent':'clarify','steps':[]}) if 'intent' in schema.get('properties',{}) else json.dumps({'steps':[],'clarification':'Уточните задачу.'})
        patch.setattr(providers,'chat',chat);patch.setattr(providers,'structured',structured)
        with TestClient(app,headers={'Authorization':'Bearer intel35-fixture-0123456789'}) as client:
            yield client,state

def run_case(client,state,case):
    state.update(opened=[],media=[],ordinary=0,structured=0)
    chat=client.post('/conversations',json={'title':'Fixture'}).json()['id']
    began=time.perf_counter()
    response=client.post('/chat',json={'text':case['text'],'mode':'conversation','conversation_id':chat})
    elapsed=(time.perf_counter()-began)*1000
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    kind=case['expected_type'];p=case['parameters']
    error=any(event['type']=='error' for event in events) or response.status_code!=200
    passed=not error
    if kind=='open':passed &= len(state['opened'])==1 and state['opened'][0].startswith(p['name']) and not state['structured']
    elif kind=='media':passed &= len(state['media'])==1 and all(state['media'][0].get(key)==value for key,value in p.items()) and not state['structured']
    elif kind=='conversation':passed &= state['ordinary']==1 and state['structured']==0 and not state['opened'] and not state['media']
    elif kind in {'clarify','blocked','context_missing'}:passed &= not state['opened'] and not state['media']
    with client.app.state.store.db() as db:
        row=db.execute('select value from chat_dialogue where conversation_id=?',(chat,)).fetchone()
    pending=json.loads(row['value']).get('pending_open',{}) if row else {}
    return dict(text=case['text'],passed=bool(passed),milliseconds=round(elapsed,3),proposed=[item['label'] for item in pending.get('choices',[])],response=''.join(e.get('text','') for e in events if e['type']=='delta'),**state)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--write-corpus',action='store_true');parser.add_argument('--baseline',action='store_true');args=parser.parse_args()
    if args.baseline:
        from core import api as api_module
        old=types.ModuleType('core._intel35_before');sys.modules[old.__name__]=old
        with zipfile.ZipFile('local/review/intelligence35/baseline-files.zip') as archive:exec(compile(archive.read('core/semantic_commands.py'),'baseline/semantic_commands.py','exec'),old.__dict__)
        api_module.semantic_commands=old
        app_discovery.purpose_key=lambda _:None
        app_discovery.ApplicationScanner.purpose_matches=lambda self,_:None
    cases=corpus()
    if args.write_corpus:Path('tests/fixtures/intelligence35.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='wiley-intel35-') as folder:
        with harness(Path(folder)) as (client,state):results=[run_case(client,state,case) for case in cases]
    fast=[row['milliseconds'] for row,case in zip(results,cases) if case['expected_type'] in {'open','media'}]
    report=dict(scope='HTTP, neutral fake LLM, fake OS; not model understanding accuracy',count=len(results),passed=sum(r['passed'] for r in results),mean_fast_ms=statistics.mean(fast),p95_fast_ms=sorted(fast)[int(.95*(len(fast)-1))],structured_requests=sum(r['structured'] for r in results),ordinary_requests=sum(r['ordinary'] for r in results),results=results)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))

if __name__=='__main__':main()
