"""Optional NEXT 6 verifier: one PLiX window per accepted Vosk final."""

import argparse
from collections import defaultdict
from importlib import import_module
from pathlib import Path
import time
import zipfile

import numpy as np

from plix_next6 import PLiX, file_hash
from wake_next6 import RATE, completed_hit, open_scores

probe = import_module('probe-next6-wake')
previous = probe.previous
MAX_LOOKBACK = round(1.8 * RATE)


def crop(pcm, decision, estimated_end):
    if estimated_end is None:
        return None
    have = min(len(pcm), round(decision * RATE))
    end = min(have, round((estimated_end + probe.OFFSET) * RATE))
    start = end - RATE
    if end <= 0 or start < have - MAX_LOOKBACK:
        return None
    window = np.zeros(RATE, dtype=np.int16)
    window[max(0, -start):] = pcm[max(0, start):end]
    return window


def occurrences(rows, threshold):
    return [decision for decision, score in rows if score is not None and score >= threshold]


def calibrate(positives, negatives):
    best = None
    for step in range(-200, 201):
        value = step / 100
        complete = sum(completed_hit(occurrences(scores, value), end)[0] == 'complete' for end, scores in positives)
        early = sum(completed_hit(occurrences(scores, value), end)[0] == 'early' for end, scores in positives)
        false = sum(len(occurrences(scores, value)) for scores in negatives)
        objective = (false + early, -complete, -value)
        if best is None or objective < best[0]:
            best = (objective, {'threshold': value, 'complete': complete, 'early': early, 'negative_events': false})
    return best[1]


