"""Measure causal voice similarity on the exact original false-wake audio."""
import argparse
from importlib import import_module
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from audit_wake_study import read_audio

study=import_module('analyze-next11-speaker')


def run(args):
    model=study.Model()
    verification=json.loads((args.results/'verification.json').read_text(encoding='utf8'))
    detector_data=json.loads((study.ROOT/'next11/results/replay-results.json').read_text(encoding='utf8'))
    ref=np.load(args.results/'owner-reference.npy',allow_pickle=False)
    rows=[]
    if study.sha(args.archive)!=detector_data['input_sha256']['zip']:
        raise ValueError('Archive differs from NEXT 11')
    with ZipFile(args.archive) as bundle:
        for entry in detector_data['samples']:
            if entry['row']['kind']!='negative':
                continue
            key=entry['row']['id']
            pcm=study.speech_audio(read_audio(bundle,key+'.wav'))
            for method in ('vosk','h2'):
                for time in entry['detectors'][method]['hits']:
                    stamps=[]
                    for delay in (0.,.5,1.):
                        right=time+round(delay*study.RATE)
                        if right>len(pcm):
                            continue
                        for duration in (.5,1.,1.5,2.):
                            left=right-round(duration*study.RATE)
                            if left<0:
                                continue
                            score=float(model.embedding(pcm[left:right])@ref)
                            threshold=verification['thresholds'][str(duration)]
                            stamps.append(dict(after_decision_s=delay,window_s=duration,
                                score=score,threshold=threshold['decision'] if threshold else None,
                                passes=score>=threshold['decision'] if threshold else None))
                    rows.append(dict(id=key,method=method,decision_s=time/study.RATE,windows=stamps,
                        reference='owner_confirmed' if entry['row']['category']=='confusable' else 'unresolved'))
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for opt in ('archive','results','output'):p.add_argument('--'+opt,required=True,type=Path)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    study.dump(a.output,dict(rows=run(a),protocol='Raw causal PCM with no speech trimming; lengths fixed at archived decision times.'))

