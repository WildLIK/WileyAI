import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wake_next6 import (HOP, RATE, AudioWindows, completed_hit, events, open_scores,
                        split_inputs, choose_threshold)


def test_audio_windows_are_causal_across_arbitrary_feed_boundaries():
    pcm = np.arange(3 * HOP + 7, dtype=np.int16)
    stream = AudioWindows()
    chunks = list(stream.feed(pcm[:700])) + list(stream.feed(pcm[700:1900])) + list(stream.feed(pcm[1900:]))
    assert [end for end, _ in chunks] == [HOP, HOP * 2, HOP * 3]
    expected = np.r_[np.zeros(RATE - HOP), pcm[:HOP]]
    assert np.array_equal(chunks[0][1], expected)
    assert np.array_equal(chunks[-1][1][-HOP:], pcm[2 * HOP:3 * HOP])
    assert stream.pending == 7


def test_report_full_early_and_late_separately():
    assert completed_hit([0.32, 0.60], 0.40) == ('early', None)
    assert completed_hit([0.55], 0.40)[1] == pytest.approx(150)
    assert completed_hit([2.2], 0.40) == ('late', None)
    assert completed_hit([], 0.40) == ('miss', None)


def test_events_require_two_windows_and_rearm_after_dip():
    sims = [(0.08, 1), (0.16, 0), (0.24, 1), (0.32, 1), (0.40, 1),
            (0.48, 0), (0.56, 1), (0.64, 1), (0.72, 0), (1.30, 1), (1.38, 1)]
    assert list(events(sims, 0.5)) == [0.32, 1.38]


def test_open_score_penalizes_queries_closer_to_negative_examples():
    emb = np.array([[1., 0.], [0., 1.]], dtype=np.float32)
    sims = open_scores(emb, emb[:1], emb[1:])
    assert list(sims) == [2., -2.]


def test_split_must_cover_archive_exactly_without_reuse():
    allowed = {'a', 'b', 'c'}
    assert split_inputs({'train': ['a'], 'validation': ['b'], 'test': ['c']}, allowed) == {'a': 'train', 'b': 'validation', 'c': 'test'}
    with pytest.raises(ValueError, match='overlap or incomplete'):
        split_inputs({'train': ['a', 'b'], 'validation': ['b'], 'test': ['c']}, allowed)


def test_threshold_calibration_prioritizes_rejecting_early_and_negative():
    positives = [(0.20, [(0.24, 0.6), (0.32, 0.6)]), (0.25, [(0.08, 0.1), (0.16, 0.1)])]
    negatives = [[(0.08, 0.4), (0.16, 0.4)]]
    result = choose_threshold(positives, negatives)
    assert result['complete'] == 1 and result['negative_events'] == 0
    assert 0.4 < result['threshold'] <= 0.6


def test_cascade_alignment_uses_only_pcm_already_received():
    cascade = import_module('probe-next6-cascade')
    pcm = np.arange(2 * RATE, dtype=np.int16)
    window = cascade.crop(pcm, 1.0, 0.99)
    assert np.array_equal(window, pcm[:RATE])
    assert cascade.crop(pcm, 1.95, 0.5) is None
    assert cascade.crop(pcm, 1.0, None) is None


def test_cascade_only_rejects_candidate_and_never_creates_one():
    cascade = import_module('probe-next6-cascade')
    originals = [(0.8, None), (1.0, 0.3), (1.3, 0.1)]
    assert cascade.occurrences(originals, 0.2) == [1.0]
    assert cascade.occurrences([], -2) == []


def test_closed_evaluation_rejects_changed_head_and_non_test_split(tmp_path, monkeypatch):
    benchmark = import_module('probe-next6-wake')
    audit = import_module('audit_wake_study')
    config = tmp_path / 'config.json'
    config.write_text('{"method":"multi", "assets":{}}', encoding='utf8')
    review = tmp_path / 'review.csv'
    review.write_text('id,wake_start_s,wake_end_s\n', encoding='utf8')
    args = SimpleNamespace(config=config, config_sha='incorrect', method='multi', exports=tmp_path,
                           reviewed=review, work=tmp_path, study_archive=[])
    with pytest.raises(ValueError, match='frozen'):
        benchmark.evaluate_study(args)

    args.config_sha = benchmark.file_hash(config)
    monkeypatch.setattr(audit, 'owner_fingerprints', lambda _: set())
    monkeypatch.setattr(audit, 'inspect', lambda *args: ({}, [{'split': 'validation', 'kind': 'negative'}]))
    with pytest.raises(ValueError, match='only test clips'):
        benchmark.evaluate_study(args)
