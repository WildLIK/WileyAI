"""File-independent Common Voice negative control. Freeze selection before decoding."""
import argparse
import collections
import csv
import hashlib
import json
import re
import subprocess
import time
from importlib import import_module
from pathlib import Path

import numpy as np

replay = import_module('replay-wake-diagnostics')
one = import_module('probe-next10-context').single
WORK = Path('local/wakeword26b')


def choose(corpus):
    old = set()
    for folder in [WORK, *(WORK/n for n in ('b6','b7','b8','b9','b10','b11','next','next5','next6','next7','next8','next9'))]:
        for f in folder.iterdir():
            if f.suffix in ('.csv','.json','.jsonl','.tsv') and f.stat().st_size < 50000000:
                old.update(s.decode() for s in re.findall(rb'spontaneous-speech-ru-[0-9]+\.mp3',f.read_bytes()))
    with (corpus/'ss-corpus-ru.tsv').open(encoding='utf-8-sig',newline='') as f:
        catalog=list(csv.DictReader(f,delimiter='\t'))
    trained=json.loads((WORK/'b6/negative-manifest.json').read_text())
    used={r['audio_file'] for subset in trained.values() if isinstance(subset,list) for r in subset if 'audio_file' in r}
    speakers={r['client_id'] for r in catalog if r['audio_file'] in used}
    previous_speakers={r['client_id'] for r in catalog if r['audio_file'] in old}
    selected=[]
    durations=collections.Counter()
    for r in sorted(catalog,key=lambda r:hashlib.sha256(('NEXT10-fixed:'+r['audio_file']).encode()).digest()):
        transcript=r['transcription'].strip().lower()
        if (not transcript or any(word in transcript for word in ('вайли','уайли','вай ли','уай ли','wiley'))
                or not r['client_id'] or r['client_id'] in speakers or r['audio_file'] in old
                or not (corpus/'audios'/r['audio_file']).is_file() or durations[r['client_id']]>=360):
            continue
        durations[r['client_id']]+=int(r['duration_ms'])/1000
        selected.append(dict(file=r['audio_file'],speaker=hashlib.sha256(r['client_id'].encode()).hexdigest()[:16],
            speaker_in_other_old_research=r['client_id'] in previous_speakers,
            file_sha256=hashlib.sha256((corpus/'audios'/r['audio_file']).read_bytes()).hexdigest()))
    return dict(rule='Exclude files in previous local manifests, H2 corpus speakers and transcripts containing wake word; fixed hash order up to 360s/speaker, whole clips.',files=selected)


def run(corpus, manifest, ffmpeg):
    config=WORK/'next6/multi.config.json'; exports=WORK/'next6/onnx'
    vosk=replay.vosk_runner(WORK/'vosk-device-model')
    models={'vosk':vosk,'multi':replay.plix_runner(exports,config),'h2':replay.plix_runner(exports,config,detailed=True,intervention=WORK/'next7/floor.config.json')}
    grammar=json.loads((WORK/'next9/timeline.json').read_text(encoding='utf8'))['events'][0]['grammar']
    results=[]
    for row in manifest['files']:
        path=corpus/'audios'/row['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['file_sha256']: raise ValueError('Changed file')
        raw=subprocess.run([str(ffmpeg),'-v','error','-i',str(path),'-ar','16000','-ac','1','-f','s16le','pipe:1'],check=True,capture_output=True).stdout
        pcm=np.frombuffer(raw,dtype='<i2'); record=dict(file=row['file'],samples=len(pcm),hits={},cpu_s={})
        for name,model in models.items():
            start=time.process_time(); out=model(pcm,grammar,'вайли')
            record['cpu_s'][name]=time.process_time()-start
            if name=='h2':
                record['hits']['one']=[round(t*16000) for t in one([(p/16000,s) for p,s in out['scores']],out['threshold'])]
                out=out['hits']
            record['hits'][name]=out
        results.append(record)
    return dict(files=results,seconds=sum(r['samples'] for r in results)/16000,
        counts={k:sum(len(r['hits'][k]) for r in results) for k in ('vosk','multi','h2','one')},independent_of='H2 registration and calibration; complete separate source files, not an ambient phone recording')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('stage',choices=('freeze','run'))
    p.add_argument('--corpus',required=True,type=Path);p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--ffmpeg',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    if a.stage=='freeze':
        with a.manifest.open('x',encoding='utf8') as out: json.dump(choose(a.corpus),out,indent=2)
    else:
        result=run(a.corpus,json.loads(a.manifest.read_text()),a.ffmpeg)
        with a.output.open('x',encoding='utf8') as out: json.dump(result,out,indent=2)

