"""Causal PCM windows and scoring for the isolated NEXT 6 experiments."""

from collections import Counter

import numpy as np

RATE = 16000
HOP = 1280
STABLE_WINDOWS = 2
REARM_SECONDS = 0.8
MAX_LAG_SECONDS = 1.5


class AudioWindows:
    def __init__(self):
        self.window = np.zeros(RATE, dtype=np.int16)
        self.incoming = np.zeros(HOP, dtype=np.int16)
        self.pending = 0
        self.position = 0

    def feed(self, samples):
        offset = 0
        while offset < len(samples):
            size = min(HOP - self.pending, len(samples) - offset)
            self.incoming[self.pending:self.pending + size] = samples[offset:offset + size]
            self.pending += size
            offset += size
            if self.pending == HOP:
                self.window[:-HOP] = self.window[HOP:]
                self.window[-HOP:] = self.incoming
                self.pending = 0
                self.position += HOP
                yield self.position, self.window.copy()


def events(scores, threshold):
    consecutive = 0
    rearm = 0.0
    for now, score in scores:
        consecutive = consecutive + 1 if score >= threshold else 0
        if consecutive == STABLE_WINDOWS and now >= rearm:
            yield now
            rearm = now + REARM_SECONDS


def completed_hit(hits, end):
    if not hits:
        return 'miss', None
    lag = hits[0] - end
    if lag < -1e-9:
        return 'early', None
    if lag > MAX_LAG_SECONDS:
        return 'late', None
    return 'complete', max(0.0, lag * 1000)


def unit(embeddings):
    return embeddings / np.maximum(1e-8, np.linalg.norm(embeddings, axis=-1, keepdims=True))


def open_scores(embeddings, prototypes, negatives):
    return 2 * (np.max(embeddings @ prototypes.T, axis=1) - np.max(embeddings @ negatives.T, axis=1))


def split_inputs(splits, ids):
    index = {clip: name for name in ('train', 'validation', 'test') for clip in splits[name]}
    if set(index) != ids or len(index) != sum(len(splits[name]) for name in ('train', 'validation', 'test')):
        raise ValueError('Owner splits overlap or incomplete')
    return index


def choose_threshold(positives, negatives):
    # Fixed grid. Rejection of calibration negatives and premature events precedes recall.
    best = None
    for threshold in np.linspace(-2, 2, 401):
        false = sum(len(list(events(scores, threshold))) for scores in negatives)
        counts = Counter(completed_hit(list(events(scores, threshold)), end)[0] for end, scores in positives)
        objective = (false + counts['early'], -counts['complete'], -float(threshold))
        if best is None or objective < best[0]:
            best = (objective, {'threshold': float(threshold), 'negative_events': false, **dict(counts)})
    result = best[1]
    return {'complete': 0, 'early': 0, 'miss': 0, 'late': 0, **result}
