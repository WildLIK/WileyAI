from pathlib import Path
import shutil
import subprocess

import pytest


def test_capture_lifecycle_and_pcm_measurements(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK unavailable')
    root = Path(__file__).resolve().parents[1]
    src = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    files = [src / f for f in ('VoiceTelemetry.java', 'PcmRingBuffer.java', 'PcmHandoff.java')]
    files.append(root / 'tests/android/VoiceTelemetryProbe.java')
    result = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.VoiceTelemetryProbe'], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
