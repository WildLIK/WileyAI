"""Local context and noise experiments using the frozen NEXT 6 PLiX-MULTI model."""

import argparse
from collections import Counter
from importlib import import_module
from pathlib import Path
import time
import zipfile

import numpy as np
from scipy.signal import lfilter

from plix_next6 import PLiX, file_hash, logmel
from wake_next6 import AudioWindows, RATE, choose_threshold, events
from wake_next7 import add_background, causal_window, detector, score_window

bench = import_module('probe-next6-wake')
previous = bench.previous
LOCK = '428d30048347b72ba75c006f8587d0220f0d319574bb8f5c1dfbd0c36c0beafb'


def context_name(phrase, condition):
    if condition in ('с паузой перед командой', 'слитно с командой'):
        return 'pause' if condition.startswith('с паузой') else 'joined'
    if phrase.startswith('Окей'):
        return 'okay'
    return 'isolated' if ',' not in phrase else 'other_command'


def frame_diagnosis(encode, bank, backgrounds, archived, speech):
    results = []
    thresholds = (-160, -80, 0, 80, 160, 240, 320, 400)

    def grid(signal, start, end, *, onset=None, offset=None):
        return [score_window(encode(causal_window(signal, end + delta * 16, word_start=onset, word_end=offset)),
                             bank, backgrounds) for delta in thresholds]

    for key, pcm, end_from, end_to, condition, phrase in archived:
        start, end = round(end_from * RATE), round(end_to * RATE)
        with_previous_speech = pcm.copy()
        portion = min(start, RATE // 2, len(speech))
        with_previous_speech[start - portion:start] = speech[:portion]
        results.append({
            'id': key, 'kind': context_name(phrase, condition), 'word_ms': (end - start) / 16,
            'deltas_ms': thresholds, 'raw': grid(pcm, start, end),
            'no_after': grid(pcm, start, end, offset=end),
            'no_before': grid(pcm, start, end, onset=start),
            'isolated': grid(pcm, start, end, onset=start, offset=end),
            'before_other_speech': grid(with_previous_speech, start, end),
            'half_word': grid(pcm, start, end, offset=(start + end) // 2),
            'quarter_gain': grid((pcm.astype(np.float32) * .25).astype(np.int16), start, end),
        })
    return results


def background_signals(a, b):
    rng = np.random.default_rng(2607)
    n = RATE * 4
    t = np.arange(n) / RATE
    white = rng.normal(0, 1, n)
    fan = 0.5 * np.sin(2 * np.pi * 110 * t) + .25 * np.sin(2 * np.pi * 220 * t)
    fan += lfilter([.08], [1, -.92], rng.normal(0, 1, n))
    music = np.zeros(n)
    for root in (130.815, 164.815, 195.995, 261.626):
        for harmonic in (1, 2, 3):
            music += np.sin(2 * np.pi * root * harmonic * t) / (4 * harmonic)
    music *= np.exp(-2 * (t % .6)) + .18
    talk = np.resize(a.astype(np.float32), n) / 32768
    chatter = talk + .75 * np.roll(np.resize(b.astype(np.float32), n) / 32768, 3200)
    return {'white': white, 'fan_proxy': fan, 'music_proxy': music, 'two_speakers': chatter,
            'video_proxy': chatter + .3 * music}


def paired_noise_analysis(encoder, prototypes, distractors, held, white):
    observed = []
    for _, pcm, start, end, _, _ in held:
        windows = [round(end * RATE) + offset for offset in range(0, 6401, 1280)]
        ranked = [(score_window(encoder(causal_window(pcm, pos)), prototypes, distractors), pos) for pos in windows]
        ranking, position = max(ranked, key=lambda pair: pair[0]['margin'])
        baseline = logmel(causal_window(pcm, position), encoder.hann, encoder.filters)
        signals = {'quarter_gain': (pcm.astype(np.float32) * .25).astype(np.int16)}
        signals.update({str(snr): add_background(pcm, start, end, white, snr) for snr in (20, 10, 0)})
        outcomes = {}
        for name, signal in signals.items():
            window = causal_window(signal, position)
            features = logmel(window, encoder.hann, encoder.filters)
            relative = score_window(encoder(window), prototypes, distractors)
            outcomes[name] = {'logmel_abs_mean': float(np.mean(np.abs(baseline - features))),
                              **{key + '_delta': relative[key] - ranking[key] for key in ranking}}
        observed.append(outcomes)
    return {method: {key: float(np.median([case[method][key] for case in observed])) for key in observed[0][method]}
            for method in observed[0]}


def run(args):
    work = args.work
    config = work / 'next6/multi.config.json'
    if file_hash(config) != LOCK:
        raise ValueError('Frozen PLiX-MULTI config changed')
    locked = bench.read_json(config)
    if any(file_hash(args.exports / name) != expected for name, expected in locked['assets'].items()):
        raise ValueError('PLiX model or frontend changed')
    init = time.perf_counter()
    vosk = previous.Vosk(work) if args.mode == 'vosk' else None
    model = None if vosk else PLiX(args.exports, 'multi')
    init = time.perf_counter() - init
    encode = None if vosk else detector(model, args.mode)
    prototype = np.array(locked['variant_prototypes']['3'], dtype=np.float32)
    distractors = np.array(locked['negative_bank'], dtype=np.float32)
    regression = bench.read_json(work / 'b6/owner-splits.json')
    path = work / 'owner-export-20261116-184820.zip'
    cv = bench.read_json(work / 'b6/negative-manifest.json')

    def scores(pcm, pad=False, stream=None):
        return bench.similarity(bench.features(encode, pcm, pad, stream=stream), prototype, distractors)

    def pcm(row):
        return np.frombuffer(previous.decode(args, row), dtype='<i2')

    if vosk:
        calibration = {'threshold': .75, 'source': 'existing Vosk short profile'}
    elif args.mode == 'base':
        calibration = locked['thresholds']['3']
    else:
        with zipfile.ZipFile(path) as archive:
            validation, = bench.owner_rows(work, archive, regression, ('validation',))
        cal_cv = set(sorted({r['speaker_split_hash'] for r in cv['validation']})[1::2])
        catalog = bench.read_json(work / 'b11/synthetic-catalog.json')['records']
        for row in catalog:
            if row['source'] == 'Timbrica':
                validation.append((row['id'], bench.read_pcm(str(args.synthetic / row['wav_path'])), row['start_energy_s'],
                                   row['end_energy_s'], '', row['declared_variant']))
        negative = [scores(pcm(row)) for row in cv['validation'] if row['speaker_split_hash'] in cal_cv]
        negative += [scores(audio[:round((start + end) / 2 * RATE)], True) for _, audio, start, end, _, _ in validation]
        positive = [(end, scores(audio, True)) for _, audio, _, end, _, _ in validation]
        calibration = choose_threshold(positive, negative)
    thresholds = {'method': args.mode, 'next6_config_sha256': LOCK, 'calibration': calibration,
                  'stability_windows': 2, 'rearm_seconds': .8, 'keep_samples': 10240 if args.mode == 'short' else RATE}
    lock = args.output.with_suffix('.config.json')
    previous.write_new(lock, thresholds)
    cut = calibration['threshold']

    def detect(pcm, pad=False):
        if vosk:
            return vosk.run(pcm.tobytes(), pad)
        return list(events(scores(pcm, pad), cut))

    with zipfile.ZipFile(path) as archive:
        held, = bench.owner_rows(work, archive, regression, ('test',))
    metric = bench.Metrics()
    for _, clip, start, end, condition, phrase in held:
        hit = detect(clip, True)
        bench.tally_owner(metric, hit, clip, end, condition, phrase)
        metric.add('context_' + context_name(phrase, condition), hit, len(clip) / RATE, end)
        prefix = clip[:round((start + end) / 2 * RATE)]
        metric.add('half_word', detect(prefix, True), len(prefix) / RATE)
    catalog = bench.read_json(work / 'b11/synthetic-catalog.json')['records']
    for row in catalog:
        if row['source'] == 'TTSMaker':
            clip = bench.read_pcm(str(args.synthetic / row['wav_path']))
            metric.add('synthetic_' + row['declared_variant'], detect(clip, True),
                       len(clip) / RATE, row['end_energy_s'])
    selected = {}
    for row in cv['test']:
        selected.setdefault(row['speaker_split_hash'], row)
    a, b = [pcm(row) for row in list(selected.values())[:2]]
    backgrounds = background_signals(a, b)
    if args.mode == 'base':
        paired = paired_noise_analysis(model, prototype, distractors, held, backgrounds['white'])
        previous.write_new(args.output.with_suffix('.noise.json'), paired)
    for name, background in backgrounds.items():
        levels = (20, 10, 0) if name == 'white' else (10,)
        for level in levels:
            for _, clip, start, end, _, _ in held:
                mixed = add_background(clip, start, end, background, level)
                metric.add(f'{name}_{level}dB', detect(mixed, True), len(mixed) / RATE, end)
        negative = np.clip(np.rint(background / max(.001, np.max(np.abs(background))) * 18000), -32768, 32767).astype(np.int16)
        metric.add(f'{name}_only', detect(negative), len(negative) / RATE)

    # Actual Piper TTS and four labeled pronunciations, generated locally, outside calibration.
    challenges = import_module('probe-next6-challenges')
    for phrase, clip, end in challenges.piper_clips(args.voices):
        is_name = phrase in challenges.LABELS
        metric.add('piper_' + phrase if is_name else 'piper_confusable', detect(clip, True),
                   len(clip) / RATE, end if is_name else None)

    if args.mode == 'base':
        with zipfile.ZipFile(path) as archive:
            training, validation = bench.owner_rows(work, archive, regression, ('train', 'validation'))
        # Broader diagnostic view, no third-party result leaves the local research folder.
        audit = frame_diagnosis(encode, prototype, distractors, training[3:] + validation + held, a)
        previous.write_new(args.output.with_suffix('.windows.json'), audit)

    stream = AudioWindows()
    ratings = []
    signal = bytearray()
    count = 0
    cpu = wall = 0.0
    for row in cv['test']:
        clip = pcm(row)
        count += len(clip)
        if vosk:
            signal.extend(clip.tobytes())
        else:
            pc, pw = time.process_time(), time.perf_counter()
            ratings.extend(scores(clip, stream=stream))
            cpu += time.process_time() - pc
            wall += time.perf_counter() - pw
    audio = bytes(signal)
    del signal
    pc, pw = time.process_time(), time.perf_counter()
    hit = vosk.run(audio, False) if vosk else list(events(ratings, cut))
    cpu += time.process_time() - pc
    wall += time.perf_counter() - pw
    metric.add('negative_continuous', hit, count / RATE)
    result = {'method': args.mode, 'config_sha256': file_hash(lock), 'initialization_s': init, 'memory': previous.memory(),
              'cpu_s': cpu, 'wall_s': wall, 'wall_per_s': wall / (count / RATE), 'groups': metric.report()}
    previous.write_new(args.output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('vosk', 'base', 'short', 'floor'))
    parser.add_argument('--work', type=Path, default=Path('local/wakeword26b'))
    parser.add_argument('--synthetic', type=Path, default=Path('WileyAI21Голос'))
    parser.add_argument('--voices', type=Path, default=Path('data/models/piper'))
    for name in ('corpus', 'ffmpeg', 'exports', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    run(parser.parse_args())
