"""PLiX retrospective streaming benchmark with frozen three-way data partitions."""

import argparse
from collections import Counter, defaultdict
from importlib import import_module
from itertools import islice
import io
import json
from pathlib import Path
import time
import wave
import zipfile

import numpy as np

from plix_next6 import PLiX, file_hash
from wake_next6 import (AudioWindows, HOP, RATE, choose_threshold, completed_hit, events,
                        open_scores, split_inputs, unit)

previous = import_module('probe-next5-wake')
read_json, rows, write_new, memory = previous.read_json, previous.rows, previous.write_new, previous.memory
COUNTS = (3, 5, 10)
CAL_SOURCE = 'Timbrica'
TEST_SOURCE = 'TTSMaker'
OFFSET = 0.16


def read_pcm(stream):
    with wave.open(stream, 'rb') as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError('Expected 16 kHz mono PCM16')
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')


def push(stream, pcm, pad):
    for start in range(0, len(pcm), 2048):
        yield from stream.feed(pcm[start:start + 2048])
    if pad:
        yield from stream.feed(np.zeros(RATE, dtype=np.int16))


def features(encode, pcm, pad=False, *, stream=None, stride=1):
    frames = push(stream if stream is not None else AudioWindows(), pcm, pad)
    return [(end / RATE, encode(window)) for end, window in islice(frames, 0, None, stride)]


def register(encode, pcm, start, end):
    # Present the isolated name once, with the same left context length as a rolling window.
    word = pcm[round(start * RATE):round(end * RATE)]
    remaining = round(OFFSET * RATE)
    if not 0 < len(word) <= RATE - remaining:
        raise ValueError('Invalid registration word interval')
    isolated = np.zeros(RATE, dtype=np.int16)
    isolated[-len(word) - remaining:-remaining] = word
    return encode(isolated)


def similarity(data, prototypes, distractors):
    if not data:
        return []
    seconds, embeddings = zip(*data)
    values = open_scores(np.stack(embeddings), prototypes, distractors)
    return list(zip(seconds, values))


def owner_rows(work, archive, splits, order=('train', 'validation', 'test')):
    labeled = {row['id']: row for row in rows(work / 'owner-annotations-reviewed.csv')}
    split_inputs(splits, set(labeled))
    for split in order:
        values = []
        for key in splits[split]:
            row = labeled[key]
            if row['status'] != 'confirmed':
                raise ValueError('Expected confirmed owner annotation')
            with io.BytesIO(archive.read(key + '.wav')) as wave_file:
                pcm = read_pcm(wave_file)
            item = (key, pcm, float(row['wake_start_s']), float(row['wake_end_s']),
                    json.loads(archive.read(key + '.json')).get('condition', ''), row['phrase'])
            values.append(item)
        yield values


def positives(encode, records):
    return [(end, features(encode, pcm, pad=True)) for _, pcm, _, end, _, _ in records]


def prefixes(encode, records):
    return [features(encode, pcm[:round((start + end) / 2 * RATE)], pad=True)
            for _, pcm, start, end, _, _ in records]


class Metrics:
    def __init__(self):
        self.counts = defaultdict(Counter)
        self.lag = defaultdict(list)

    def add(self, group, hits, seconds, end=None):
        count = self.counts[group]
        count['clips'] += 1
        count['seconds'] += seconds
        count['events'] += len(hits)
        count['clips_with_events'] += bool(hits)
        if end is not None:
            disposition, delay = completed_hit(hits, end)
            count[disposition] += 1
            if delay is not None:
                self.lag[group].append(delay)

    def report(self):
        result = {}
        for group, count in self.counts.items():
            result[group] = {**dict(count), 'seconds': round(count['seconds'], 3),
                             'lag': previous.summary(self.lag[group])}
            if group.startswith('negative_') and count['seconds']:
                result[group]['events_per_hour'] = round(count['events'] * 3600 / count['seconds'], 2)
        return result


