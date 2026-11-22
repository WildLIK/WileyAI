from pathlib import Path
import shutil
import subprocess
import os

import pytest


def test_media_speech(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if (not javac or not java) and os.environ.get("JAVA_HOME"):
        java_bin = Path(os.environ["JAVA_HOME"]) / "bin"
        javac = javac or str(java_bin / ("javac.exe" if os.name == "nt" else "javac"))
        java = java or str(java_bin / ("java.exe" if os.name == "nt" else "java"))
    if not javac or not java:
        pytest.skip("JDK unavailable")
    root = Path(__file__).resolve().parents[1]
    src = root / "android/app/src/main/java/ru/wildlik/wileyai/mobile"
    files = [src / "MediaSpeech.java", src / "PhoneActionReply.java", src / "MusicCatalogPolicy.java", root / "tests/android/MediaSpeechProbe.java"]
    result = subprocess.run([javac, "-encoding", "UTF-8", "-d", str(tmp_path), *map(str, files)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.MediaSpeechProbe"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
