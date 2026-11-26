from pathlib import Path
import subprocess


def test_first_wake_command_preserves_meaning_and_requires_exact_route_for_homophones(tmp_path):
    root = Path(__file__).resolve().parents[1]
    src = root / "android/app/src/main/java/ru/wildlik/wileyai/mobile"
    subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(tmp_path),
                    *[str(src / name) for name in ("WakePhrase.java", "PhoneCommands.java", "MediaCommands.java", "SpokenNames.java")],
                    str(root / "tests/android/WakeCommandExtractionProbe.java")], check=True)
    subprocess.run(["java", "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.WakeCommandExtractionProbe"], check=True)
