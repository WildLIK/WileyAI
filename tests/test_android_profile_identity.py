from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_name_and_address_are_distinct(tmp_path):
    java, javac = shutil.which("java"), shutil.which("javac")
    if not java or not javac:
        pytest.skip("JDK is unavailable")
    source = ROOT / "android/app/src/main/java/ru/wildlik/wileyai/mobile/ProfileIdentity.java"
    probe = ROOT / "tests/android/ProfileIdentityProbe.java"
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(tmp_path), str(source), str(probe)], check=True)
    subprocess.run([java, "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.ProfileIdentityProbe"], check=True)
