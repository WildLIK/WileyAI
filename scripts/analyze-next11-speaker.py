"""Offline paired speaker verification, diarization and wake event review for NEXT 11.1."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import csv
import ctypes as ct
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import time
import wave
from zipfile import ZipFile

import numpy as np
import sherpa_onnx as so
import vosk

from audit_wake_study import RATE, read_audio

ROOT = Path('local/wakeword26b')
ANCHORS = ROOT/'next11-speaker/models'
CAM = '53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b'
REVERB = 'b9d683988380daa45cade934279c456003a43c48a5b5d6f213b3b3d134b25027'
DURATIONS = (.5, 1., 1.5, 2., 3., 5.)
TARGET_IDS = ('0966f7e2','0d200936','565317e0','8bc1f186','c630110a')
DETECTION_PREFIXES = ('78168be4','b0954f45','b5b2c653','d3d17d80','f2c98ab7',*TARGET_IDS)


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def normalize(emb):
    return emb/np.linalg.norm(emb)


def speech_audio(pcm):
    return np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768


class Model:
    def __init__(self):
        embed = ANCHORS/'campplus.onnx'
        segment = ANCHORS/'sherpa-onnx-reverb-diarization-v1/model.int8.onnx'
        if sha(embed)!=CAM or sha(segment)!=REVERB:
            raise ValueError('Unverified model')
        config = so.SpeakerEmbeddingExtractorConfig(str(embed),num_threads=1)
        begin, cpu = time.perf_counter(), time.process_time()
        self.embedder = so.SpeakerEmbeddingExtractor(config)
        self.embedding_init = dict(wall_s=time.perf_counter()-begin,cpu_s=time.process_time()-cpu)
        self.cost = defaultdict(list)
        begin, cpu = time.perf_counter(), time.process_time()
        self.diarizer = so.OfflineSpeakerDiarization(so.OfflineSpeakerDiarizationConfig(
            so.OfflineSpeakerSegmentationModelConfig(
                so.OfflineSpeakerSegmentationPyannoteModelConfig(str(segment)),num_threads=1),
            config,so.FastClusteringConfig(),.2,.15))
        self.diarization_init = dict(wall_s=time.perf_counter()-begin,cpu_s=time.process_time()-cpu)

    def embedding(self, signal):
        stream=self.embedder.create_stream()
        begin,cpu=time.perf_counter(),time.process_time()
        stream.accept_waveform(RATE,signal)
        stream.input_finished()
        if not self.embedder.is_ready(stream):
            raise ValueError('Insufficient feature frames')
        value=normalize(np.asarray(self.embedder.compute(stream),dtype=np.float32))
        self.cost[round(len(signal)/RATE,2)].append([1000*(time.perf_counter()-begin),1000*(time.process_time()-cpu)])
        return value

    def diarize(self, signal):
        result=self.diarizer.process(signal)
        end=len(signal)/RATE
        return [Turn(max(s.start,0),min(s.end,end),s.speaker)
                for s in result.sort_by_start_time() if min(s.end,end)>max(s.start,0)]


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: int


def exact_slice(signal, begin, end):
    return signal[max(0,round(begin*RATE)):round(end*RATE)]


def partition(turns, length, extra=()):
    boundaries=sorted({0.,length,*extra,*(time for t in turns for time in (t.start,t.end))})
    for a,b in zip(boundaries,boundaries[1:]):
        if b<=a:
            continue
        who=sorted({t.speaker for t in turns if t.start<b-1e-6 and t.end>a+1e-6})
        yield a,b,who


def windows(signal, turns):
    """Extract one contiguous central voiced crop per recording and requested duration."""
    available=[(a,b) for a,b,who in partition(turns,len(signal)/RATE) if len(who)==1]
    if not available:
        return {},np.empty(0,dtype=np.float32)
    first,last=max(available,key=lambda p:p[1]-p[0])
    clean=exact_slice(signal,first,last)
    parts={}
    for d in DURATIONS:
        count=round(d*RATE)
        if count<=len(clean):
            start=(len(clean)-count)//2
            parts[d]=clean[start:start+count]
    return parts,clean


def owner_records(archive,replay):
    controls=[]
    long_audio={}
    with ZipFile(archive) as bundle:
        for item in replay['samples']:
            row=item['row']
            key=row['id']
            signal=speech_audio(read_audio(bundle,key+'.wav'))
            if key[:8] in TARGET_IDS:
                long_audio[key]=signal
            else:
                role={'owner':'enroll','owner2':'cal','owner3':'test'}[row['original_alias']]
                controls.append(dict(id=key,split=role,reference='owner',original_alias=row['original_alias'],signal=signal))
    previous=ROOT/'owner-export-20261116-184820.zip'
    with ZipFile(previous) as bundle:
        controls.extend(dict(id=Path(name).stem,split='historical',reference='owner',original_alias='historical_50',
                             signal=speech_audio(read_audio(bundle,name)))
                        for name in bundle.namelist() if name.endswith('.wav'))
    if len({r['id'] for r in controls})!=len(controls) or len(controls)!=89 or len(long_audio)!=5:
        raise ValueError('Unexpected owner records')
    return controls,long_audio


def foreign_records(corpus,ffmpeg):
    candidates=defaultdict(list)
    with (corpus/'ss-corpus-ru.tsv').open(encoding='utf-8-sig',newline='') as file:
        for row in csv.DictReader(file,delimiter='\t'):
            audio=corpus/'audios'/row['audio_file']
            if row['client_id'] and row['transcription'].strip() and 5000<=int(row['duration_ms'])<=24000 and audio.is_file():
                key=hashlib.sha256(('NEXT11-SV:'+row['client_id']).encode()).hexdigest()[:16]
                candidates[key].append(audio)
    for i,(key,files) in enumerate(sorted(candidates.items())):
        for audio in sorted(files,key=lambda f:hashlib.sha256(('NEXT11-SV:'+f.name).encode()).digest())[:4]:
            raw=subprocess.check_output([str(ffmpeg),'-nostdin','-v','error','-i',str(audio),'-f','s16le',
                                         '-ac','1','-ar',str(RATE),'pipe:1'],timeout=30)
            yield dict(id=audio.name,split='cal' if i%2==0 else 'test',reference='other',original_alias=key,
                       input_sha256=sha(audio),signal=speech_audio(raw))


def owner_reference(model, controls):
    vectors=[]
    for record in controls:
        signal=record['clean']
        if record['split']=='enroll' and len(signal)>=round(.35*RATE):
            vectors.append((record['id'],len(signal)/RATE,model.embedding(signal)))
    if len(vectors)<3:
        raise ValueError('Not enough enrollment clips')
    return normalize(np.mean([v for _,_,v in vectors],axis=0)),vectors


def cutoff(rows, duration):
    positive=[r['score'] for r in rows if r['split']=='cal' and r['reference']=='owner' and r['duration_s']==duration]
    negative=[r['score'] for r in rows if r['split']=='cal' and r['reference']=='other' and r['duration_s']==duration]
    if len(positive)<3 or len(negative)<3:
        return None
    unique=sorted(set(positive+negative))
    choices=[-1.]+[(a+b)/2 for a,b in zip(unique,unique[1:])]+[1.]
    def cost(t):
        return (sum(v<t for v in positive)/len(positive)+sum(v>=t for v in negative)/len(negative),
                sum(v>=t for v in negative),-t)
    best=min(choices,key=cost)
    return dict(decision=best, cautious_other=min(best,float(np.quantile(positive,.1))),
                cautious_owner=max(best,float(np.quantile(negative,.95))),
                owner_n=len(positive),other_n=len(negative))


def mix(signal, noise, snr):
    return (signal+noise*np.sqrt(np.mean(signal**2)/max(np.mean(noise**2),1e-9))*10**(-snr/20)).astype(np.float32)


def synthetic_music(count):
    x=np.arange(count)/RATE
    return sum(np.sin(2*np.pi*f*x)*c for f,c in [(147.,.1),(220.,.06),(296.,.045),(440.,.05)]) * (.7+.3*np.sin(2*np.pi*2.7*x))


def metrics(rows, thresholds):
    output=[]
    for variant in sorted({r['condition'] for r in rows}):
        for group in ('test','historical'):
            for seconds in DURATIONS:
                selected=[r for r in rows if r['split']==group and r['condition']==variant and r['duration_s']==seconds]
                owner=[r['score'] for r in selected if r['reference']=='owner']
                other=[r['score'] for r in selected if r['reference']=='other']
                train=thresholds[str(seconds)]
                output.append(dict(split=group,condition=variant,seconds=seconds,owner_n=len(owner),other_n=len(other),
                    owner_accepted=sum(s>=train['decision'] for s in owner) if train and owner else None,
                    other_accepted=sum(s>=train['decision'] for s in other) if train and other else None,
                    owner_median=float(np.median(owner)) if owner else None,other_median=float(np.median(other)) if other else None))
    return output


def label(model, reference, signal, thresholds):
    rawlen=len(signal)/RATE
    if rawlen<.5:
        return None,'insufficient',None
    exact=float(model.embedding(signal)@reference)
    # Compare an exact-sized crop with the cutoff learned for that duration.
    usable=[d for d in DURATIONS if d>=1. and round(d*RATE)<=len(signal) and thresholds[str(d)]]
    if not usable:
        return exact,'insufficient',None
    dur=max(usable)
    limit=round(dur*RATE)
    start=(len(signal)-limit)//2
    decision_score=exact if limit==len(signal) else float(model.embedding(signal[start:start+limit])@reference)
    t=thresholds[str(dur)]
    outcome=('possible_owner' if decision_score>=t['cautious_owner'] else
             'possible_other' if decision_score<t['cautious_other'] else 'uncertain')
    return exact,outcome,dict(seconds=dur,score=decision_score)


def intervals(model,reference,signal,turns,thresholds):
    for a,b,who in partition(turns,len(signal)/RATE):
        if len(who)!=1:
            yield dict(start_s=a,end_s=b,seconds=b-a,clusters=who,
                       estimate='overlap' if who else 'non_speech',score=None)
            continue
        count=max(1,int(np.ceil((b-a)/3)))
        edges=np.linspace(a,b,count+1)
        for l,r in zip(edges,edges[1:]):
            score,outcome,decision=label(model,reference,exact_slice(signal,l,r),thresholds)
            yield dict(start_s=l,end_s=r,seconds=r-l,clusters=who,estimate=outcome,score=score,decision=decision)


class ASR:
    def __init__(self):
        gm=ROOT/'gigaam-device-model'
        self.giga=so.OfflineRecognizer.from_transducer(
            encoder=str(gm/'encoder.int8.onnx'),decoder=str(gm/'decoder.onnx'),
            joiner=str(gm/'joiner.onnx'),tokens=str(gm/'tokens.txt'),num_threads=2,sample_rate=RATE,
            feature_dim=64,model_type='nemo_transducer')
        vosk.SetLogLevel(-1)
        self.full=vosk.Model(str(ROOT/'vosk-device-model'))

    def recognize(self,signal):
        stream=self.giga.create_stream()
        stream.accept_waveform(RATE,signal)
        self.giga.decode_stream(stream)
        result=stream.result
        recog=vosk.KaldiRecognizer(self.full,RATE)
        recog.SetWords(True)
        words=[]
        raw=np.clip(signal*32768,-32768,32767).astype('<i2')
        for i in range(0,len(raw),2048):
            if recog.AcceptWaveform(raw[i:i+2048].tobytes()):
                words.extend(json.loads(recog.Result()).get('result',[]))
        words.extend(json.loads(recog.FinalResult()).get('result',[]))
        return dict(giga=result.text,tokens=list(result.tokens),timestamps=list(result.timestamps),
                    free_vosk=' '.join(w['word'] for w in words))


def review_events(out,data,long_audio,model,reference,by_clip,thresholds, *, scan=True):
    directory=out/'listen'
    directory.mkdir()
    asr=ASR()
    mentions=[]
    nested=[]
    for sample in data['samples']:
        row=sample['row']
        key=row['id']
        if key not in long_audio:
            continue
        signal=long_audio[key]
        # Coarse lexical search across all five recordings. Overlap the ASR chunks around the seams.
        for start in range(0,len(signal),10*RATE) if scan else ():
            heard=asr.recognize(signal[start:start+12*RATE])
            words=heard['giga']+' / '+heard['free_vosk']
            if re.search(r'(?:вай\s*ли|уайли|wiley|уайлиаи|вайлиаи)',words.lower()):
                mentions.append(dict(id=key,start_s=start/RATE,end_s=min(len(signal),start+12*RATE)/RATE,recognition=heard))
        for method in ('h2','vosk'):
            detector=sample['detectors'][method]
            for i,at in enumerate(detector['hits'],1):
                t=at/RATE
                a,b=max(t-2.7,0),min(t+1.3,len(signal)/RATE)
                relevant=[r for r in by_clip[key] if r['start_s']<b and r['end_s']>a]
                if method=='h2':
                    core=(max(0,t-1.),t)
                else:
                    words=next(f['words'] for f in detector['finals'] if f['sample']==at)
                    core=(words[0]['start'],words[-1]['end'])
                values=[]
                for duration in (1.,1.5,2.,3.):
                    middle=(core[0]+core[1])/2
                    left=max(0.,middle-duration/2)
                    right=min(len(signal)/RATE,left+duration)
                    values.append(dict(start_s=left,end_s=right,cosine=float(model.embedding(exact_slice(signal,left,right))@reference),
                        coverage={k:sum(max(0.,min(right,r['end_s'])-max(left,r['start_s']))
                                            for r in relevant if r['estimate']==k)
                                  for k in ('overlap','non_speech','possible_owner','possible_other')},
                        cutoff=thresholds[str(duration)]))
                stem=f'{key[:8]}-{method}-{i}'
                file=directory/(stem+'.wav')
                piece=exact_slice(signal,a,b)
                with wave.open(str(file),'wb') as wav:
                    wav.setparams((1,2,RATE,0,'NONE','not compressed'))
                    wav.writeframes(np.clip(piece*32768,-32768,32767).astype('<i2').tobytes())
                nested.append(dict(id=key,detector=method,decision_s=t,core_s=core,excerpt_s=[a,b],
                    recognition=asr.recognize(piece),core_recognition=asr.recognize(exact_slice(signal,*core)),
                    scores=values,intervals=relevant,file=file.relative_to(out).as_posix(),needs_manual_review=True))
    return nested,mentions


def rss():
    class Counters(ct.Structure):
        _fields_=[('cb',ct.c_ulong),('PageFaultCount',ct.c_ulong)]+[(k,ct.c_size_t) for k in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    c=Counters()
    c.cb=ct.sizeof(c)
    kernel=ct.windll.kernel32
    kernel.GetCurrentProcess.restype=ct.c_void_p
    if not ct.windll.psapi.GetProcessMemoryInfo(ct.c_void_p(kernel.GetCurrentProcess()),ct.byref(c),c.cb):
        raise OSError('GetProcessMemoryInfo')
    return dict(rss_mib=c.WorkingSetSize/2**20,peak_rss_mib=c.PeakWorkingSetSize/2**20)


def dump(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')


def run(args):
    data=json.loads((ROOT/'next11/results/replay-results.json').read_text(encoding='utf8'))
    if sha(args.archive)!=data['input_sha256']['zip']:
        raise ValueError('Archive does not match NEXT 11')
    args.out.mkdir()
    baseline=rss()
    model=Model()
    loaded=rss()
    controls,long_audio=owner_records(args.archive,data)
    controls.extend(foreign_records(args.corpus,args.ffmpeg))
    for row in controls:
        row['windows'],row['clean']=windows(row['signal'],model.diarize(row['signal']))
    reference,enrollment=owner_reference(model,controls)
    np.save(args.out/'owner-reference.npy',reference)
    ref_seconds=sum(x[1] for x in enrollment)
    scores=[]
    for row in controls:
        print('features',row['split'],row['id'][:8],flush=True)
        if row['split']=='enroll':
            continue
        for dur,pcm in row['windows'].items():
            variants={'clean':pcm}
            if row['split']!='cal':
                rng=np.random.default_rng(112)
                variants.update(noise10=mix(pcm,rng.standard_normal(len(pcm)),10),
                                music10=mix(pcm,synthetic_music(len(pcm)),10))
            for condition,fragment in variants.items():
                scores.append(dict(id=row['id'],split=row['split'],reference=row['reference'],
                    speaker_code=row['original_alias'],duration_s=dur,condition=condition,
                    score=float(model.embedding(fragment)@reference)))
    thresholds={str(d):cutoff(scores,d) for d in DURATIONS}
    profile=dict(sha256=sha(args.out/'owner-reference.npy'),voiced_seconds=ref_seconds,
                 used=[dict(id=i,seconds=d,cosine_leave_one_out=float(v@normalize(np.mean([v2 for j,_,v2 in enrollment if j!=i],axis=0))))
                       for i,d,v in enrollment])
    dump(args.out/'verification.json',dict(profile=profile,thresholds=thresholds,metrics=metrics(scores,thresholds),rows=scores,
        input_roles=[{k:v for k,v in row.items() if k not in {'signal','windows','clean'}} |
                        dict(longest_single_voice_s=len(row['clean'])/RATE) for row in controls],
        methodology='Historical 50 and owner3 are excluded from fitting. Russian comparator split by hashed public speaker.'))
    by_clip={}
    timelines=[]
    for key,signal in long_audio.items():
        start,cpu=time.perf_counter(),time.process_time()
        turns=model.diarize(signal)
        cost=dict(wall_s=time.perf_counter()-start,cpu_s=time.process_time()-cpu)
        by_clip[key]=list(intervals(model,reference,signal,turns,thresholds))
        for row in by_clip[key]:
            row['id']=key
        timelines.append(dict(id=key,duration_s=len(signal)/RATE,turns=[t.__dict__ for t in turns],
                              intervals=by_clip[key],cost=cost))
        print('diarization',key[:8],len(by_clip[key]),flush=True)
    dump(args.out/'intervals.json',timelines)
    columns=['id','start_s','end_s','seconds','clusters','estimate','score','decision']
    with (args.out/'intervals.csv').open('x',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns)
        writer.writeheader()
        for rows in by_clip.values():
            writer.writerows(rows)
    events,mentions=review_events(args.out,data,long_audio,model,reference,by_clip,thresholds)
    dump(args.out/'wake-events.json',events)
    dump(args.out/'mentions-review.json',mentions)
    dump(args.out/'performance.json',dict(rss_before=baseline,rss_loaded=loaded,rss_after=rss(),
        embedding_init=model.embedding_init,diarization_init=model.diarization_init,
        embedding_by_duration={d:dict(n=len(times),p50_p95_wall_and_cpu_ms=np.percentile(times,[50,95],axis=0).tolist())
                               for d,times in model.cost.items()},provider='CPU',threads=1,format='[p50,p95] x [wall,cpu]'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for opt in ('archive','corpus','ffmpeg','out'):
        parser.add_argument('--'+opt,required=True,type=Path)
    run(parser.parse_args())

