"""Exercise LocalVoice against a deterministic fake TTS; no device or audio."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_local_voice_lifecycle(tmp_path):
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac: pytest.skip('JDK required')
    files=[ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile/LocalVoice.java', ROOT/'tests/android/LocalVoiceProbe.java']
    files+=list((ROOT/'tests/android/tts_stubs').rglob('*.java'))
    files += [ROOT/'tests/android/c8stubs/android/os/Handler.java', ROOT/'tests/android/c8stubs/android/os/Looper.java']
    compiled=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert compiled.returncode==0,compiled.stderr
    ran=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.LocalVoiceProbe'],capture_output=True,text=True,timeout=15)
    assert ran.returncode==0,ran.stdout+ran.stderr
