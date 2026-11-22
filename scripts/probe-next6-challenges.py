"""Frozen detector probes on generated phrases and fixed-noise archival clips."""

import argparse
from importlib import import_module
import io
from pathlib import Path
import wave
import zipfile

import numpy as np
from scipy.signal import resample_poly

from plix_next6 import PLiX, file_hash
from wake_next6 import RATE, events

probe = import_module('probe-next6-wake')
previous = probe.previous
VOICES = {
    'denis': '15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a',
    'dmitri': 'f073356ebc4bd0f80c5af58df2953a5988bd5bdab1eb38635ce960b071fbefcb',
}
LABELS = ('Вайли', 'Уайли', 'Окей, Вайли', 'Окей, Уайли')
CONFUSABLE = ('Валя', 'Вали', 'Вели', 'Вайфай', 'Ой, Валя', 'Мы говорили', 'Давай поговорим')


def piper_clips(voices):
    from piper import PiperVoice, SynthesisConfig

    for name, expected in VOICES.items():
        path = voices / name / f'ru_RU-{name}-medium.onnx'
        if file_hash(path) != expected:
            raise ValueError('Piper model checksum changed')
        voice = PiperVoice.load(path)
        for phrase in LABELS + CONFUSABLE:
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                voice.synthesize_wav(phrase, wav, SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0))
            with wave.open(io.BytesIO(output.getvalue()), 'rb') as wav:
                if (wav.getnchannels(), wav.getsampwidth()) != (1, 2):
                    raise ValueError('Expected mono PCM16')
                pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)
                pcm = np.clip(np.rint(resample_poly(pcm, RATE, wav.getframerate())), -32768, 32767).astype(np.int16)
            # Estimate usable endpoint from energy. Never use it in the detector.
            interval = RATE // 100
            chunks = pcm[:len(pcm) // interval * interval].reshape(-1, interval).astype(np.float32)
            active = np.flatnonzero(np.sqrt(np.mean(chunks * chunks, axis=1)) > 327.68)
            if not len(active):
                raise ValueError('Piper phrase has no speech')
            yield phrase, pcm, (active[-1] + 1) / 100


def add_noise(pcm, start, end, seed):
    rng = np.random.default_rng(seed)
    signal = pcm.astype(np.float32)
    word = signal[round(start * RATE):round(end * RATE)]
    sigma = np.sqrt(np.mean(word ** 2) / 10)
    return np.clip(np.rint(signal + rng.normal(0, sigma, len(pcm))), -32768, 32767).astype(np.int16)


def run(args):
    methods = {}
    for language in ('ru', 'multi'):
        path = (args.configs or args.work / 'next6') / f'{language}.config.json'
        frozen = probe.read_json(path)
        if any(file_hash(args.exports / asset) != sha for asset, sha in frozen['assets'].items()):
            raise ValueError('ONNX export changed')
        encode = PLiX(args.exports, language)
        negatives = np.array(frozen['negative_bank'], dtype=np.float32)
        for name in ('synthetic', frozen['selected']):
            prototype = np.array(frozen['variant_prototypes'][name], dtype=np.float32)
            threshold = frozen['thresholds'][name]['threshold']
            methods[f'{language}/{name}'] = (encode, prototype, negatives, threshold)

    vosk = previous.Vosk(args.work)
    metrics = {name: probe.Metrics() for name in (*methods, 'vosk')}
    synthetic = list(piper_clips(args.voices))
    splits = probe.read_json(args.work / 'b6/owner-splits.json')
    with zipfile.ZipFile(args.work / 'owner-export-20261116-184820.zip') as archive:
        held, = probe.owner_rows(args.work, archive, splits, ('test',))

    def score(clip, group, end):
        embedded = {}
        for name, (encoder, prototypes, negatives, threshold) in methods.items():
            if encoder not in embedded:
                embedded[encoder] = probe.features(encoder, clip, True)
            hits = list(events(probe.similarity(embedded[encoder], prototypes, negatives), threshold))
            metrics[name].add(group, hits, len(clip) / RATE, end)
        metrics['vosk'].add(group, vosk.run(clip.tobytes(), True), len(clip) / RATE, end)

    for phrase, pcm, end in synthetic:
        score(pcm, 'piper_' + phrase if phrase in LABELS else 'confusable', end if phrase in LABELS else None)
    for index, (_, pcm, start, end, _, _) in enumerate(held):
        score(add_noise(pcm, start, end, index), 'owner_white_noise_10db', end)
    result = {'onset_note': 'Piper use a 10-ms energy endpoint; noise uses reviewed archival bounds',
              'methods': {name: values.report() for name, values in metrics.items()}}
    probe.write_new(args.output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', default=Path('local/wakeword26b'), type=Path)
    parser.add_argument('--voices', default=Path('data/models/piper'), type=Path)
    parser.add_argument('--configs', type=Path)
    parser.add_argument('--exports', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    run(parser.parse_args())
