"""Evaluate the preregistered owner study only after its closed set and annotations are ready."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from importlib import import_module
import json
from pathlib import Path
import wave
import zipfile

import numpy as np
from audit_wake_study import inspect, owner_fingerprints, read_audio
from wake_next6 import completed_hit, RATE

replay = import_module('replay-wake-diagnostics')
WORK = Path('local/wakeword26b')
PLAN_HASH = '750e8fab12bf29e02413260bcbb7822f2ff11758036fc831e13cdd95179ddafc'
FROZEN_MS = 1795182098128


def records(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def negative_wav(row, seen, intervals):
    if row['consent'] != 'yes' or row['no_intent'] != 'yes' or row['split'] != 'test' or not row['capture_id'].strip():
        raise ValueError('Missing recording provenance or consent')
    if int(row['started_at_ms']) <= FROZEN_MS:
        raise ValueError('Recording predates closed study')
    with wave.open(row['file'],'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate()) != (1,2,RATE) or not 0 < f.getnframes() <= 600*RATE:
            raise ValueError('Expected one mono 16k PCM16 segment up to 10 minutes')
        length=f.getnframes()
        data=f.readframes(length)
    first=int(row['source_start_sample'])
    if len(data)!=length*2 or first<0 or any(first<b and a<first+length for a,b in intervals[row['capture_id']]):
        raise ValueError('Invalid or overlapping negative audio')
    digest=hashlib.sha256(data).hexdigest()
    if digest in seen: raise ValueError('Duplicate audio')
    intervals[row['capture_id']].append((first, first+length))
    seen.add(digest)
    return data


def score(args):
    planfile=WORK/'next10/study-plan.json'
    if hashlib.sha256(planfile.read_bytes()).hexdigest()!=PLAN_HASH: raise ValueError('Study plan changed')
    plan=json.loads(planfile.read_text(encoding='utf8'))
    labels=records(args.review)
    if len(labels)!=len({r['id'] for r in labels}) or any(r['reviewed']!='yes' for r in labels):
        raise ValueError('Explicit, unique manual boundaries required')
    by_id={r['id']:r for r in labels}
    times={k:(r['wake_start_s'],r['wake_end_s']) for k,r in by_id.items()}
    known=owner_fingerprints(WORK/'owner-export-20261116-184820.zip')
    summary,items=inspect(args.archives,known,times)
    by_group=defaultdict(Counter)
    assignments={}
    session_groups={}
    for row in items:
        if row['kind']!='positive' or row['split']!='test' or row['speaker']!='n10owner' or row['session_start_ms']<=FROZEN_MS:
            raise ValueError('Expected only the new closed owner sessions')
        sample=Path(row['member']).stem
        label=by_id[sample]
        session=row['session_id']
        group=label['planned_session']
        if group not in plan['sessions'] or session_groups.setdefault(session,group)!=group or assignments.setdefault(group,session)!=session:
            raise ValueError('Each planned session must have one distinct Android session')
        if row['end'] is None or row['start'] is None: raise ValueError('Missing reviewed boundaries')
        by_group[group][row['phrase']]+=1
    if len(labels)!=len(items) or set(by_group)!=set(plan['sessions']) or any(dict(c)!=plan['per_session'] for c in by_group.values()):
        raise ValueError('Complete all planned sessions before scoring')
    negrows=records(args.negatives)
    if not negrows or {r['condition'] for r in negrows}!=set(plan['negative_conditions']):
        raise ValueError('Missing negative conditions')
    if any(r['capture_id'] in session_groups for r in negrows): raise ValueError('Positive/negative capture reused')
    seen=set(known)|{r['pcm_sha256'] for r in items}
    spans=defaultdict(list)
    negative_hashes=[]
    for row in negrows:
        raw=negative_wav(row,seen,spans)
        negative_hashes.append(hashlib.sha256(raw).hexdigest())
    grammar=json.loads((WORK/'next9/timeline.json').read_text(encoding='utf8'))['events'][0]['grammar']
    cfg=WORK/'next6/multi.config.json'; exports=WORK/'next6/onnx'
    models={'Vosk':replay.vosk_runner(WORK/'vosk-device-model'),'MULTI':replay.plix_runner(exports,cfg),
            'H2':replay.plix_runner(exports,cfg,intervention=WORK/'next7/floor.config.json')}
    result={'audit':summary,'plan_sha256':PLAN_HASH,'positives':[],'negatives':[]}
    for row in items:
        with zipfile.ZipFile(row['archive']) as z: pcm=np.frombuffer(read_audio(z,row['member']),dtype='<i2')
        sample=Path(row['member']).stem
        scores={k:completed_hit([v/RATE for v in model(pcm,grammar,'вайли')],row['end']) for k,model in models.items()}
        result['positives'].append(dict(id=sample,session=by_id[sample]['planned_session'],phrase=row['phrase'],outcome=scores))
    for row,expected in zip(negrows,negative_hashes):
        data=negative_wav(row,set(),defaultdict(list))
        if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Source changed during evaluation')
        pcm=np.frombuffer(data,dtype='<i2')
        result['negatives'].append(dict(capture_id=row['capture_id'],condition=row['condition'],seconds=len(pcm)/RATE,
            start=int(row['source_start_sample']),hits={k:model(pcm,grammar,'вайли') for k,model in models.items()}))
    result['by_group']={}
    for row in result['positives']:
        for group in ('all', row['phrase'], row['session']):
            group_rows=result['by_group'].setdefault(group,{})
            for method,(status,lag) in row['outcome'].items():
                metrics=group_rows.setdefault(method,{'statuses':Counter(),'complete_lags_ms':[]})
                metrics['statuses'][status]+=1
                if status=='complete': metrics['complete_lags_ms'].append(lag)
    for group_rows in result['by_group'].values():
        for metrics in group_rows.values():
            lags=metrics.pop('complete_lags_ms')
            metrics['p50_p95_ms']=np.percentile(lags,[50,95]).tolist() if lags else None
    result['negative_seconds']=sum(row['seconds'] for row in result['negatives'])
    result['negative_events']={k: sum(len(row['hits'][k]) for row in result['negatives']) for k in models}
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archives',nargs='+',type=Path)
    for arg in ('review','negatives','output'): p.add_argument('--'+arg,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): raise FileExistsError('Results already exist')
    result=score(args)
    with args.output.open('x',encoding='utf8') as f: json.dump(result,f,indent=2,ensure_ascii=False)

