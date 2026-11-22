"""Apply experimental context masks to new fused clips without changing detector parameters."""
import argparse
from importlib import import_module
import json
from pathlib import Path
import re
from zipfile import ZipFile

import numpy as np

from audit_wake_study import read_audio
from wake_next6 import HOP, RATE

study=import_module('analyze-next11-study')


def name_range(result):
    tokens=result['tokens']
    times=result['timestamps']
    if not tokens or len(tokens)!=len(times) or any(not np.isfinite(t) for t in times):
        return None
    text=''.join(tokens).lower()
    match=re.match(r'^\s*(?:окей\s+)?(вайли|уайли)(?=\s|$)\s*\S',text)
    if not match:
        return None
    boundaries=np.cumsum([0]+[len(t) for t in tokens])
    start=np.searchsorted(boundaries,match.start(1),side='right')-1
    last=np.searchsorted(boundaries,match.end(1)-1,side='right')-1
    after=np.searchsorted(boundaries,match.end()-1,side='right')-1
    return [float(times[i]) for i in (start,last,after)]


def report(args):
    data=json.loads(args.replay.read_text(encoding='utf8'))
    models=study.models()
    details=[]
    with ZipFile(args.archive) as archive:
        for sample in data['samples']:
            row=sample['row']
            if row['category'] not in ('fused','okay'):
                continue
            bounds=name_range(sample['recognition'])
            part=dict(id=row['id'],label=row['original_phrase'],category=row['category'],giga_name_token_times=bounds,
                      original_hits={m:sample['detectors'][m]['hits'] for m in study.METHODS})
            details.append(part)
            if bounds is None or bounds[2]<=bounds[1]:
                continue
            raw=np.frombuffer(read_audio(archive,row['id']+'.wav'),dtype='<i2')
            cuts=[]
            midpoint=(bounds[1]+bounds[2])/2
            for delta in (-.08,0,.08):
                cut=round((midpoint+delta)*RATE)
                pcm=np.r_[raw[:cut],np.zeros(len(raw)+RATE-cut,dtype='<i2')]
                entry=dict(cut_s=cut/RATE,relative_to_token_midpoint_s=delta,methods={})
                end=min(len(raw)+RATE,cut+RATE)
                for model in study.METHODS:
                    out=models[model](pcm,json.dumps(data['grammar'],ensure_ascii=False),'вайли')
                    view=dict(hits=out['hits'])
                    if model!='vosk':
                        def best(values):
                            selected=[(p,s) for p,s in values if round(bounds[0]*RATE)<=p<=end]
                            ranked=max(((p,min(s,selected[i-1][1])) for i,(p,s) in enumerate(selected) if i),
                                key=lambda row:row[1],default=(None,None))
                            return ranked
                        view['original_pair']=best(sample['detectors'][model]['scores'])
                        view['masked_pair']=best(out['scores'])
                    entry['methods'][model]=view
                cuts.append(entry)
            part['cuts']=cuts
    return dict(protocol='ASR token timestamps only. Three nearby audio masks. No word boundary ground truth.',rows=details)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('archive','replay','output'):p.add_argument('--'+arg,required=True,type=Path)
    a=p.parse_args()
    with a.output.open('x',encoding='utf8') as stream:
        json.dump(report(a),stream,ensure_ascii=False,indent=2)

