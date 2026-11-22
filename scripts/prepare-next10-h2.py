"""Freeze the existing H2, export private probe assets and PCM parity fixtures locally."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from plix_next6 import PLiX, file_hash
from wake_next6 import unit, open_scores
from wake_next7 import filtered_logmel

BASE = '428d30048347b72ba75c006f8587d0220f0d319574bb8f5c1dfbd0c36c0beafb'
H2 = '19329c2fbf116107abbff7ba4b7f1285af842e94cf578d4e9240cffd018962c4'


def prepare(work, apk, out):
    config = work / 'next6/multi.config.json'
    intervention = work / 'next7/floor.config.json'
    hashes = json.loads((work / 'next9/configs/sha256.json').read_text(encoding='utf8'))
    if file_hash(config) != BASE or file_hash(intervention) != H2:
        raise ValueError('Frozen configuration changed')
    frozen = json.loads(config.read_text())
    exports = work / 'next6/onnx'
    score_config = json.loads(intervention.read_text())
    owner = work / 'owner-export-20261116-184820.zip'
    hashes[owner.as_posix()] = frozen['owner_archive_sha256']
    hashes[(work/'owner-annotations-reviewed.csv').as_posix()] = frozen['annotations_sha256']
    sources = [config, intervention, work / 'next6/small_multi_model.pt', owner,
               work / 'owner-annotations-reviewed.csv', work / 'b6/owner-splits.json',
               *(exports / n for n in frozen['assets'])]
    verified = {}
    for path in sources:
        digest = file_hash(path)
        if hashes[path.as_posix()] != digest:
            raise ValueError('Frozen input changed: ' + path.name)
        verified[path.name] = digest
    anchors = np.array(frozen['variant_prototypes']['3'], dtype='<f4')
    negatives = np.array(frozen['negative_bank'], dtype='<f4')
    if anchors.shape != (2, 1280) or negatives.shape != (386, 1280):
        raise ValueError('Unexpected reference bank shape')
    model = PLiX(exports, 'multi')
    out.mkdir(parents=True, exist_ok=True)
    filters = model.hann.astype('<f4').tobytes() + model.filters.astype('<f4').tobytes()
    bank = anchors.tobytes() + negatives.tobytes()
    # The NEXT 7 fixtures contain synthetic Piper and silence only. Read just their PCM.
    past = work / 'next7/device/fixtures.bin'
    with past.open('rb') as old, (out/'fixtures.bin').open('xb') as stream:
        if old.read(len(filters)) != filters:
            raise ValueError('Fixture frontend mismatch')
        count = int.from_bytes(old.read(4), 'little')
        if count != 5:
            raise ValueError('Unexpected fixture count')
        stream.write(filters + count.to_bytes(4, 'little'))
        for _ in range(count):
            pcm_bytes = old.read(32000)
            old.seek(4 * (64*101 + 1280), 1)
            pcm = np.frombuffer(pcm_bytes, dtype='<i2')
            feature = filtered_logmel(pcm, model.hann, model.filters)
            embedding = model.runtime.run(['embedding'], {'logmel':feature})[0]
            score = open_scores(unit(embedding), anchors, negatives)
            stream.write(pcm_bytes + feature.astype('<f4').tobytes() + embedding.astype('<f4').tobytes() + score.astype('<f4').tobytes())
        if old.tell() != past.stat().st_size:
            raise ValueError('Invalid NEXT 7 fixtures')
    with zipfile.ZipFile(apk) as bundle:
        runtime = bundle.read('lib/arm64-v8a/libonnxruntime.so')
    private = {'filters.bin':filters, 'head.bin':bank, 'multi.onnx':(exports/'multi.onnx').read_bytes(),
               'libonnxruntime.so':runtime}
    for name, data in private.items():
        with (out/name).open('xb') as f:
            f.write(data)
    lock = dict(sources=verified, device_assets={k:hashlib.sha256(v).hexdigest() for k,v in private.items()},
                apk_sha256=file_hash(apk), fixture_sha256=file_hash(out/'fixtures.bin'), parameters=score_config,
                hop_samples=1280, positive_rows=len(anchors), negative_rows=len(negatives),
                thresholds_decided_before_collection=True)
    (out/'lock.json').write_text(json.dumps(lock, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('local/wakeword26b'))
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    prepare(a.work, a.apk, a.output)

