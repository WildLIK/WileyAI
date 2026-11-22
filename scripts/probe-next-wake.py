"""Offline NEXT feasibility: propose with Vosk, verify only already-arrived PCM with GigaAM.
No Android activation, transcripts, saved audio, network calls or training. Reuses B6/B10/B11.
"""
import argparse
import csv
import ctypes
import io
import json
import re
import subprocess
import time
import wave
import zipfile
from pathlib import Path

import numpy as np
import sherpa_onnx
import vosk

RATE = 16000
BLOCK = 2048
LOOKBACK = 10 * BLOCK  # 1.28 s, no future frames; one attempt per Vosk segment
KEY = re.compile(r'(?<![а-яё])(?:вайли|уайли|вай\s+ли|уай\s+ли)(?![а-яё])', re.I)


def read_json(f):
    return json.loads(f.read_text(encoding='utf-8-sig'))


def read_wav(f):
    with wave.open(f, 'rb') as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
        return w.readframes(w.getnframes())


def peak_mib():
    # Windows PROCESS_MEMORY_COUNTERS, process peak working set including DLLs and both models.
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_uint32), ('faults', ctypes.c_uint32)] + [
            (k, ctypes.c_size_t) for k in ('peak', 'rss', 'p1', 'p2', 'p3', 'p4', 'page', 'page_peak')]
    val = Counters(); val.cb = ctypes.sizeof(val)
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    if fn(ctypes.c_void_p(-1), ctypes.byref(val), val.cb):
        return round(val.peak / 1048576, 1)
    return None


class Probe:
    def __init__(self, work):
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(str(work / 'vosk-device-model'))
        self.grammar = read_json(work / 'b10/vosk-audit-summary.json')['grammar']
        self.candidates = set(self.grammar) - {'[unk]'}
        g = work / 'gigaam-device-model'
        self.verifier = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(g / 'encoder.int8.onnx'), decoder=str(g / 'decoder.onnx'),
            joiner=str(g / 'joiner.onnx'), tokens=str(g / 'tokens.txt'),
            num_threads=2, sample_rate=RATE, feature_dim=64, model_type='nemo_transducer')

    def run(self, pcm, tail=False):
        original = len(pcm) / (2 * RATE)
        if tail:  # model a listener remaining on after a positive/isolated fragment
            pcm += bytes(2 * BLOCK * 8)
        rec = vosk.KaldiRecognizer(self.model, RATE, json.dumps(self.grammar, ensure_ascii=False))
        tried = False
        candidates, hits, costs = [], [], []
        cpu, wall = time.process_time(), time.perf_counter()
        for i in range(0, len(pcm), 2 * BLOCK):
            end = min(i + 2 * BLOCK, len(pcm))
            if rec.AcceptWaveform(pcm[i:end]):
                rec.Result(); tried = False
                continue
            if tried or json.loads(rec.PartialResult()).get('partial', '') not in self.candidates:
                continue
            tried = True
            candidates.append(end / (2 * RATE))
            t = time.perf_counter()
            x = np.frombuffer(pcm[max(0, end - 2 * LOOKBACK):end], dtype='<i2').astype(np.float32) / 32768
            s = self.verifier.create_stream(); s.accept_waveform(RATE, x); self.verifier.decode_stream(s)
            elapsed = time.perf_counter() - t
            costs.append(elapsed)
            if KEY.search(s.result.text):
                hits.append({'audio_s': candidates[-1], 'verify_s': elapsed})
        return dict(audio_s=original, candidates=candidates, hits=hits, verify_s=costs,
                    wall_s=time.perf_counter()-wall, cpu_s=time.process_time()-cpu)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('work', 'corpus', 'ffmpeg', 'output'):
        p.add_argument('--'+k, type=Path, required=True)
    p.add_argument("--continuous-only", action="store_true")
    a = p.parse_args(); w = a.work
    root = Path(__file__).resolve().parents[1]
    t = time.perf_counter(); engine = Probe(w)
    out = dict(load_s=time.perf_counter()-t, grammar=engine.grammar, block=BLOCK,
               lookback=LOOKBACK, groups={})
    groups = out['groups']
    def run(group, pcm, **metadata):
        groups.setdefault(group, []).append({**engine.run(pcm, group != 'negative'), **metadata})
    def decode(name, start=0., length=30.):
        return subprocess.run([str(a.ffmpeg),'-nostdin','-loglevel','error','-ss',str(start),'-t',str(length),
            '-i',str(a.corpus/'audios'/name),'-f','s16le','-ac','1','-ar','16000','pipe:1'],
            stdout=subprocess.PIPE,check=True,timeout=60).stdout
    if a.continuous_only:
        clips = read_json(w/'b6/negative-manifest.json')['test']
        # Preserve recognizer and block boundaries across joins; no padding or resets.
        pcm = b''.join(decode(row['audio_file']) for row in clips)
        groups['continuous_spliced'] = [engine.run(pcm)]
        save(a.output, out)
        return
    splits = read_json(w/'b6/owner-splits.json')
    with (w/'owner-annotations-reviewed.csv').open(encoding='utf-8-sig') as f:
        rows = {r['id']:r for r in csv.DictReader(f)}
    with zipfile.ZipFile(w/'owner-export-20261116-184820.zip') as z:
        for role, ids in splits.items():
            if role not in ('train','validation','test'): continue
            for uid in ids:
                r = rows[uid]; assert r['status']=='confirmed'
                start, end = float(r['wake_start_s']), float(r['wake_end_s'])
                pcm = read_wav(io.BytesIO(z.read(uid+'.wav')))
                run('owner_'+role, pcm, start_s=start, end_s=end)
                run('prefix_only', pcm[:2*round(RATE*(start+end)/2)])
    for r in read_json(w/'b11/synthetic-catalog.json')['records']:
        run('synthetic_'+r['declared_variant'], read_wav(str(root/'WileyAI21Голос'/r['wav_path'])),
            energy_end_s=r['end_energy_s'])
    for e in read_json(w/'b10/vosk-final-events.json'):
        start = max(0., e['word_start_s']-.5); end = min(e['time_s']+.4,e['word_end_s']+.6)
        run('hard_overlap',decode(e['source'],start,max(.2,end-start)))
    for r in read_json(w/'b6/negative-manifest.json')['test']:
        run('negative',decode(r['audio_file']))
    save(a.output, out)


def save(output, out):
    out['peak_mib'] = peak_mib()
    output.parent.mkdir(exist_ok=True,parents=True)
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    for g,items in out['groups'].items():
        print(g,len(items),sum(len(i['candidates']) for i in items),sum(len(i['hits']) for i in items))


if __name__ == '__main__': main()
