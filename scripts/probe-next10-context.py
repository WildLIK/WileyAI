"""Retrospective matched ablations and a single one-window diagnostic variant; no fitting."""
from collections import Counter
from importlib import import_module
import json
from pathlib import Path
import time
import zipfile
import argparse

import numpy as np
from plix_next6 import PLiX, file_hash
from wake_next6 import RATE, HOP, events, completed_hit
from wake_next7 import detector, causal_window, score_window

bench = import_module('probe-next6-wake')
replay = import_module('replay-wake-diagnostics')


def single(scores, threshold):
    active = False
    rearm = 0.
    for t, score in scores:
        if score >= threshold and not active and t >= rearm:
            yield t
            rearm = t + .8
        active = score >= threshold


def analyse(work):
    started = time.process_time()
    cfg_path = work/'next6/multi.config.json'
    lock = json.loads((work/'next10/device/lock.json').read_text())
    if any(file_hash(path) != lock['sources'][path.name] for path in [
            cfg_path, work/'next7/floor.config.json', work/'owner-annotations-reviewed.csv',
            work/'b6/owner-splits.json',work/'owner-export-20261116-184820.zip',
            work/'next6/onnx/multi.onnx',work/'next6/onnx/multi-frontend.npz']):
        raise ValueError('Inputs changed after registration')
    cfg=json.loads(cfg_path.read_text())
    enc=PLiX(work/'next6/onnx','multi')
    anchors=np.array(cfg['variant_prototypes']['3'],dtype=np.float32)
    bank=np.array(cfg['negative_bank'],dtype=np.float32)
    splits=json.loads((work/'b6/owner-splits.json').read_text(encoding='utf-8-sig'))
    rows=[]
    costs={}
    cut=lock['parameters']['calibration']['threshold']
    with zipfile.ZipFile(work/'owner-export-20261116-184820.zip') as archive:
        for key,pcm,start,end,condition,phrase in next(bench.owner_rows(work,archive,splits,('test',))):
            first,last=round(start*RATE),round(end*RATE)
            record=dict(id=key,phrase=phrase,condition=condition,word_ms=round((end-start)*1000),models={})
            for model,encode in [('base',enc),('H2',detector(enc,'floor'))]:
                def trace(onset=None,offset=None):
                    pos = range(HOP, len(pcm)+RATE+1,HOP)
                    if onset is not None or offset is not None:
                        pos = [p for p in pos if first <= p <= last+RATE]
                    return [(p/RATE,score_window(encode(causal_window(pcm,p,word_start=onset,word_end=offset)),anchors,bank)['margin']) for p in pos]
                cpu=time.process_time()
                raw=trace()
                costs[model]=costs.get(model,0.)+time.process_time()-cpu
                scores=dict(raw=raw,remove_before=trace(onset=first),remove_after=trace(offset=last),word_only=trace(first,last))
                output={}
                for label,points in scores.items():
                    nearby=[(t,s) for t,s in points if start<=t<=end+1]
                    peak=max(nearby,key=lambda row:row[1])
                    pairs=[(t,min(s,nearby[i-1][1])) for i,(t,s) in enumerate(nearby) if i]
                    best_pair=max(pairs,key=lambda row:row[1])
                    output[label]=dict(peak=peak[1],peak_lag_ms=round(1000*(peak[0]-end)),
                        pair_peak=best_pair[1],pair_lag_ms=round(1000*(best_pair[0]-end)),
                        scores=[(round(1000*(t-end)),s) for t,s in nearby],
                        complete=completed_hit(list(events(points,cut)),end)[0])
                output['one_window']=completed_hit(list(single(raw,cut)),end)
                output['two_windows']=completed_hit(list(events(raw,cut)),end)
                record['models'][model]=output
            rows.append(record)
    timeline=json.loads((work/'next9/timeline.json').read_text(encoding='utf8'))
    neg_sessions={e['session_id'] for e in timeline['events'] if e['utc'].startswith('2026-11-20')}
    timings={}
    for name, rule in [('two',events),('one',single)]:
        hits=[]
        begin=time.process_time()
        for island in timeline['islands']:
            if island['session_id'] not in neg_sessions: continue
            points=[(pos/RATE,s) for pos,s in island['models']['floor']['scores']]
            hits.extend((island['session_id'],island['start']+round(t*RATE)) for t in rule(points,cut))
        timings[name]=dict(hits=hits,decision_loop_cpu_s=time.process_time()-begin)
    return dict(protocol='Archived retrospective control; no future recordings; 80ms capture grid; zeros only in diagnostic interventions and old control tail',rows=rows,
        natural_cpu_seconds=costs,retrospective_negatives=timings,process_cpu_seconds=time.process_time()-started)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with args.output.open('x',encoding='utf8') as f:
        json.dump(analyse(Path('local/wakeword26b')),f,ensure_ascii=False,indent=2)

