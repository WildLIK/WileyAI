import subprocess
from pathlib import Path


def test_frozen_livekit_decision_and_contiguous_pcm(tmp_path):
    root = Path(__file__).resolve().parents[1]
    src = root / "android/app/src/main/java/ru/wildlik/wileyai/mobile"
    subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(tmp_path),
         str(src / "WakeComparisonPcm.java"), str(root / "tests/android/WakeComparisonPcmProbe.java")],
        check=True,
    )
    subprocess.run(
        ["java", "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.WakeComparisonPcmProbe"],
        check=True,
    )
