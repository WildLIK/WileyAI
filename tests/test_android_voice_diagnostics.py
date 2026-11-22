"""Voice command diagnostics snapshot: statuses only, no content, no re-execution."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'


def test_voice_diagnostics_snapshot(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    files = [SOURCE / 'VoiceDiagnostics.java']
    files.append(ROOT / 'tests/android/VoiceDiagnosticsProbe.java')
    compiled = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stderr
    launched = subprocess.run([java, '-Dfile.encoding=UTF-8', '-cp', str(tmp_path), 'ru.wildlik.wileyai.mobile.VoiceDiagnosticsProbe'], capture_output=True, text=True, timeout=60)
    assert launched.returncode == 0, launched.stdout + launched.stderr


def test_voice_diagnostics_observational_and_content_free():
    """The snapshot is volatile, holds no session references, never logs, never re-executes."""
    code = (SOURCE / 'VoiceDiagnostics.java').read_text(encoding='utf-8')
    for banned in ('android.', 'SharedPreferences', 'java.io.File', 'openFileOutput', 'android.util.Log',
                   'LocalVoice', 'AndroidToolExecutor', 'ScreenDispatcher', 'ScreenObservationService',
                   'BrainController', 'performAction', 'dispatchGesture'):
        assert banned not in code, banned
    hands_free = (SOURCE / 'HandsFreeService.java').read_text(encoding='utf-8')
    # The recognized utterance never becomes a diagnostics argument (statuses only).
    import re
    for match in re.finditer(r'VoiceDiagnostics\.\w+\(([^;\n]*)\)', hands_free):
        args = match.group(1)
        assert not re.search(r'(?:^|[(,]\s*)(?:text|heard)\s*[,)]', args), match.group(0)
        assert 'heard' not in args, match.group(0)
    dispatcher = (SOURCE / 'ScreenDispatcher.java').read_text(encoding='utf-8')
    # The request text is never handed to diagnostics: only kinds, statuses and counts.
    for line in dispatcher.splitlines():
        if 'VoiceDiagnostics.' in line:
            assert 'request)' not in line and 'request,' not in line, line
    observation = (SOURCE / 'ScreenObservationService.java').read_text(encoding='utf-8')
    for banned in ('detail","text', 'elements","text'):
        assert banned not in observation, banned
