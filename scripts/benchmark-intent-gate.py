"""C7 A/B/C: real API routing, fake effects, optional installed loopback Qwen only."""
import argparse
import asyncio
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import providers, device_audio, commands, media_manager, semantic_commands
from scripts.semantic_test_safety import isolated_boundaries

spec = importlib.util.spec_from_file_location('c7_base_suite',ROOT/'scripts/benchmark-intent-suite.py')
base = importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
FIXTURE = ROOT/'tests/fixtures/intent-gate/c7.json'
SOURCE_FILES = ['core/intent_gate.py','core/api.py','core/providers.py','core/intents.py','core/audio_intents.py','core/media_manager.py','core/semantic_commands.py','core/config.py','scripts/benchmark-intent-gate.py','scripts/semantic_test_safety.py']


def load_cases():
    seal=json.loads(FIXTURE.with_name('seal.json').read_text())
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest()!=seal['c7.json']:raise ValueError('Frozen fixture changed')
    data=json.loads(FIXTURE.read_text(encoding='utf-8'));cases=data['cases']
    if len(cases)!=150 or len({c['id'] for c in cases})!=150 or sum(c['expected_effect']=='none' for c in cases)<75:raise ValueError('Invalid fixture')
    return cases


def scripted(case,messages):
    if case.get('injected_response'):return case['injected_response']
    expected=case['expected']
    if expected=='no_action':return json.dumps({'kind':'prohibit'})
    if expected=='conversation':return json.dumps({'kind':'information'})
    if expected=='clarification':return json.dumps({'kind':'ambiguous'})
    category=case['category']
    if category=='apps':
        rows=json.loads(messages[0]['content'].split('Каталог: ')[1]);want=case['choice_name'].casefold()
        keys=[row['id'] for row in rows if row['name'].casefold()==want]
        return json.dumps({'kind':'indirect','tool':'applications.search','choices':keys})
    if category in {'volume','context'}:return json.dumps({'kind':'context' if category=='context' else 'action','tool':'audio.volume','source':case['source'],'value':case['value']})
    if category=='playback':return json.dumps({'kind':'action','tool':'audio.playback','source':'music','action':case['action']})
    if category=='search':return json.dumps({'kind':'action','tool':'media.manager','source':'music','action':'search','query':case['query']})
    raise ValueError('Unimplemented fixture category')


def effects():
    return [*(('open',*r) for r in base.REC.open),*(('audio',*r) for r in base.REC.audio if r[0] not in {'status','read'}),
            *(('media',*r) for r in base.REC.media if r[0] not in {'status','read','found'}),
            *((('yandex',*r) for r in base.REC.yandex if r[0] not in {'status','read'}) if not base.REC.media else [])]


