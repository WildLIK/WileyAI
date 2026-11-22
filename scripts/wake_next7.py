"""Controlled causal window interventions for PLiX-MULTI."""

import numpy as np
from scipy.fft import rfft

from wake_next6 import RATE, unit

RETAIN = 10240


def causal_window(pcm, end, *, word_start=None, word_end=None):
    """Keep timestamp and actual word samples fixed while zeroing selected context."""
    begin = end - RATE
    left = max(0, begin, 0 if word_start is None else word_start)
    right = min(len(pcm), end, len(pcm) if word_end is None else word_end)
    result = np.zeros(RATE, dtype=np.int16)
    if left < right:
        result[left - begin:right - begin] = pcm[left:right]
    return result


def shorten(pcm):
    result = pcm.copy()
    result[:-RETAIN] = 0
    return result


def score_window(embedding, anchors, distractors):
    keyword = float(np.max(anchors @ embedding))
    distractor = float(np.max(distractors @ embedding))
    return {'keyword': keyword, 'distractor': distractor, 'margin': 2 * (keyword - distractor)}


def stationary_floor(power):
    floor = np.quantile(power, .2, axis=0).astype(np.float32) * 1.25
    return np.maximum(power - floor, power * np.float32(.1))


def filtered_logmel(pcm, window, bank):
    data = np.pad(pcm.astype(np.float32) / 32768, 512, mode='reflect')
    frames = np.lib.stride_tricks.sliding_window_view(data, 1024)[::160]
    spectrum = rfft(frames * window)
    power = spectrum.real ** 2 + spectrum.imag ** 2
    return np.log(stationary_floor(power) @ bank + np.float32(1e-6)).T[None, None].copy()


def detector(encoder, mode):
    if mode == 'base':
        return encoder
    if mode == 'short':
        return lambda pcm: encoder(shorten(pcm))
    if mode == 'floor':
        def filtered(pcm):
            features = filtered_logmel(pcm, encoder.hann, encoder.filters)
            return unit(encoder.runtime.run(['embedding'], {'logmel': features})[0])[0]
        return filtered
    raise ValueError('Unknown research intervention')


def add_background(pcm, start, end, background, snr):
    signal = pcm.astype(np.float32)
    limit = slice(round(start * RATE), round(end * RATE))
    if not len(background):
        raise ValueError('No background samples')
    mixed_noise = np.resize(background.astype(np.float32), len(signal))
    word_rms = np.sqrt(np.mean(signal[limit] ** 2))
    noise_rms = np.sqrt(np.mean(mixed_noise[limit] ** 2))
    if not np.isfinite(word_rms) or noise_rms < 1e-8:
        raise ValueError('Silent or invalid SNR reference interval')
    scale = word_rms / (noise_rms * 10 ** (snr / 20))
    return np.clip(np.rint(signal + mixed_noise * scale), -32768, 32767).astype(np.int16)
