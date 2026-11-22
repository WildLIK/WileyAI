import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wake_next7 import causal_window, shorten, score_window, stationary_floor, add_background
from wake_next6 import RATE


def test_window_removes_context_without_modifying_word_or_reading_future():
    pcm = np.arange(2 * RATE, dtype=np.int16)
    raw = causal_window(pcm, 1600)
    assert np.array_equal(raw[-1600:], pcm[:1600]) and not raw[:-1600].any()
    isolated = causal_window(pcm, 1600, word_start=500, word_end=1300)
    assert np.array_equal(isolated[-1100:-300], pcm[500:1300])
    assert not isolated[:-1100].any() and not isolated[-300:].any()


def test_short_window_zeros_old_context_and_preserves_tail():
    pcm = np.arange(RATE, dtype=np.int16)
    shorter = shorten(pcm)
    assert len(shorter) == len(pcm) and not shorter[:-10240].any()
    assert np.array_equal(shorter[-10240:], pcm[-10240:])


def test_floor_stays_finite_and_preserves_transient_bins():
    power = np.array([[4, 0], [4, 0], [4, 10], [4, 0]], dtype=np.float32)
    result = stationary_floor(power)
    assert result[0, 0] == pytest.approx(0.4)
    assert result[2, 1] == 10 and result[0, 1] == 0
    assert np.array_equal(power[2], [4, 10])


def test_background_normalizes_noise_relative_to_word_interval():
    pcm = np.full(RATE, 1000, dtype=np.int16)
    profile = np.ones(RATE, dtype=np.float32)
    mixed = add_background(pcm, 0.2, 0.6, profile, 20)
    assert np.all(mixed == 1100) and np.all(pcm == 1000)


def test_scores_expose_separate_keyword_and_distractor_similarities():
    anchors = np.array([[1., 0.]], dtype=np.float32)
    distractors = np.array([[0., 1.]], dtype=np.float32)
    result = score_window(np.array([.8, .6]), anchors, distractors)
    assert result['keyword'] == pytest.approx(0.8)
    assert result['distractor'] == pytest.approx(0.6)
    assert result['margin'] == pytest.approx(0.4)