def run(args):
    locked = probe.read_json(args.config)
    if file_hash(args.config) != args.config_sha or locked['method'] != 'ru':
        raise ValueError('Cascade requires the frozen Russian PLiX configuration')
    if any(file_hash(args.exports / f) != sha for f, sha in locked['assets'].items()):
        raise ValueError('PLiX graph or frontend changed')
    references = np.array(locked['variant_prototypes'][locked['selected']], dtype=np.float32)
    negative_bank = np.array(locked['negative_bank'], dtype=np.float32)
    started = time.perf_counter()
    vosk = previous.Vosk(args.work)
    acoustic = PLiX(args.exports, 'ru')
    cold = time.perf_counter() - started
    times = defaultdict(list)
    before = previous.memory()

    def replay(pcm, pad=False, metric=None):
        proposals = vosk.impl.replay(vosk.model, vosk.grammar, vosk.allowed, pcm.tobytes(), pad=pad)
        signal = np.pad(pcm, (0, RATE)) if pad else pcm
        candidates = []
        for _, decision, end in proposals:
            cpu, wall = time.process_time(), time.perf_counter()
            window = crop(signal, decision, end)
            score = None if window is None else float(open_scores(acoustic(window)[None, :], references, negative_bank)[0])
            if metric:
                times[metric].append((1000 * (time.perf_counter() - wall), 1000 * (time.process_time() - cpu)))
            candidates.append((decision, score))
        return candidates

    cv = probe.read_json(args.work / 'b6/negative-manifest.json')
    if args.continuous_rule is not None:
        frozen = probe.read_json(args.continuous_rule)
        if frozen['config_sha256'] != args.config_sha or frozen['lookback_samples'] != MAX_LOOKBACK:
            raise ValueError('Rule does not match the frozen PLiX configuration')
        data = bytearray()
        for item in cv['test']:
            data.extend(previous.decode(args, item))
        pcm = np.frombuffer(data, dtype='<i2')
        cpu, wall = time.process_time(), time.perf_counter()
        candidates = replay(pcm, metric='continuous')
        accepted = occurrences(candidates, frozen['threshold'])
        timing = {'seconds_cpu': time.process_time() - cpu, 'seconds_wall': time.perf_counter() - wall}
        plain, filtered = probe.Metrics(), probe.Metrics()
        plain.add('negative_continuous', [sec for sec, _ in candidates], len(pcm) / RATE)
        filtered.add('negative_continuous', accepted, len(pcm) / RATE)
        previous.write_new(args.output, {'rule_sha256': file_hash(args.continuous_rule), 'vosk': plain.report(),
                                         'cascade': filtered.report(), **timing,
                                         'extra_wall_ms': previous.summary([wall_ms for wall_ms, _ in times['continuous']])})
        return

    splits = probe.read_json(args.work / 'b6/owner-splits.json')
    archive = args.work / 'owner-export-20261116-184820.zip'
    supported = sorted({row['speaker_split_hash'] for row in cv['validation']})
    cal_speakers = set(supported[1::2])
    with zipfile.ZipFile(archive) as bundle:
        validation, = probe.owner_rows(args.work, bundle, splits, ('validation',))
    positives = [(end, replay(pcm, True)) for _, pcm, _, end, _, _ in validation]
    negative = [replay(pcm[:round((start + end) / 2 * RATE)], True) for _, pcm, start, end, _, _ in validation]
    for row in cv['validation']:
        if row['speaker_split_hash'] in cal_speakers:
            negative.append(replay(np.frombuffer(previous.decode(args, row), dtype='<i2')))
    rule = calibrate(positives, negative)
    rule['config_sha256'] = args.config_sha
    rule['lookback_samples'] = MAX_LOOKBACK
    freeze = args.output.with_suffix('.rule.json')
    previous.write_new(freeze, rule)
    with zipfile.ZipFile(archive) as bundle:
        test, = probe.owner_rows(args.work, bundle, splits, ('test',))

    plain, combined = probe.Metrics(), probe.Metrics()
    for _, pcm, start, end, condition, phrase in test:
        candidates = replay(pcm, True, 'owner')
        probe.tally_owner(plain, [sec for sec, _ in candidates], pcm, end, condition, phrase)
        probe.tally_owner(combined, occurrences(candidates, rule['threshold']), pcm, end, condition, phrase)
        prefix = pcm[:round((start + end) / 2 * RATE)]
        half = replay(prefix, True, 'prefix')
        plain.add('owner_half_word', [sec for sec, _ in half], len(prefix) / RATE)
        combined.add('owner_half_word', occurrences(half, rule['threshold']), len(prefix) / RATE)

    hard = defaultdict(list)
    known = {r['event_id']: r for r in probe.read_json(args.work / 'b10/vosk-final-events.json')}
    for label in probe.rows(args.work / 'b10/review-final.csv'):
        if label['verdict'] == 'false_detection':
            row = known[label['event_id']]
            if row['source'] != label['source'] or abs(row['time_s'] - float(label['time_s'])) > 0.001:
                raise ValueError('Hard negative annotation changed')
            hard[row['source']].append((round(max(0, row['word_start_s'] - 0.32) * RATE), round((row['time_s'] + 0.16) * RATE)))

    cpu, wall = 0.0, 0.0
    for row in cv['test']:
        pcm = np.frombuffer(previous.decode(args, row), dtype='<i2')
        for name, signal in [('negative_files', pcm)] + [('hard_subset', pcm[a:b]) for a, b in hard.pop(row['audio_file'], [])]:
            t_cpu, t_wall = time.process_time(), time.perf_counter()
            candidates = replay(signal, name == 'hard_subset', name)
            accepted = occurrences(candidates, rule['threshold'])
            if name == 'negative_files':
                cpu += time.process_time() - t_cpu
                wall += time.perf_counter() - t_wall
            plain.add(name, [sec for sec, _ in candidates], len(signal) / RATE)
            combined.add(name, accepted, len(signal) / RATE)
    if hard:
        raise ValueError('Negative files missing')
    weights = acoustic.asset_bytes + references.nbytes + negative_bank.nbytes
    weights += sum(p.stat().st_size for p in (args.work / 'vosk-device-model').rglob('*') if p.is_file())
    report = {'rule': rule, 'rule_sha256': file_hash(freeze), 'vosk': plain.report(), 'cascade': combined.report(),
              'initialization_s': cold, 'after_loading': before, 'memory_after': previous.memory(),
              'seconds_cpu': cpu, 'seconds_wall': wall, 'weights_bytes': weights,
              'additional_time_ms': {key: {'wall': previous.summary([p[0] for p in sample]),
                                           'cpu': previous.summary([p[1] for p in sample]), 'n': len(sample)}
                                     for key, sample in times.items()}}
    previous.write_new(args.output, report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('local/wakeword26b'))
    parser.add_argument('--config-sha', required=True)
    parser.add_argument('--continuous-rule', type=Path)
    for name in ('corpus', 'ffmpeg', 'config', 'exports', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    run(parser.parse_args())
