from pathlib import Path
import os
import shutil
import subprocess

import pytest


def test_bounded_pcm_ring(tmp_path):
    root = Path(__file__).resolve().parents[1]
    java_bin = Path(os.environ.get("JAVA_HOME", "")) / "bin"
    javac = str(java_bin / "javac.exe") if (java_bin / "javac.exe").exists() else shutil.which("javac")
    java = str(java_bin / "java.exe") if (java_bin / "java.exe").exists() else shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK unavailable")
    sources = [root / "android/app/src/main/java/ru/wildlik/wileyai/mobile/PcmRingBuffer.java", root / "tests/android/PcmRingBufferProbe.java"]
    compiled = subprocess.run([javac, "-encoding", "UTF-8", "-d", str(tmp_path), *map(str, sources)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run([java, "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.PcmRingBufferProbe"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