def controls(args):
    import hashlib

    load_seconds = time.perf_counter()
    method = previous.Vosk(args.work) if args.method == 'vosk' else previous.Acoustic(args.work / 'next5')
    if args.method == 'next5':
        head = args.work / 'next5/acoustic.head.json'
        if hashlib.sha256(head.read_bytes()).hexdigest() != 'a06ba43d141b561a8a05ddd53d9c484b992e60ac4c2f8adb1369a1e79c259c30':
            raise ValueError('NEXT 5 calibration changed')
        frozen = read_json(head)
        method.weights = np.array(frozen['weights'])
        method.threshold = frozen['threshold']
    load_seconds = time.perf_counter() - load_seconds
    splits = read_json(args.work / 'b6/owner-splits.json')
    with zipfile.ZipFile(args.work / 'owner-export-20261116-184820.zip') as archive:
        test, = owner_rows(args.work, archive, splits, ('test',))
    metric = Metrics()
    for _, pcm, start, end, condition, phrase in test:
        hits = method.run(pcm.tobytes(), True)
        tally_owner(metric, hits, pcm, end, condition, phrase)
        prefix = pcm[:round((start + end) / 2 * RATE)]
        metric.add('owner_half_word', method.run(prefix.tobytes(), True), len(prefix) / RATE)
    timing = {}
    if args.corpus is not None and args.ffmpeg is not None:
        cv = read_json(args.work / 'b6/negative-manifest.json')
        pcm = bytearray()
        for row in cv['test']:
            pcm.extend(previous.decode(args, row))
        audio = bytes(pcm)
        del pcm
        cpu, wall = time.process_time(), time.perf_counter()
        hits = method.run(audio, False)
        metric.add('negative_continuous', hits, len(audio) / (2 * RATE))
        timing = {'continuous_cpu_s': time.process_time() - cpu, 'continuous_wall_s': time.perf_counter() - wall}
    write_new(args.output, {'method': args.method, 'load_s': load_seconds, 'groups': metric.report(), 'timing': timing})


def tally_owner(metric, hits, pcm, end, condition, phrase):
    metric.add('owner_test', hits, len(pcm) / RATE, end)
    if condition in ('с паузой перед командой', 'слитно с командой'):
        metric.add('owner_' + ('pause' if condition.startswith('с паузой') else 'joined'), hits, len(pcm) / RATE, end)
    if phrase.startswith('Окей'):
        metric.add('owner_okay', hits, len(pcm) / RATE, end)
    if condition == 'тихо':
        metric.add('owner_quiet', hits, len(pcm) / RATE, end)


