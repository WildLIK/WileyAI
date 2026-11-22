from pathlib import Path
import shutil
import subprocess
import wave
import json
import pytest


def test_continuous_handoff_order_overflow_and_cancel(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    source = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    files = [source / 'PcmRingBuffer.java', source / 'PcmHandoff.java', root / 'tests/android/PcmHandoffProbe.java']
    compile = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=30)
    assert compile.returncode == 0, compile.stderr
    run = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.PcmHandoffProbe'], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


def test_handoff_wav_does_not_drop_samples(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    source = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    files = [source / 'PcmRingBuffer.java', source / 'PcmHandoff.java', root / 'tests/android/PcmHandoffProbe.java']
    compile = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=30)
    assert compile.returncode == 0, compile.stderr
    sample = root / 'local/wakeword26b/synthetic/test/positive/dmitri-03-1.wav'
    if not sample.exists():
        pytest.skip('Optional local synthetic wake-plus-command WAV unavailable')
    with wave.open(str(sample), 'rb') as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        raw = audio.readframes(audio.getnframes())
    pcm = tmp_path / 'command.pcm'
    pcm.write_bytes(raw)
    run = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.PcmHandoffProbe', str(pcm)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


def test_wake_prefix_only_removed_at_command_start(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    files = [root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile/WakePhrase.java', root / 'tests/android/WakePrefixProbe.java']
    result = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.WakePrefixProbe'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_synthetic_wake_wavs_keep_every_post_wake_sample(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    corpus = root / 'local/wakeword26b/handoff_wav'
    if not (corpus / 'manifest.json').exists():
        pytest.skip('Optional local synthetic wake WAVs unavailable')
    source = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    files = [source / 'PcmRingBuffer.java', source / 'PcmHandoff.java', root / 'tests/android/PcmHandoffProbe.java']
    result = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    rows = json.loads((corpus / 'manifest.json').read_text(encoding='utf8'))
    assert len(rows) == 6
    for row in rows:
        with wave.open(str(corpus / row['file']), 'rb') as audio:
            assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
            pcm = audio.readframes(audio.getnframes())
        raw = tmp_path / (row['file'] + '.pcm')
        raw.write_bytes(pcm)
        result = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.PcmHandoffProbe', str(raw), str(row['wake_end_sample'])], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, row['file'] + ': ' + result.stderr
