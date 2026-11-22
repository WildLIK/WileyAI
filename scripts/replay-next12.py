"""Causal comparison on the owner archive, a historical control and independently selected public speech."""
import argparse
from collections import Counter
import csv
import hashlib
from importlib import import_module
import io
import json
from pathlib import Path
import re
import subprocess
import time
from zipfile import ZipFile

import numpy as np
import psutil
import vosk

from audit_wake_study import read_audio
from wake_next6 import HOP, events, open_scores
from wake_next12 import RATE,BLOCK,PARAMS,RING,StablePartial,confirm,parse
from plix_next6 import PLiX,file_hash

ROOT=Path('local/wakeword26b')
ARCHIVE_HASH='4fd75745f4997f1628ed33e2c105ae5f900a284b7846a24aefa75bac9d5cbcb8'
METHODS=('vosk','a_final_prefix','b_plix_confirmation','c_partial','multi')
base=import_module('replay-wake-diagnostics')


def new_negative_plan(corpus):
    recent=[ROOT/'next10/negative-plan.json',ROOT/'next11-speaker/results/verification.json']
    for folder in [ROOT,*(ROOT/n for n in ('b6','b7','b8','b9','b10','b11','next','next5','next6','next7','next8','next9'))]:
        recent.extend(f for f in folder.iterdir() if f.suffix in ('.csv','.json','.jsonl','.tsv') and f.stat().st_size<50000000)
    known={item.decode() for f in recent for item in re.findall(rb'spontaneous-speech-ru-[0-9]+\.mp3',f.read_bytes())}
    with (corpus/'ss-corpus-ru.tsv').open(encoding='utf-8-sig',newline='') as f:
        manifest=list(csv.DictReader(f,delimiter='\t'))
    registered=json.loads((ROOT/'b6/negative-manifest.json').read_text())
    train={m['audio_file'] for rows in registered.values() if isinstance(rows,list) for m in rows if 'audio_file' in m}
    trained_speakers={row['client_id'] for row in manifest if row['audio_file'] in train}
    counts=Counter()
    selected=[]
    for r in sorted(manifest,key=lambda r:hashlib.sha256(('WileyAI NEXT12 fixed:'+r['audio_file']).encode()).digest()):
        audio=corpus/'audios'/r['audio_file']
        speaker=r['client_id']
        if (not speaker or speaker in trained_speakers or not 5_000<=int(r['duration_ms'])<=45_000
                or counts[speaker]>=16 or r['audio_file'] in known or not audio.is_file()
                or not r['transcription'].strip()
                or re.search(r'вай\s*ли|уайли|wiley',r['transcription'],re.I)):
            continue
        counts[speaker]+=1
        selected.append(dict(file=audio.name,speaker=hashlib.sha256(speaker.encode()).hexdigest()[:16],sha256=file_hash(audio)))
        if len(selected)==48:
            break
    if not selected:
        raise ValueError('No separately recorded public controls')
    return dict(rule='Files absent from available earlier manifests; distinct from PLiX data speakers; no wake phrases in the transcript.',
                files=selected,params=PARAMS,rule_sha256=file_hash(Path('scripts/wake_next12.py')),
                experiment_sha256=file_hash(Path('scripts/replay-next12.py')))


def negative_items(path, corpus, ffmpeg):
    lock=json.loads(path.read_text(encoding='utf8'))
    if (lock['rule_sha256']!=file_hash(Path('scripts/wake_next12.py')) or
            lock['experiment_sha256']!=file_hash(Path(__file__))):
        raise ValueError('Experimental rules changed since selection')
    for item in lock['files']:
        file=corpus/'audios'/item['file']
        if file_hash(file)!=item['sha256']:
            raise ValueError('Audio changed after selection')
        audio=subprocess.check_output([str(ffmpeg),'-nostdin','-v','error','-i',str(file),'-ar','16000','-ac','1',
                                      '-c:a','pcm_s16le','-f','s16le','pipe:1'])
        yield dict(id=file.name,category='ordinary_other',expected=False,speaker=item['speaker']), np.frombuffer(audio,dtype='<i2')