def run(args):
    folder = args.exports
    manifest = read_json(folder / f'{args.method}-export.json')
    if any(file_hash(folder / filename) != sha for filename, sha in manifest['assets_sha256'].items()):
        raise ValueError('Exported ONNX or frontend data changed')
    before = memory()
    started = time.perf_counter()
    encode = PLiX(folder, args.method)
    load_seconds = time.perf_counter() - started
    after_load = memory()
    work = args.work
    splits = read_json(work / 'b6/owner-splits.json')
    archive_path = work / 'owner-export-20261116-184820.zip'
    with zipfile.ZipFile(archive_path) as archive:
        train, validate = owner_rows(work, archive, splits, ('train', 'validation'))
    catalog = read_json(work / 'b11/synthetic-catalog.json')['records']

    def synthetic(row):
        return (row['id'], read_pcm(str(args.synthetic / row['wav_path'])), row['start_energy_s'],
                row['end_energy_s'], row['source'], row['declared_variant'])

    synth_train = [synthetic(row) for row in catalog if row['source'] not in (CAL_SOURCE, TEST_SOURCE)]
    synth_cal = [synthetic(row) for row in catalog if row['source'] == CAL_SOURCE]
    cv = read_json(work / 'b6/negative-manifest.json')
    dev_speakers = sorted({r['speaker_split_hash'] for r in cv['validation']})
    if set(dev_speakers) & {r['speaker_split_hash'] for r in cv['test']}:
        raise ValueError('Russian negative speakers cross partitions')
    reg_speakers = set(dev_speakers[::2])
    enroll_seconds, cal_seconds = 0.0, 0.0
    reg_owner = [register(encode, pcm, start, end) for _, pcm, start, end, _, _ in train[:10]]
    reg_synth = defaultdict(list)
    for _, pcm, start, end, _, variant in synth_train:
        reg_synth[variant].append(register(encode, pcm, start, end))
    synthesis_similarity = float(unit(np.mean(reg_synth['Вайли'], axis=0)) @ unit(np.mean(reg_synth['Уайли'], axis=0)))
    owner_to_synth = float(unit(np.mean(reg_owner, axis=0)) @ unit(np.mean(reg_synth['Вайли'], axis=0)))
    negatives = [embed for data in prefixes(encode, train[:10] + synth_train) for _, embed in data[::8]]
    cal_negative = prefixes(encode, validate + synth_cal)
    for row in cv['validation']:
        pcm = np.frombuffer(previous.decode(args, row), dtype='<i2')
        if row['speaker_split_hash'] in reg_speakers:
            negatives.extend(embed for _, embed in features(encode, pcm, stride=8))
            enroll_seconds += len(pcm) / RATE
        else:
            cal_negative.append(features(encode, pcm))
            cal_seconds += len(pcm) / RATE
    distractors = np.stack(negatives)
    cal_positive = positives(encode, validate + synth_cal)
    anchors = {'synthetic': np.stack([unit(np.mean(reg_synth[key][:5], axis=0)) for key in ('Вайли', 'Уайли')])}
    for shots in COUNTS:
        anchors[str(shots)] = np.stack([unit(np.mean(reg_owner[:shots], axis=0)), anchors['synthetic'][1]])
    calibration = {}
    for name, prototypes in anchors.items():
        calibration[name] = choose_threshold([(end, similarity(data, prototypes, distractors)) for end, data in cal_positive],
                                             [similarity(data, prototypes, distractors) for data in cal_negative])
    best = min(map(str, COUNTS), key=lambda name: (calibration[name]['negative_events'] + calibration[name]['early'],
                                                   -calibration[name]['complete'], int(name)))
    lock = {'method': args.method, 'exports': manifest, 'checkpoint': manifest['checkpoint_sha256'],
            'assets': manifest['assets_sha256'], 'owner_splits_sha256': file_hash(work / 'b6/owner-splits.json'),
            'owner_archive_sha256': file_hash(archive_path), 'annotations_sha256': file_hash(work / 'owner-annotations-reviewed.csv'),
            'synthetic_catalog_sha256': file_hash(work / 'b11/synthetic-catalog.json'),
            'cv_manifest_sha256': file_hash(work / 'b6/negative-manifest.json'),
            'owner_order': {name: identifiers for name, identifiers in splits.items() if name in ('train', 'validation', 'test')},
            'synthetic_cal_source': CAL_SOURCE, 'synthetic_test_source': TEST_SOURCE, 'thresholds': calibration,
            'registration_negative_seconds': enroll_seconds, 'calibration_negative_seconds': cal_seconds,
            'distractor_count': len(distractors), 'variants': list(anchors), 'selected': best,
            'hop': HOP, 'window': RATE, 'stability_windows': 2, 'event_rearm_s': 0.8, 'positive_max_lag_s': 1.5,
            'prototype_end_offset_s': OFFSET, 'variant_prototypes': {key: value.tolist() for key, value in anchors.items()},
            'negative_bank': distractors.tolist()}
    freeze = args.output.with_suffix('.config.json')
    write_new(freeze, lock)
    print(f'Configuration frozen: {best}, thresholds {calibration}', flush=True)

    with zipfile.ZipFile(archive_path) as archive:
        test, = owner_rows(work, archive, splits, ('test',))

    results = {name: Metrics() for name in anchors}

    def detect(name, frame_features):
        return list(events(similarity(frame_features, anchors[name], distractors), calibration[name]['threshold']))

    for _, pcm, start, end, condition, phrase in test:
        data = features(encode, pcm, True)
        prefix = pcm[:round((start + end) / 2 * RATE)]
        partial = features(encode, prefix, True)
        for name, metrics in results.items():
            tally_owner(metrics, detect(name, data), pcm, end, condition, phrase)
            metrics.add('owner_half_word', detect(name, partial), len(prefix) / RATE)
    synth_test = [synthetic(row) for row in catalog if row['source'] == TEST_SOURCE]
    for _, pcm, _, end, _, label in synth_test:
        data = features(encode, pcm, True)
        for name, metrics in results.items():
            metrics.add('synthetic_held_' + label, detect(name, data), len(pcm) / RATE, end)

    hard = defaultdict(list)
    final_records = {row['event_id']: row for row in read_json(work / 'b10/vosk-final-events.json')}
    for label in rows(work / 'b10/review-final.csv'):
        if label['verdict'] == 'false_detection':
            row = final_records[label['event_id']]
            if row['source'] != label['source'] or abs(row['time_s'] - float(label['time_s'])) > 0.001:
                raise ValueError('Hard negative annotation changed')
            hard[row['source']].append((round(max(0, row['word_start_s'] - 0.32) * RATE),
                                        round((row['time_s'] + 0.16) * RATE)))

    continuous = AudioWindows()
    scores = {name: [] for name in anchors}
    timing = Counter()
    total = 0
    for row in cv['test']:
        pcm = np.frombuffer(previous.decode(args, row), dtype='<i2')
        total += len(pcm)
        for key, stream in [('file', None), ('continuous', continuous)]:
            cpu, wall = time.process_time(), time.perf_counter()
            data = features(encode, pcm, stream=stream)
            primary = similarity(data, anchors[best], distractors)
            found = [] if stream is not None else list(events(primary, calibration[best]['threshold']))
            timing[key + '_cpu_s'] += time.process_time() - cpu
            timing[key + '_wall_s'] += time.perf_counter() - wall
            for name, metrics in results.items():
                computed = primary if name == best else similarity(data, anchors[name], distractors)
                if stream is None:
                    hits = found if name == best else list(events(computed, calibration[name]['threshold']))
                    metrics.add('negative_files', hits, len(pcm) / RATE)
                else:
                    scores[name].extend(computed)
        for start, stop in hard.pop(row['audio_file'], []):
            excerpt = pcm[start:stop]
            data = features(encode, excerpt, True)
            for name, metrics in results.items():
                metrics.add('hard_subset', detect(name, data), len(excerpt) / RATE)
    if hard:
        raise ValueError('Negative files missing')
    continuous_cpu, continuous_wall = time.process_time(), time.perf_counter()
    events_continuous = list(events(scores[best], calibration[best]['threshold']))
    timing['continuous_cpu_s'] += time.process_time() - continuous_cpu
    timing['continuous_wall_s'] += time.perf_counter() - continuous_wall
    for name, metrics in results.items():
        hits = events_continuous if name == best else list(events(scores[name], calibration[name]['threshold']))
        metrics.add('negative_continuous', hits, total / RATE)

    summary = {'method': args.method, 'primary': best, 'config_sha256': file_hash(freeze),
               'initialization_s': load_seconds, 'memory_before': before, 'memory_loaded': after_load, 'memory_after': memory(),
               'timing': {**dict(timing), 'file_wall_per_audio_s': timing['file_wall_s'] / (total / RATE),
                          'continuous_wall_per_audio_s': timing['continuous_wall_s'] / (total / RATE)},
               'all_weights_bytes': encode.asset_bytes + anchors[best].nbytes + distractors.nbytes,
               'embedding_cosines': {'synthetic_between_variants': synthesis_similarity, 'owner_to_synthetic_vayli': owner_to_synth},
               'synthetic_counts': {'registrations_available': len(synth_train), 'calibration': len(synth_cal), 'evaluation': len(synth_test)},
               'groups': {key: metric.report() for key, metric in results.items()}}
    write_new(args.output, summary)
    print(f'Evaluated {args.method}/{best}: {summary["groups"][best]}', flush=True)


