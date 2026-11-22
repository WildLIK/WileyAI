"""Controlled overlap and playback-proxy checks using frozen NEXT 11.1 verification splits."""
import argparse
from importlib import import_module
import json
from pathlib import Path

import numpy as np

main=import_module('analyze-next11-speaker')


def run(args):
    root=main.ROOT
    results=json.loads((args.result/'verification.json').read_text(encoding='utf8'))
    ref=np.load(args.result/'owner-reference.npy',allow_pickle=False)
    data=json.loads((root/'next11/results/replay-results.json').read_text(encoding='utf8'))
    model=main.Model()
    owner,_=main.owner_records(args.archive,data)
    public=main.foreign_records(args.corpus,args.ffmpeg)
    def longest(records,kinds,limit,min_seconds):
        taken=[]
        for record in records:
            if record['split'] not in kinds:
                continue
            _,clean=main.windows(record['signal'],model.diarize(record['signal']))
            if len(clean)>=main.RATE*min_seconds:
                taken.append((record['id'],clean))
            if len(taken)>=limit:
                break
        return taken
    owners=longest(owner,{'test','historical'},12,1.5)
    others=longest(public,{'test'},12,2.)
    overlaps=[]
    for (oid,v),(nid,n) in zip(owners,others):
        left=np.zeros(main.RATE*4,dtype=np.float32)
        right=np.zeros_like(left)
        v=v[:min(len(v),main.RATE*2)]
        n=n[:main.RATE*2]
        # Each source has a 1s stretch alone. Align one half-second ending for the overlap.
        left_start=main.RATE//2
        left_end=left_start+len(v)
        right_start=left_end-main.RATE//2
        right_end=right_start+len(n)
        left[left_start:left_end]=v
        right[right_start:right_end]=n
        common=slice(right_start,left_end)
        right*=np.sqrt(np.mean(left[common]**2)/max(np.mean(right[common]**2),1e-9))
        turns=model.diarize(left+right)
        predicted=[(a,b) for a,b,who in main.partition(turns,4.) if len(who)>1]
        a,b=right_start/main.RATE,left_end/main.RATE
        matched=sum(max(0.,min(end,b)-max(start,a)) for start,end in predicted)
        total=sum(e-s for s,e in predicted)
        overlaps.append(dict(owner_id=oid,other_id=nid,expected_s=[a,b],predicted=predicted,
                             detected_overlap_s=matched,spurious_overlap_s=total-matched))
    proxy=[]
    duration=1.5
    threshold=results['thresholds'][str(duration)]
    if threshold:
        # Re-recording proxy. A deterministic band limit and echo, with no microphone or new recording.
        t=np.arange(-48,49)
        kernel=2*2200/16000*np.sinc(2*2200/16000*t)*np.hanning(len(t))
        kernel/=sum(kernel)
        for id,signal in owners:
            signal=signal[:round(duration*main.RATE)]
            recolored=np.convolve(signal,kernel,mode='same')
            lag=320
            recolored[lag:]+=recolored[:-lag]*.35
            before=float(model.embedding(signal)@ref)
            after=float(model.embedding(recolored.astype(np.float32))@ref)
            proxy.append(dict(id=id,clean_score=before,proxy_score=after,proxy_accepted=after>=threshold['decision']))
    main.dump(args.output,dict(overlap=overlaps,playback_proxy=proxy,
        design='Owner + independent test public speech at 0 dB in known half-second overlaps; band limit and echo as proxy for playback.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','corpus','ffmpeg','result','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    run(args)

