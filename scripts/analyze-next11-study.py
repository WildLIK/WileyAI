"""Read-only NEXT 11 paired replay of the original owner export."""
import argparse
from collections import Counter
import csv
import hashlib
from importlib import import_module
import json
from pathlib import Path
import subprocess
import os
from zipfile import ZipFile

import numpy as np
from scipy.signal import butter, correlate, resample_poly, sosfiltfilt

from audit_wake_study import inspect, owner_fingerprints, read_audio
from plix_next6 import file_hash

WORK = Path('local/wakeword26b')
RATE = 16000
METHODS = ('vosk', 'multi', 'h2')
replay = import_module('replay-wake-diagnostics')


def write_csv(path, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def possible_copies(audio):
    """Check shifted and gain-scaled repeats in speech-band waveform, ignoring low-frequency rumble."""
    band = butter(4, (250, 1800), fs=4000, btype='bandpass', output='sos')
    down = [sosfiltfilt(band, resample_poly(pcm.astype(np.float32), 1, 4)).astype(np.float32) for pcm in audio]
    width = 2000
    excerpts = []
    for signal in down:
        blocks = signal[:len(signal)//width*width].reshape(-1, width)
        candidates = sorted(blocks, key=lambda block: float(np.dot(block, block)), reverse=True)[:2]
        excerpts.append([block-np.mean(block) for block in candidates])
    pairs = []
    for i, signal in enumerate(down):
        for j, target in enumerate(down[:i]):
            strongest = 0.0
            for ref, stream in [(ref,target) for ref in excerpts[i]] + [(ref,signal) for ref in excerpts[j]]:
                energy = float(np.dot(ref,ref))
                if not energy:
                    continue
                sums = np.r_[0., np.cumsum(stream,dtype=np.float64)]
                squares = np.r_[0., np.cumsum(stream**2,dtype=np.float64)]
                norm = squares[width:]-squares[:-width]-(sums[width:]-sums[:-width])**2/width
                similarity = abs(correlate(stream,ref,mode='valid',method='fft'))/np.sqrt(np.maximum(norm*energy,1.))
                strongest = max(strongest,float(similarity.max()))
            pairs.append((strongest,j,i))
    return sorted(pairs, reverse=True)


def models():
    config = WORK/'next6/multi.config.json'
    assets = WORK/'next6/onnx'
    floor = WORK/'next7/floor.config.json'
    return dict(vosk=replay.vosk_runner(WORK/'vosk-device-model', detailed=True),
                multi=replay.plix_runner(assets, config, detailed=True),
                h2=replay.plix_runner(assets, config, detailed=True, intervention=floor))


def speech_recognizers(archive, items):
    import vosk
    gm = WORK/'gigaam-device-model'
    archived = json.loads((WORK/'next9/configs/sha256.json').read_text(encoding='utf8'))
    files = [gm/f for f in ('encoder.int8.onnx','decoder.onnx','joiner.onnx','tokens.txt')]
    if any(file_hash(p) != archived[p.as_posix()] for p in files):
        raise ValueError('GigaAM model differs from the verified local model')
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    giga = json.loads(subprocess.check_output([str(WORK/'venv/Scripts/python.exe'),'-X','utf8',
        'scripts/transcribe-next11-study.py', str(archive), *(r['member'] for r in items)], env=env))
    full = vosk.Model(str(WORK/'vosk-device-model'))

    def transcribe(pcm, member):
        unrestricted = vosk.KaldiRecognizer(full,RATE)
        unrestricted.SetWords(True)
        words = []
        for first in range(0,len(pcm),2048):
            if unrestricted.AcceptWaveform(pcm[first:first+2048].tobytes()):
                words.extend(json.loads(unrestricted.Result()).get('result', []))
        words.extend(json.loads(unrestricted.FinalResult()).get('result', []))
        return dict(giga[member],free_vosk_words=words)
    return transcribe


def run(archive, audit_csv, out):
    archived = owner_fingerprints(WORK/'owner-export-20261116-184820.zip')
    integrity, items = inspect([archive], archived)
    with audit_csv.open(encoding='utf-8-sig',newline='') as stream:
        index = list(csv.DictReader(stream))
    audit = {r['id']:r for r in index}
    if len(items)!=44 or len(index)!=44 or set(audit)!={Path(r['member']).stem for r in items}:
        raise ValueError('Expected the exact 44 linked NEXT 11 inputs')
    detectors = models()
    transcribe = speech_recognizers(archive, items)
    grammar = json.loads((WORK/'next9/timeline.json').read_text(encoding='utf8'))['events'][0]['grammar']
    results, table, signals = [], [], []
    with ZipFile(archive) as bundle:
        if bundle.testzip():
            raise ValueError('ZIP CRC failed')
        for item in items:
            sample = Path(item['member']).stem
            meta = json.loads(bundle.read(sample+'.json'))
            row = audit[sample]
            cached = meta['vosk']
            raw = np.frombuffer(read_audio(bundle,item['member']),dtype='<i2')
            prefields = ('id','session_id','speaker_id','split','kind','phrase','voice_level','environment')
            if (any(row[k]!=str(meta[k]) for k in prefields) or row['vosk_status']!=cached['status']
                or row['pcm_sha256']!=item['pcm_sha256'] or abs(float(row['duration_s'])-len(raw)/RATE)>.00051
                or float(row['distance_m'])!=meta['distance_cm']/100
                or row['confidence_milli']!=str(cached.get('confidence_milli',''))
                or row['vosk_variant']!=str(cached.get('variant','')) or cached['preset']!='вайли'):
                raise ValueError('Audit CSV differs from archive: '+sample)
            padded=np.r_[raw,np.zeros(RATE,dtype='<i2')]
            # One second of silence matches Android's collector. Separate events that need it.
            outputs={name:detector(padded,grammar,'вайли') for name,detector in detectors.items()}
            recognized=transcribe(raw,item['member'])
            floating=raw.astype(np.float64)
            rms=float(np.sqrt(np.mean(floating**2)))
            peak=int(np.abs(floating).max())
            if rms and (abs(float(row['rms_dbfs']) - 20*np.log10(rms/32768)) > .015 or int(row['peak_pcm']) != peak):
                raise ValueError('Signal levels differ from the audit CSV: '+sample)
            label = meta['label']
            category=('confusable' if label==7 else 'owner_speech' if label==6 else
                      'fused' if label in (4,5) else 'okay' if label in (2,3) else 'isolated')
            # Use the expressed phrase for grouping. Preserve raw code for legacy labels.
            phrase=meta['phrase']
            if meta['kind']=='positive':
                category='okay' if phrase.startswith('Окей') else 'fused' if ', сколько' in phrase else 'isolated'
            if meta['speaker_id'] not in {'owner','owner2','owner3'}: raise ValueError('Unmapped owner alias')
            common=dict(id=sample,session_id=meta['session_id'],original_alias=meta['speaker_id'],
                speaker='owner',speaker_role='owner',original_split=meta['split'], category=category,
                original_phrase=phrase,kind=meta['kind'],name=('Уайли' if 'Уайли' in phrase else 'Вайли') if meta['kind']=='positive' else '',
                duration_s=len(raw)/RATE,rms_dbfs=round(20*np.log10(rms/32768),2) if rms else None,
                peak_pcm=peak,clipped=int(np.count_nonzero((raw==32767)|(raw==-32768))),
                silence_frames=int(np.count_nonzero(np.mean(floating[:len(raw)//320*320].reshape(-1,320)**2,axis=1)<32**2)),
                pcm_sha256=item['pcm_sha256'],wav_sha256=hashlib.sha256(bundle.read(item['member'])).hexdigest(),
                vosk_archive=cached['status'],archive_confidence=cached.get('confidence_milli'),
                archive_variant=cached.get('variant'),gigaam=recognized['giga'],
                free_vosk=' '.join(w['word'] for w in recognized['free_vosk_words']),
                vosk_finals=' | '.join(f['text'] for f in outputs['vosk']['finals'] if f['text']),
                reviewed_wake_end_s=item['end'])
            for name, output in outputs.items():
                common[name+'_hits']=len(output['hits'])
                common[name+'_raw_hits']=sum(h<=len(raw) for h in output['hits'])
                common[name+'_repeat_hits']=max(0,len(output['hits'])-1)
                if name!='vosk':
                    common[name+'_peak']=max((s for t,s in output['scores'] if t<=len(raw)),default=None)
            table.append(common)
            results.append(dict(row=common,archive_vosk=cached,recognition=recognized,detectors=outputs,
                                recorded_at_ms=meta['recorded_at_ms']))
            signals.append(raw)
            print(f'{len(results)}/44',flush=True)
    comparison=[]
    selectors = [('positive',lambda r: r['kind']=='positive'),('negative',lambda r:r['kind']=='negative')]
    selectors += [(t,lambda r,t=t:r['category']==t) for t in ('fused','okay','isolated','confusable','owner_speech')]
    selectors += [(t,lambda r,t=t:r['name']==t) for t in ('Вайли','Уайли')]
    selectors += [(f'{c}/{n}',lambda r,c=c,n=n:r['category']==c and r['name']==n)
                  for c in ('fused','okay','isolated') for n in ('Вайли','Уайли')]
    for label, select in selectors:
        selected=[r for r in table if select(r)]
        for method in ('vosk_archive',*METHODS):
            hits=sum(r[method]=='accepted' if method=='vosk_archive' else r[method+'_hits']>0 for r in selected)
            comparison.append(dict(group=label,method=method,n=len(selected),hits=hits,misses=len(selected)-hits,
                raw_hits=sum(r[method+'_raw_hits']>0 for r in selected) if method in METHODS else '',
                repeats=sum(r[method+'_repeat_hits'] for r in selected) if method in METHODS else ''))
    pairs=possible_copies(signals)
    integrity['largest_waveform_correlations']=[dict(a=table[i]['id'],b=table[j]['id'],r=v) for v,i,j in pairs[:12]]
    integrity.update(original_aliases=dict(Counter(r['original_alias'] for r in table)),normalized_speakers=1,
                     original_splits=dict(Counter(r['original_split'] for r in table)))
    errors=[r['id'] for r in table if any((r[m+'_hits']>0)!=(r['kind']=='positive') for m in METHODS)]
    write_csv(out/'samples-analysis.csv',table)
    write_csv(out/'model-comparison.csv',comparison)
    (out/'replay-results.json').write_text(json.dumps(dict(integrity=integrity,samples=results,grammar=json.loads(grammar),
        input_sha256={'zip':file_hash(archive),'csv':file_hash(audit_csv)}),ensure_ascii=False,indent=2),encoding='utf8')
    (out/'errors.json').write_text(json.dumps(dict(ids=errors,comparison=comparison),ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('archive','audit-csv','output'):
        p.add_argument('--'+arg,required=True,type=Path)
    opts=p.parse_args()
    opts.output.mkdir()
    run(opts.archive,opts.audit_csv,opts.output)

