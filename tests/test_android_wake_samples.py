from pathlib import Path
import shutil
import subprocess

import pytest


def test_sample_deletion_is_scoped_and_reports_failures(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    source = root / 'android/app/src/main/java/ru/wildlik/wileyai/mobile/WakeSampleStore.java'
    probe = root / 'tests/android/WakeSampleStoreProbe.java'
    output = tmp_path / 'classes'
    output.mkdir()
    samples = tmp_path / 'synthetic-samples'
    samples.mkdir()
    compiled = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(output), str(source),
                               str(source.with_name('WakeStudy.java')), str(probe)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run([java, '-cp', str(output), 'ru.wildlik.wileyai.mobile.WakeSampleStoreProbe', str(samples)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