def evaluate_study(args):
    import audit_wake_study as audit
    import hashlib

    config = read_json(args.config)
    if file_hash(args.config) != args.config_sha or config['method'] != args.method:
        raise ValueError('Use the predetermined, frozen PLiX configuration')
    if any(file_hash(args.exports / name) != value for name, value in config['assets'].items()):
        raise ValueError('Frozen encoder or frontend changed')
    labels = rows(args.reviewed)
    reviewed = {r['id']: (r['wake_start_s'], r['wake_end_s']) for r in labels}
    if len(reviewed) != len(labels):
        raise ValueError('Repeated reviewed ID')
    prior = audit.owner_fingerprints(args.work / 'owner-export-20261116-184820.zip')
    report, clips = audit.inspect(args.study_archive, prior, reviewed)
    if any(clip['split'] != 'test' or (clip['kind'] == 'positive' and clip['end'] is None) for clip in clips):
        raise ValueError('Closed study requires only test clips with reviewed positive boundaries')

    start = time.perf_counter()
    encoder = PLiX(args.exports, args.method)
    load = time.perf_counter() - start
    selected = config['selected']
    anchors = np.array(config['variant_prototypes'][selected], dtype=np.float32)
    background = np.array(config['negative_bank'], dtype=np.float32)
    threshold = config['thresholds'][selected]['threshold']
    results = Metrics()
    cpu, wall = 0.0, 0.0
    for clip in clips:
        with zipfile.ZipFile(clip['archive']) as archive:
            data = audit.read_audio(archive, clip['member'])
        if hashlib.sha256(data).hexdigest() != clip['pcm_sha256']:
            raise ValueError('Study archive changed during evaluation')
        pcm = np.frombuffer(data, dtype='<i2')
        is_positive = clip['kind'] == 'positive'
        c, t = time.process_time(), time.perf_counter()
        found = list(events(similarity(features(encoder, pcm, is_positive), anchors, background), threshold))
        cpu, wall = cpu + time.process_time() - c, wall + time.perf_counter() - t
        results.add('positive' if is_positive else 'negative_files', found, len(pcm) / RATE, clip['end'])
        if is_positive:
            results.add(clip['phrase'], found, len(pcm) / RATE, clip['end'])
            if args.owner_alias:
                kind = 'owner' if clip['speaker'] == args.owner_alias else 'other_speaker'
                results.add(kind, found, len(pcm) / RATE, clip['end'])
    write_new(args.output, {'method': args.method, 'config_sha256': args.config_sha, 'audit': report,
                            'load_s': load, 'cpu_s': cpu, 'wall_s': wall, 'memory': memory(), 'groups': results.report()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('method', choices=('ru', 'multi', 'vosk', 'next5'))
    parser.add_argument('--work', default=Path('local/wakeword26b'), type=Path)
    parser.add_argument('--synthetic', default=Path('WileyAI21Голос'), type=Path)
    parser.add_argument('--study-archive', action='append', type=Path)
    parser.add_argument('--config-sha')
    parser.add_argument('--owner-alias')
    for key in ('corpus', 'ffmpeg', 'exports', 'config', 'reviewed', 'output'):
        parser.add_argument('--' + key, type=Path, required=key == 'output')
    args = parser.parse_args()
    if args.study_archive:
        if args.method not in ('ru', 'multi') or not all((args.config, args.config_sha, args.reviewed, args.exports)):
            parser.error('Independent PLiX evaluation requires --config, --config-sha, --reviewed, --exports and a PLiX method')
        evaluate_study(args)
    elif args.method in ('vosk', 'next5'):
        controls(args)
    else:
        if not all((args.corpus, args.ffmpeg, args.exports)):
            parser.error('PLiX evaluation requires --corpus, --ffmpeg, and --exports')
        run(args)