def assess(case,dialogue,trace,events,elapsed,model_calls,script_calls):
    gate=trace.get('intent_gate',{});calls=effects()
    pending=next((dialogue[k] for k in ('pending_open','pending_audio','pending_media') if dialogue.get(k)),None)
    statuses=[e.get('action',{}).get('status') for e in events if e['type']=='speech_result']
    if calls: actual='search' if all(r[0] in {'media','yandex'} and r[1]=='search' for r in calls) else 'execution'
    elif pending:actual='proposal'
    elif gate.get('kind') in {'ambiguous','compound'} or any(s in {'needs_clarification','clarification'} for s in statuses):actual='clarification'
    elif gate.get('kind')=='prohibit' or any(s in {'prohibited','cancelled','no_action'} for s in statuses):actual='no_action'
    else:actual='conversation'
    tool=gate.get('tool','')
    if not tool and pending:
        tool='windows.app.open' if 'choices' in pending and pending.get('choices') and 'kind' in pending['choices'][0] else 'audio.volume' if (pending.get('action') or {}).get('action')=='change_volume' else 'audio.playback'
    if not tool and calls:
        tool='media.manager' if calls[-1][0] in {'media','yandex'} else 'audio.volume' if calls[-1][0]=='audio' else 'windows.app.open'
    expected=case['expected'];argument_ok=None
    if case['category']=='apps' and pending:
        labels=[r.get('label','').casefold() for r in pending.get('choices',[])]
        argument_ok=bool(labels) and all(label==case['choice_name'].casefold() for label in labels)
    if case['category'] in {'volume','context'} and pending:
        argument_ok=(pending.get('action') or {}).get('value')==case['value'] and pending.get('source')==case['source']
    if case['category']=='playback' and pending:argument_ok=(pending.get('action') or {}).get('action')==case['action']
    if case['category']=='search' and calls:
        argument_ok=any(r[0]=='media' and r[1]=='search' and r[4]==case['query'] or r[0]=='yandex' and r[1]=='search' and r[2]==case['query'] for r in calls)
    tool_ok=tool in case['allowed_tools'] if case['allowed_tools'] else not tool
    # A failed parse has no accepted tool, even if a trace records a rejected suggestion.
    if actual in {'conversation','no_action','clarification'} and not calls and not pending:tool_ok=not case['allowed_tools']
    false_action=bool(calls) and (case['expected_effect']!='search_only' or actual!='search')
    false_proposal=bool(pending) and not case['confirmation'] and case['expected']!='search'
    confirmation_ok=bool(pending)==case['confirmation'] if actual!='search' else not case['confirmation']
    passed=actual==expected and tool_ok and argument_ok is not False and not false_action and not false_proposal and confirmation_ok
    reason='' if passed else 'unauthorized_effect' if false_action else 'unexpected_pending' if false_proposal else 'wrong_intent' if actual!=expected else 'wrong_tool' if not tool_ok else 'wrong_arguments' if argument_ok is False else 'confirmation_mismatch'
    return {'id':case['id'],'split':case['split'],'category':case['category'],'text':case['text'],'expected':expected,'allowed_tools':case['allowed_tools'],
        'expected_confirmation':case['confirmation'],'actual':actual,'actual_tool':tool,'arguments_correct':argument_ok,'tool_correct':tool_ok,
        'confirmation_correct':confirmation_ok,'intent_correct':actual==expected,'passed':passed,'reason':reason,
        'false_action':false_action,'false_proposal':false_proposal,'effects':calls,'route_ms':round(elapsed,2),'gate':gate,
        'real_model_calls':model_calls,'scripted_model_calls':script_calls,'injected_validation_probe':bool(case.get('validation_probe')),
        'late_or_cancelled':gate.get('reason') in {'cancelled','invalidated'},'transcript':'fixture text, no microphone'}


def summary(rows):
    def rate(values):return round(sum(values)/len(values),4) if values else None
    def timing(values):
        values=sorted(values)
        return {'p50_ms':round(statistics.median(values),2),'p95_ms':round(values[min(len(values)-1,int(len(values)*.95))],2)} if values else {'p50_ms':None,'p95_ms':None}
    negative=[r for r in rows if not r['allowed_tools']]
    clarify=[r for r in rows if r['expected']=='clarification']
    args=[r['arguments_correct'] for r in rows if r['arguments_correct'] is not None]
    return {'total':len(rows),'passed':sum(r['passed'] for r in rows),'errors':sum(bool(r.get('error')) for r in rows),
        'correct_intent_rate':rate([r['intent_correct'] for r in rows]),'correct_tool_selection':rate([r['tool_correct'] for r in rows]),
        'false_actions':sum(r['false_action'] for r in rows),'false_action_rate':rate([r['false_action'] for r in negative]),'negative_cases':len(negative),
        'false_proposals':sum(r['false_proposal'] for r in rows),'clarification_accuracy':rate([r['actual']=='clarification' for r in clarify]),
        'argument_accuracy':rate(args),'argument_evaluated':len(args),'confirmation_accuracy':rate([r['confirmation_correct'] for r in rows]),
        'real_model_calls':sum(r['real_model_calls'] for r in rows),'scripted_model_calls':sum(r['scripted_model_calls'] for r in rows),
        'fast_path_fraction':rate([r['gate'].get('fast_path',True) for r in rows]),'late_or_cancelled':sum(r['late_or_cancelled'] for r in rows),
        'route_latency':timing([r['route_ms'] for r in rows]),'classification_latency':timing([r['gate'].get('classification_ms',0) for r in rows if r['gate'].get('called') and not r['injected_validation_probe']])}


