"""Inspect proposed PCM boundaries with the existing local GigaAM model, without recording."""
import argparse
import json
from pathlib import Path
import re
from zipfile import ZipFile

import numpy as np
import sherpa_onnx as so

from audit_wake_study import read_audio
from wake_next12 import RATE,RING

ROOT=Path('local/wakeword26b')


def run(replay,archive):
    gm=ROOT/'gigaam-device-model'
    asr=so.OfflineRecognizer.from_transducer(encoder=str(gm/'encoder.int8.onnx'),
        decoder=str(gm/'decoder.onnx'),joiner=str(gm/'joiner.onnx'),tokens=str(gm/'tokens.txt'),
        num_threads=2,sample_rate=RATE,feature_dim=64,model_type='nemo_transducer')
    def infer(raw):
        s=asr.create_stream()
        s.accept_waveform(RATE,raw.astype(np.float32)/32768)
        asr.decode_stream(s)
        return s.result.text
    with ZipFile(archive) as bundle:
        for r in replay['inputs']:
            if r['category']!='fused':
                continue
            first=r['hits']['a_final_prefix']
            if not first:
                continue
            pcm=np.frombuffer(read_audio(bundle,r['id']+'.wav'),dtype='<i2')
            hit=first[0]
            boundary=hit['handoff']
            cand=hit.get('candidate')
            final=next(f for f in r['trace'] if f['kind']=='final' and f['sample']==hit['sample'])
            last=round(final['words'][-1]['end']*RATE)
            known={'final_last_word':last,'selected':boundary}
            if cand:
                known.update(prefix_end=cand['end'],prefix_start=cand['start'])
            ns=hit['sample']
            outcomes=[]
            for key,left in known.items():
                if not max(0,ns-RING)<=left<=min(ns,len(pcm)):
                    raise ValueError('Boundary is outside the current ring')
                # Original history through the decision, then continuous original tail.
                history=pcm[left:min(ns,len(pcm))]
                tail=pcm[ns:]
                target=np.concatenate((history,tail))
                if not np.array_equal(target,pcm[left:]):
                    raise ValueError('PCM handoff is discontinuous')
                text=infer(target)
                completed=bool(re.search(r'сколько (?:сейчас )?времени',text.lower()))
                outcomes.append(dict(mode=key,start_sample=left,queued=len(history),tail=len(tail),
                                     hypothesis=text,complete_time_command=completed,simulated_loss_samples=0))
            yield dict(id=r['id'],label=r['label'],source_samples=len(pcm),decision_sample=ns,recovered=bool(cand),outcomes=outcomes)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for field in ('replay','archive','output'):p.add_argument('--'+field,type=Path,required=True)
    a=p.parse_args()
    data=json.loads(a.replay.read_text(encoding='utf8'))
    with a.output.open('x',encoding='utf8') as f:
        json.dump(list(run(data,a.archive)),f,ensure_ascii=False,indent=2)

