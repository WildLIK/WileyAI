from pathlib import Path
import shutil
import subprocess

import pytest


def test_acoustic_pcm_windows_and_lossless_storage(tmp_path):
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    root = Path(__file__).resolve().parents[1]
    sources = root / "android/app/src/main/java/ru/wildlik/wileyai/mobile"
    probe = root / "tests/android/AcousticDiagnosticsProbe.java"
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(tmp_path), str(probe),
                    *[str(sources / name) for name in ("PcmRingBuffer.java", "AcousticCapture.java", "AcousticAudio.java")]],
                   check=True, capture_output=True, text=True)
    subprocess.run([java, "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.AcousticDiagnosticsProbe", str(tmp_path)],
                   check=True, capture_output=True, text=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        actual = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(tmp_path / "test.flac"),
                                         "-f", "s16le", "-"])
        assert actual == (tmp_path / "expected.pcm").read_bytes()
