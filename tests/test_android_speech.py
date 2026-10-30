"""Executes the real Java installer on host files; never downloads model weights."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
JAVA_SOURCE = ROOT / "android/app/src/main/java/ru/wildlik/wileyai/mobile"


@pytest.fixture(scope="module")
def speech_probe(tmp_path_factory):
    java_home = Path(os.environ.get("JAVA_HOME", "")) / "bin"
    java = str(java_home / "java.exe") if (java_home / "java.exe").exists() else shutil.which("java")
    javac = str(java_home / "javac.exe") if (java_home / "javac.exe").exists() else shutil.which("javac")
    if not java or not javac:
        pytest.skip("JDK 17 is required for Android Java host probes")
    classes = tmp_path_factory.mktemp("android-speech-classes")
    result = subprocess.run([javac, "-encoding", "UTF-8", "-d", str(classes),
                             str(JAVA_SOURCE / "VerifiedModelInstaller.java"), str(JAVA_SOURCE / "SpokenNames.java"), str(JAVA_SOURCE / "AppRegistry.java"),
                             str(JAVA_SOURCE / "VoiceLabels.java"), str(JAVA_SOURCE / "WakePhrase.java"), str(JAVA_SOURCE / "ResumableDownload.java"),
                             str(JAVA_SOURCE / "GgufInstaller.java"), str(ROOT / "tests/android/GgufProbe.java"),
                             str(ROOT / "tests/android/DownloadProbe.java"), str(ROOT / "tests/android/SpeechComponentsProbe.java")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return java, classes


@pytest.mark.parametrize("scenario", ["wake-phrase", "reopen", "replace", "bad-sha", "bad-md5", "partial-download", "traversal", "absolute", "wrong-root", "expansion-limit", "cancelled", "cancel-after-validation", "engine-failure", "corrupt-pointer", "spoken-aliases", "voice-labels", "catalog-exact", "catalog-ambiguous", "catalog-aliases", "catalog-rejects-fuzzy", "catalog-search", "catalog-removed", "catalog-nfkc", "catalog-alias-validation"])
def test_speech_and_app_components(speech_probe, tmp_path, scenario):
    java, classes = speech_probe
    result = subprocess.run([java, "-cp", str(classes), "SpeechComponentsProbe", scenario, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed: " + scenario in result.stdout


@pytest.mark.parametrize("scenario", ["resume", "short-ranges", "truncated-fallback", "redirect", "range-ignored", "invalid-range", "cancelled", "bounded-retries"])
def test_download_transport(speech_probe, tmp_path, scenario):
    java, classes = speech_probe
    result = subprocess.run([java, "-cp", str(classes), "DownloadProbe", scenario, str(tmp_path)], capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed: " + scenario in result.stdout


@pytest.mark.parametrize("scenario", ["replace", "short-file", "bad-sha", "engine-failure", "cancel-after-validation", "cancel-before-publication", "invalid-pointer"])
def test_gguf_publication(speech_probe, tmp_path, scenario):
    java, classes = speech_probe
    result = subprocess.run([java, "-cp", str(classes), "GgufProbe", scenario, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed: " + scenario in result.stdout
