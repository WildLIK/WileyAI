import csv
import importlib.util
import io
import json
from pathlib import Path
from uuid import UUID
import wave
import zipfile

import pytest


def load(script):
    path = Path(__file__).resolve().parents[1] / 'scripts' / (script + '.py')
    spec = importlib.util.spec_from_file_location(script, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('audit_wake_study')


def study_zip(path, ident, *, split='test', speaker='speaker-1', session=1, signal=None, reviewed=False):
    ident = str(UUID(int=ident))
    meta = dict(id=ident, speaker_id=speaker, session_id=str(UUID(int=session)), split=split,
                kind='positive', phrase='Окей, Уайли', voice_level='quiet', distance_cm=100,
                environment='room', started_at_ms=10, samples=8000, schema=1, sample_rate=16000,
                channels=1, format='pcm_s16le', vosk={'status': 'accepted'})
    metadata = {key: meta[key] for key in ('id', 'speaker_id', 'session_id', 'split', 'kind',
                                          'phrase', 'voice_level', 'environment', 'started_at_ms', 'samples')}
    metadata.update(file=ident + '.wav', distance_m='1.0', wake_start_s='0.1' if reviewed else '',
                    wake_end_s='0.4' if reviewed else '', vosk_status='accepted')
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav:
        wav.setparams((1, 2, 16000, 8000, 'NONE', 'not compressed'))
        wav.writeframes((signal if signal is not None else UUID(ident).int).to_bytes(2, 'little') * 8000)
    manifest = io.StringIO(newline='')
    writer = csv.DictWriter(manifest, list(metadata))
    writer.writeheader()
    writer.writerow(metadata)
    with zipfile.ZipFile(path, 'w') as bundle:
        bundle.writestr('manifest.csv', manifest.getvalue())
        bundle.writestr(ident + '.wav', wav_buffer.getvalue())
        bundle.writestr(ident + '.json', json.dumps(meta))
    return path


def test_collection_stays_separate_and_audits_timing(tmp_path):
    first = study_zip(tmp_path / 'a.zip', 1, reviewed=True)
    second = study_zip(tmp_path / 'b.zip', 2, speaker='speaker-2', session=2, split='development')
    stats, entries = audit.inspect([first, second])
    assert stats['counts'] == {'test_positive': 1, 'development_positive': 1}
    assert stats['positives_needing_review'] == 1 and stats['speakers'] == 2
    assert entries[0]['end'] == 0.4 and entries[1]['end'] is None


def test_rejects_pcm_from_old_archive_with_different_sample_id(tmp_path):
    first = study_zip(tmp_path / 'a.zip', 1)
    second = study_zip(tmp_path / 'b.zip', 2, signal=1)
    with pytest.raises(ValueError, match='Duplicate decoded PCM'):
        audit.inspect([second], audit.owner_fingerprints(first))


def test_rejects_speaker_crossing_partitions(tmp_path):
    first = study_zip(tmp_path / 'a.zip', 1)
    second = study_zip(tmp_path / 'b.zip', 2, split='validation', session=2)
    with pytest.raises(ValueError, match='speaker spans'):
        audit.inspect([first, second])


def test_rejects_reassigned_session_and_unsafe_members(tmp_path):
    first = study_zip(tmp_path / 'a.zip', 1)
    second = study_zip(tmp_path / 'b.zip', 2, speaker='speaker-2')
    with pytest.raises(ValueError, match='session has conflicting'):
        audit.inspect([first, second])
    with zipfile.ZipFile(second, 'a') as bundle:
        bundle.writestr('../outside.wav', 'test')
    with pytest.raises(ValueError, match='Unlisted entry'):
        audit.inspect([second])


def test_rejects_bad_reviewed_interval(tmp_path):
    path = study_zip(tmp_path / 'a.zip', 1)
    with pytest.raises(ValueError, match='outside audio'):
        audit.inspect([path], reviewed={str(UUID(int=1)): ('0.1', '0.6')})


def test_acoustic_events_need_adjacent_windows_and_emit_once_per_run():
    pytest.importorskip('numpy')
    benchmark = load('probe-next5-wake')
    scores = [(0.08, 1), (0.16, 0), (0.24, 1), (0.32, 1), (0.4, 1),
              (0.48, 0), (0.56, 1), (0.64, 1), (1.6, 0), (1.68, 1), (1.76, 1)]
    assert list(benchmark.Acoustic.events(iter(scores), 0.5)) == [0.32, 1.76]
