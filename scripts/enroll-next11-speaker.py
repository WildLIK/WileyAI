"""Prepare a separate local research reference from a voluntarily recorded WAV."""
import argparse
from importlib import import_module
from pathlib import Path
import wave

import numpy as np

study=import_module('analyze-next11-speaker')


def enroll(source,out):
    with wave.open(str(source),'rb') as file:
        if (file.getnchannels(),file.getsampwidth(),file.getframerate())!=(1,2,16000):
            raise ValueError('Expected PCM16 mono 16 kHz')
        length=file.getnframes()
        if not 30*study.RATE<=length<=60*study.RATE:
            raise ValueError('Expected a 30–60 second recording')
        pcm=file.readframes(length)
    if len(pcm)!=2*length:
        raise ValueError('Truncated source')
    audio=study.speech_audio(pcm)
    model=study.Model()
    turns=model.diarize(audio)
    pieces=[]
    for a,b,who in study.partition(turns,len(audio)/study.RATE):
        if len(who)!=1:
            continue
        count=max(1,round((b-a)/3))
        boundaries=np.linspace(a,b,count+1)
        for first,last in zip(boundaries,boundaries[1:]):
            if last-first>=1.5:
                pieces.append((who[0],last-first,model.embedding(study.exact_slice(audio,first,last))))
    if sum(duration for _,duration,_ in pieces)<20 or len({who for who,_,_ in pieces})!=1:
        raise ValueError('Expected at least 20 s of usable single-cluster speech; review source before registering')
    ref=study.normalize(np.mean([v for _,_,v in pieces],axis=0))
    local=(study.ROOT/'next11-speaker').resolve()
    if not out.resolve().is_relative_to(local):
        raise ValueError('Keep your research reference inside the ignored local directory')
    out.mkdir()
    np.save(out/'owner-reference.npy',ref)
    study.dump(out/'profile.json',dict(source_sha256=study.sha(source),usable_seconds=sum(d for _,d,_ in pieces),
        segments=len(pieces),model_sha256=study.CAM,limitations='Research reference. Calibrate and evaluate independently.'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args()
    enroll(args.source,args.output)