def run(mode,cases,model_url):
    raw_chat,raw_structured=providers.chat,providers.structured
    rows=[];cold=[]
    with tempfile.TemporaryDirectory(prefix='wileyai-c7-') as directory:
        root=Path(directory);windows=root/'Windows';(windows/'System32').mkdir(parents=True)
        for p in (windows/'explorer.exe',windows/'System32/notepad.exe',windows/'System32/calc.exe'):p.touch()
        import os
        with patch.dict(os.environ,{'WILEYAI_TEST':'1','WILEYAI_DATA_DIR':str(root/'unused'),'WINDIR':str(windows)}), isolated_boundaries(local_model_url=model_url if mode=='C' else None) as blocked:
            for number,case in enumerate(cases):
                folder=root/case['id'];folder.mkdir();restore=base.setup_case(folder)
                model_calls=script_calls=legacy_route_calls=0;level={'volume':50,'muted':False};raw_predictions=[]
                def audio(self,command,**kwargs):
                    base.REC.audio.append((command.action,command.value));before=dict(level)
                    if command.action=='change_volume':level['volume']=max(0,min(100,level['volume']+command.value))
                    elif command.action=='set_volume':level['volume']=command.value
                    elif command.action in {'mute','unmute'}:level['muted']=command.action=='mute'
                    return {'text':f"Громкость Windows: {level['volume']}%.",'confirmed':True,'scope':'windows_master',**level,'before':before,'diagnostics':{'expected_volume':level['volume']}}
                device_audio.AudioTools.execute=audio
                before_blocked=len(blocked)
                try:
                    with base.build_case_app(folder) as client:
                        client.put('/settings',json={'semantic_commands':True,'intent_gate':mode!='A','music_player':'yandex','media_source':'auto','provider':'ollama','model':'qwen3.5:4b','base_url':model_url})
                        async def decision(cfg,messages,schema,**kwargs):
                            nonlocal model_calls,script_calls
                            if 'kind' not in schema.get('properties',{}):return base.scripted_structured(cfg,messages,schema,**{k:v for k,v in kwargs.items() if k=='max_chars'})
                            if mode=='C' and not case.get('validation_probe'):
                                model_calls+=1
                                with patch.object(providers,'chat',raw_chat):raw=await raw_structured(cfg,messages,schema,**kwargs)
                                raw_predictions.append(raw)
                                return raw
                            script_calls+=1
                            return scripted(case,messages)
                        legacy_route=semantic_commands.route
                        async def record_legacy(*a,**kw):
                            nonlocal legacy_route_calls
                            legacy_route_calls+=1;before_chat=base.REC.chat_calls
                            result=await legacy_route(*a,**kw)
                            base.REC.chat_calls=before_chat
                            return result
                        with patch.object(providers,'structured',decision), patch.object(semantic_commands,'route',record_legacy):
                            for text in case.get('setup',[]):base.send(client,text)
                            base.REC.open.clear();base.REC.audio.clear();base.REC.media.clear();base.REC.yandex.clear();base.REC.events.clear()
                            base.REC.chat_calls=base.REC.structured_calls=0
                            model_calls=script_calls=legacy_route_calls=0
                            _,elapsed=base.send(client,case['text'])
                            source_id=next((e['message']['id'] for e in base.REC.events if e['type']=='user'),None)
                            traces=client.get('/commands/traces').json();trace=next((t for t in traces if t.get('source_message_id')==source_id),{})
                            dialogue=client.app.state.store.dialogue() if hasattr(client,'app') else {}
                            total_scripted=script_calls+base.REC.chat_calls+base.REC.structured_calls+legacy_route_calls
                            if mode=='A':trace['intent_gate']={'enabled':False,'called':False,'fast_path':not total_scripted,'reason':'disabled'}
                            row=assess(case,dialogue,trace,base.REC.events,elapsed,model_calls,total_scripted)
                            row['raw_decisions']=raw_predictions
                            row['proposed_arguments']={k:pending[k] for k in ('action','source','media_source') if k in pending} if (pending:=next((dialogue[k] for k in ('pending_open','pending_audio','pending_media') if dialogue.get(k)),None)) else {}
                            if pending and pending.get('choices'):row['proposed_arguments']['choices']=[{'kind':r.get('kind'),'label':r.get('label')} for r in pending['choices']]
                            if len(blocked)!=before_blocked:raise RuntimeError('Blocked boundary: '+','.join(blocked[before_blocked:]))
                            if any(e['type']=='error' for e in base.REC.events):raise RuntimeError('API error')
                            if row['gate'].get('provider_timing'):cold.append({'id':case['id'],**row['gate']['provider_timing'],'classification_ms':row['gate'].get('classification_ms')})
                except Exception as error:
                    row={'id':case['id'],'split':case['split'],'category':case['category'],'text':case['text'],'expected':case['expected'],'allowed_tools':case['allowed_tools'],
                        'actual':'error','actual_tool':'','arguments_correct':None,'tool_correct':False,'confirmation_correct':False,'intent_correct':False,'passed':False,
                        'false_action':bool(effects()),'false_proposal':False,'reason':'harness_or_api_error','error':type(error).__name__+': '+str(error)[:180],
                        'route_ms':0,'gate':{},'real_model_calls':model_calls,'scripted_model_calls':script_calls,'late_or_cancelled':False,'injected_validation_probe':bool(case.get('validation_probe'))}
                finally:device_audio.AudioTools.execute,media_manager.MediaManager.execute,commands.execute=restore[2],restore[1],restore[0]
                rows.append(row)
                if (number+1)%10==0:print(f'C7 {mode}: {number+1}/{len(cases)}',file=sys.stderr,flush=True)
    return {'summary':summary(rows),'categories':{c:summary([r for r in rows if r['category']==c]) for c in dict.fromkeys(r['category'] for r in rows)},'cases':rows,'blocked_boundary_calls':blocked,'provider_samples':cold}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['A','B','C'],required=True);parser.add_argument('--split',choices=['tuning','holdout','all'],required=True)
    parser.add_argument('--model-url',default='http://127.0.0.1:17434');parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks/intent-gate-c7.json')
    parser.add_argument('--run-label',default='',help='Optional timing repeat label; never overwrites a previous run')
    args=parser.parse_args();cases=[c for c in load_cases() if args.split=='all' or c['split']==args.split]
    report=json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    key=args.mode+'_'+args.split+('_'+args.run_label if args.run_label else '')
    if key in report.get('runs',{}):raise ValueError('Preserve previous run; choose a new output file')
    report.update(stage='C7 3.6.6',fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),effects='fake only',
        limitations='Real /chat, validators and Pending. A legacy scripted fallback; B scripted gate; C installed loopback Qwen for classifier only. Dialogue scripted. Ten injected protocol probes are not real model predictions.',
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCE_FILES})
    result=run(args.mode,cases,args.model_url)
    result['completed_at']=datetime.now(timezone.utc).isoformat()
    result['source_sha256']=dict(report['source_sha256'])
    report.setdefault('runs',{})[key]=result
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result=report['runs'][key];print(json.dumps({'run':key,**result['summary']},ensure_ascii=False))
    for row in result['cases']:
        if not row['passed']:print(json.dumps({k:row.get(k) for k in ('id','text','expected','actual','actual_tool','reason','error')},ensure_ascii=False))
    return 1 if result['summary']['errors'] or result['summary']['false_actions'] else 0


if __name__=='__main__':raise SystemExit(main())
