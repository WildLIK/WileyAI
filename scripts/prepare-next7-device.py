"""Prepare synthetic-only PCM fixtures and extract the APK's arm64 ONNX Runtime."""

import argparse
from importlib import import_module
from pathlib import Path
import zipfile

import numpy as np

from plix_next6 import PLiX, file_hash, logmel
from wake_next6 import RATE
from wake_next7 import causal_window


def prepare(args):
    origin = args.exports / 'multi.onnx'
    expected = '6258bf82d30870e240e5927dd06987170c1dc3615dcaf0c95071ccceacdacb49'
    if file_hash(origin) != expected:
        raise ValueError('Expected the frozen NEXT 6 MULTI graph')
    model = PLiX(args.exports, 'multi')
    fixture = [np.zeros(RATE, dtype=np.int16)]
    generator = import_module('probe-next6-challenges')
    for phrase, pcm, end in generator.piper_clips(args.voices):
        if phrase in generator.LABELS:
            fixture.append(causal_window(pcm, round((end + .16) * RATE)))
        if len(fixture) == 5:
            break
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'fixtures.bin').open('xb') as stream:
        stream.write(model.hann.astype('<f4').tobytes())
        stream.write(model.filters.astype('<f4').tobytes())
        stream.write(np.array([len(fixture)], dtype='<u4').tobytes())
        for pcm in fixture:
            stream.write(pcm.astype('<i2').tobytes())
            stream.write(logmel(pcm, model.hann, model.filters).astype('<f4').tobytes())
            stream.write(model.raw_embedding(pcm).astype('<f4').tobytes())
    with zipfile.ZipFile(args.apk) as apk:
        arm64 = apk.read('lib/arm64-v8a/libonnxruntime.so')
    for name, packed in (('libonnxruntime.so', arm64), ('multi.onnx', origin.read_bytes())):
        with (args.output / name).open('xb') as stream:
            stream.write(packed)
        print(name, file_hash(args.output / name))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voices', type=Path, default=Path('data/models/piper'))
    for name in ('exports', 'apk', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    prepare(parser.parse_args())