def owner_items(archive, group):
    if group=='development':
        if file_hash(archive)!=ARCHIVE_HASH:
            raise ValueError('Wrong NEXT 11 file')
        current=json.loads((ROOT/'next11/results/replay-results.json').read_text(encoding='utf8'))
        records=[s['row'] for s in current['samples']]
    else:
        with (ROOT/'owner-annotations-reviewed.csv').open(encoding='utf-8-sig',newline='') as f:
            records=[dict(id=m['id'],kind='positive',category='historical',original_phrase=m['phrase'],
                          verified_end_s=float(m['wake_end_s']),verified_start_s=float(m['wake_start_s']))
                     for m in csv.DictReader(f) if m['status']=='confirmed']
    with ZipFile(archive) as bundle:
        for r in records:
            meta=dict(id=r['id'],category=r['category'],expected=r['kind']=='positive',label=r['original_phrase'])
            meta.update({k:v for k,v in r.items() if k.startswith('verified_')})
            raw=read_audio(bundle,r['id']+'.wav')
            if group=='development' and hashlib.sha256(raw).hexdigest()!=r['pcm_sha256']:
                raise ValueError('File mismatch')
            yield meta,np.frombuffer(raw,dtype='<i2')


class Rig:
    def __init__(self,grammar):
        start=time.perf_counter()
        vosk.SetLogLevel(-1)
        self.model=vosk.Model(str(ROOT/'vosk-device-model'))
        proc=psutil.Process()
        self.vosk_load_ms=1000*(time.perf_counter()-start)
        self.vosk_rss_mib=proc.memory_info().rss/2**20
        self.grammar=grammar
        start=time.perf_counter()
        exports=ROOT/'next6/onnx'
        conf=ROOT/'next6/multi.config.json'
        if file_hash(conf)!=base.FROZEN_HEAD:
            raise ValueError('Frozen PLiX config changed')
        frozen=json.loads(conf.read_text(encoding='utf8'))
        if any(file_hash(exports / name)!=digest for name,digest in frozen['assets'].items()):
            raise ValueError('Frozen PLiX weights changed')
        self.encoder=PLiX(exports,'multi')
        self.pos=np.array(frozen['variant_prototypes']['3'],dtype=np.float32)
        self.neg=np.array(frozen['negative_bank'],dtype=np.float32)
        self.threshold=frozen['thresholds']['3']['threshold']
        self.multi_load_ms=1000*(time.perf_counter()-start)
        self.multi_rss_mib=proc.memory_info().rss/2**20

    def plix_windows(self, pcm, where):
        scores=[]
        for end in where:
            window=np.zeros(RATE,dtype=np.int16)
            from_index=max(0,end-RATE)
            tail=pcm[from_index:end]
            window[-len(tail):]=tail
            emb=self.encoder(window)
            scores.append((end/RATE,float(open_scores(emb[None,:],self.pos,self.neg)[0])))
        return [round(t*RATE) for t in events(scores,self.threshold)]

    def run(self, raw, pad):
        pcm=np.r_[raw,np.zeros(RATE,dtype='<i2')] if pad else raw
        hits={m:[] for m in METHODS}
        cpu=Counter()
        attempted=0
        t0=time.process_time()
        decoder=vosk.KaldiRecognizer(self.model,RATE,self.grammar)
        decoder.SetWords(True)
        cpu['vosk']+=time.process_time()-t0
        trace=[]
        prefix_wall=0.
        for start in range(0,len(pcm),BLOCK):
            stop=min(len(pcm),start+BLOCK)
            t0=time.process_time()
            complete=decoder.AcceptWaveform(pcm[start:stop].tobytes())
            final=json.loads(decoder.Result()) if complete else None
            cpu['vosk']+=time.process_time()-t0
            if final is None:
                continue
            words=final.get('result',[])
            label=final.get('text','')
            confidence=min((w.get('conf',0) for w in words),default=0)
            start_exact=time.process_time()
            exact=.75<=confidence<=1 and base.exact_wake(label,'вайли')
            cpu['vosk']+=time.process_time()-start_exact
            trace.append(dict(kind='final',sample=stop,text=label,words=words,accepted=exact))
            if exact:
                end=round(words[-1]['end']*RATE)
                hit=dict(sample=stop,why='baseline',handoff=end)
                for m in ('vosk','a_final_prefix','b_plix_confirmation'):
                    hits[m].append(hit)
            else:
                start_extra=time.process_time()
                start_wall=time.perf_counter()
                candidate=parse(words,stop,ambiguous=True)
                if candidate is not None and candidate.handoff>=max(0,stop-RING):
                    hit=dict(sample=stop,why='bounded_suffix',candidate=candidate.__dict__,handoff=candidate.handoff)
                    hits['a_final_prefix'].append(hit)
                cpu['prefix_extra']+=time.process_time()-start_extra
                prefix_wall+=time.perf_counter()-start_wall
                if candidate is not None:
                    # Start before the confirmation interval so the stable-window state is initialized consistently.
                    begin=time.process_time()
                    first=max(HOP,((candidate.end-PARAMS['multi_left'])//HOP-2)*HOP)
                    last=min(stop,candidate.end+PARAMS['multi_right'])
                    local=self.plix_windows(pcm,range(first,last+1,HOP))
                    attempted+=1
                    if any(confirm(candidate,h) for h in local) and candidate.handoff>=max(0,stop-RING):
                        hits['b_plix_confirmation'].append(dict(hit,evidence_samples=local))
                    cpu['candidate_plix_extra']+=time.process_time()-begin
        del decoder
        t0=time.process_time()
        hits['c_partial'],partial_trace=self.partial_run(pcm)
        cpu['c_partial_total']+=time.process_time()-t0
        t0=time.process_time()
        hits['multi']=[dict(sample=t,why='multi') for t in self.plix_windows(pcm,range(HOP,len(pcm)+1,HOP))]
        cpu['multi']+=time.process_time()-t0
        return dict(hits=hits,trace=trace,partial_trace=partial_trace,cpu_s=dict(cpu),prefix_wall_s=prefix_wall,
                    confirmation_requests=attempted,samples=len(raw))

    def partial_run(self, pcm):
        decoder=vosk.KaldiRecognizer(self.model,RATE,self.grammar)
        decoder.SetWords(True)
        decoder.SetPartialWords(True)
        trace=[]
        hits=[]
        seen=False
        last=''
        stable=StablePartial()
        for start in range(0,len(pcm),BLOCK):
            stop=min(len(pcm),start+BLOCK)
            if decoder.AcceptWaveform(pcm[start:stop].tobytes()):
                final=json.loads(decoder.Result())
                words=final.get('result',[])
                text=final.get('text','')
                conf=min((w.get('conf',0) for w in words),default=0)
                accepted=.75<=conf<=1 and base.exact_wake(text,'вайли')
                trace.append(dict(kind='final',sample=stop,text=text,words=words,accepted=accepted))
                if accepted and not seen:
                    hits.append(dict(sample=stop,why='baseline',handoff=round(words[-1]['end']*RATE)))
                stable=StablePartial()
                seen=False
                last=''
                continue
            partial=json.loads(decoder.PartialResult())
            text=partial.get('partial','')
            words=partial.get('partial_result',[])
            candidate=stable.update(words,stop)
            if text!=last:
                trace.append(dict(kind='partial',sample=stop,text=text,words=words))
                last=text
            if candidate and not seen:
                hits.append(dict(sample=stop,why='stable_partial',candidate=candidate.__dict__,handoff=candidate.handoff))
                seen=True
        return hits,trace


def run(args):
    grammar=json.dumps(json.loads((ROOT/'next11/results/replay-results.json').read_text(encoding='utf8'))['grammar'],
                       ensure_ascii=False)
    model=Rig(grammar)
    items=negative_items(args.manifest,args.corpus,args.ffmpeg) if args.group=='public' else owner_items(args.archive,args.group)
    results=[]
    begin=time.perf_counter()
    for meta,pcm in items:
        r=model.run(pcm,args.group!='public')
        results.append(dict(meta,**r))
        print(meta['id'][:15],len(results),flush=True)
    data=dict(group=args.group,params=PARAMS,inputs=results,model={k:v for k,v in vars(model).items()
              if k.endswith(('mib','ms'))}, wall_s=time.perf_counter()-begin,
              memory_end_rss_mib=psutil.Process().memory_info().rss/2**20)
    with args.output.open('x',encoding='utf8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('group',choices=('freeze','development','historical','public'))
    for option in ('corpus','archive','manifest','ffmpeg','output'):
        p.add_argument('--'+option,type=Path)
    args=p.parse_args()
    if args.group=='freeze':
        lock=new_negative_plan(args.corpus)
        with args.output.open('x',encoding='utf8') as stream:
            json.dump(lock,stream,ensure_ascii=False,indent=2)
    else:
        run(args)

