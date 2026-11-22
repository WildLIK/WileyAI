"""Inspect raw Reverb overlap classes around the three wake events and public-speech controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
import onnxruntime as ort

RATE=16000
MODEL=Path('local/wakeword26b/next11-speaker/models/sherpa-onnx-reverb-diarization-v1/model.int8.onnx')
CHECKSUM='b9d683988380daa45cade934279c456003a43c48a5b5d6f213b3b3d134b25027'


def session():
    if hashlib.sha256(MODEL.read_bytes()).hexdigest()!=CHECKSUM:
        raise ValueError('Unexpected Reverb model')
    options=ort.SessionOptions()
    options.intra_op_num_threads=1
    options.inter_op_num_threads=1
    return ort.InferenceSession(str(MODEL),options,providers=['CPUExecutionProvider'])


def score(model, pcm, center, truth=None):
    width=160000
    pad=round((10-len(pcm)/RATE)*RATE/2) if center else 0
    if pad<0 or pad+len(pcm)>width:
        raise ValueError('Expected at most 10 seconds')
    audio=np.zeros(width,dtype=np.float32)
    audio[pad:pad+len(pcm)]=pcm
    scores=model.run(None,{'x':audio[None,None,:]})[0][0]
    scores=np.exp(scores-scores.max(axis=1,keepdims=True))
    scores/=scores.sum(axis=1,keepdims=True)
    frames=(495+270*np.arange(len(scores))-pad)/RATE
    active=(frames>=0)&(frames<len(pcm)/RATE)
    overlap=scores[:,4:7].sum(axis=1)
    info=dict(all=int(active.sum()),overlap_frames=int(np.count_nonzero(active&(overlap>=.5))),
              maximum=float(overlap[active].max()),interval_s=270/RATE)
    if truth:
        hits=(frames>=truth[0])&(frames<truth[1])
        info.update(known_overlap_frames=int(hits.sum()),overlap_in_truth_frames=int(np.count_nonzero(hits&(overlap>=.5))))
    return info


def run(args):
    m=session()
    for clip in sorted((args.snippets or args.results/'listen').glob('*.wav')):
        with wave.open(str(clip),'rb') as file:
            pcm=np.frombuffer(file.readframes(file.getnframes()),dtype='<i2').astype(np.float32)/32768
        yield dict(case=clip.stem,result=score(m,pcm,True))
    plan=json.loads((args.results/'verification.json').read_text(encoding='utf8'))
    files={}
    for row in plan['input_roles']:
        if row['reference']=='other' and row['split']=='test' and row['longest_single_voice_s']>=2.5:
            files.setdefault(row['original_alias'],row['id'])
    pairs=list(files.values())
    for i in range(0,len(pairs)-1,2):
        def speech(name):
            pcm=subprocess.check_output([str(args.ffmpeg),'-nostdin','-v','error','-i',
                str(args.corpus/'audios'/name),'-ss','0.5','-t','3','-c:a','pcm_s16le','-f','s16le','-ar','16000','-ac','1','pipe:1'])
            p=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
            return p/np.sqrt(max(float(np.mean(p**2)),1e-10))*.06
        a,b=(speech(name) for name in pairs[i:i+2])
        for offset in (.5,1.5):
            start=round(offset*RATE)
            mixed=np.zeros(max(len(a),start+len(b))+16000,dtype=np.float32)
            mixed[:len(a)]=a
            mixed[start:start+len(b)]+=b
            known=(offset,min(len(a),start+len(b))/RATE)
            yield dict(case='independent_public_mixture',pair=pairs[i:i+2],truth_s=known,result=score(m,mixed,True,known))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for opt in ('results','corpus','ffmpeg','output'):parser.add_argument('--'+opt,required=True,type=Path)
    parser.add_argument('--snippets',type=Path)
    args=parser.parse_args()
    rows=list(run(args))
    with args.output.open('x',encoding='utf8') as f:
        json.dump(dict(method='0.5 threshold on normalized sum of classes 4–6; nominal overlap may include short speech pauses',rows=rows),f,indent=2)

