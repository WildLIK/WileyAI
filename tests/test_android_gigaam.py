"""GigaAM runtime lifecycle, C9 context matcher and sherpa glue against fakes; no real weights."""
from pathlib import Path
import shutil
import os
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'


def _run(tmp_path, files, main_class):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    compiled = subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(tmp_path), *map(str, files)], capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stderr
    launched = subprocess.run([java, '-Dfile.encoding=UTF-8', '-cp', str(tmp_path), main_class], capture_output=True, text=True, timeout=120)
    assert launched.returncode == 0, launched.stdout + launched.stderr


def test_gigaam_session_fake_backend(tmp_path):
    files = [SOURCE / x for x in ['GigaAmModel.java', 'GigaAmSession.java', 'LocalModelSession.java']]
    files.append(ROOT / 'tests/android/GigaAmProbe.java')
    _run(tmp_path, files, 'ru.wildlik.wileyai.mobile.GigaAmProbe')


def test_screen_context_matcher(tmp_path):
    files = [SOURCE / 'ScreenContextMatcher.java']
    files.append(ROOT / 'tests/android/ScreenContextMatcherProbe.java')
    _run(tmp_path, files, 'ru.wildlik.wileyai.mobile.ScreenContextMatcherProbe')


def test_gigaam_sherpa_glue_stub_api(tmp_path):
    files = [SOURCE / x for x in ['GigaAmModel.java', 'GigaAmSession.java', 'GigaAmSherpa.java']]
    files += list((ROOT / 'tests/android/gigaam_stubs').rglob('*.java'))
    files.append(ROOT / 'tests/android/GigaAmSherpaGlueProbe.java')
    _run(tmp_path, files, 'ru.wildlik.wileyai.mobile.GigaAmSherpaGlueProbe')


def test_gigaam_read_only_and_isolated():
    """The ASR runtime stays pure Java, never logs screen or speech content, and old engines remain wired."""
    session = (SOURCE / 'GigaAmSession.java').read_text(encoding='utf-8')
    matcher = (SOURCE / 'ScreenContextMatcher.java').read_text(encoding='utf-8')
    for banned in ('android.', 'SharedPreferences', 'android.util.Log', 'LocalChatRepository'):
        assert banned not in session, banned
    for banned in ('SharedPreferences', 'android.util.Log', 'performAction', 'dispatchGesture'):
        assert banned not in matcher, banned
    engine = (SOURCE / 'GigaAmSpeechEngine.java').read_text(encoding='utf-8')
    for banned in ('ScreenObservationService', 'LocalChatRepository'):
        assert banned not in engine, banned
    for line in engine.splitlines():
        if 'android.util.Log.' in line:
            assert '"WileyVoice"' in line and not any(secret in line for secret in ('recognized[0]', 'output.text()', 'buffer', 'failure.getMessage()'))
    hands_free = (SOURCE / 'HandsFreeService.java').read_text(encoding='utf-8')
    main_activity = (SOURCE / 'MainActivity.java').read_text(encoding='utf-8')
    assert 'speech.start(model, listener, waiting)' in hands_free  # existing Vosk path preserved
    assert 'offlineSpeech.start(speechModels.active(), recognition)' in main_activity
    assert 'gigaAm.start(waiting, listener)' in hands_free and 'gigaAmSpeech.start(15000, recognition)' in main_activity

def test_gigaam_official_sherpa_configuration_api(tmp_path):
    import zipfile
    aar = ROOT / 'local/android-libs/sherpa-onnx-1.13.5.aar'
    kotlin = ROOT / 'local/android-libs/kotlin-stdlib-1.9.24.jar'
    if not aar.exists() or not kotlin.exists(): pytest.skip('Optional verified sherpa AAR unavailable')
    with zipfile.ZipFile(aar) as z: (tmp_path/'sherpa.jar').write_bytes(z.read('classes.jar'))
    files = [SOURCE/x for x in ['GigaAmModel.java','GigaAmSession.java','GigaAmSherpa.java']]
    files += [ROOT/'tests/android/gigaam_stubs/android/content/res/AssetManager.java', ROOT/'tests/android/GigaAmRealApiProbe.java']
    p=subprocess.run([shutil.which('javac'),'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True,timeout=60)
    assert p.returncode==0,p.stderr
    cp=os.pathsep.join([str(tmp_path),str(tmp_path/'sherpa.jar'),str(kotlin)])
    p=subprocess.run([shutil.which('java'),'-cp',cp,'ru.wildlik.wileyai.mobile.GigaAmRealApiProbe'],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stdout+p.stderr

def test_pcm_chunks_are_independent(tmp_path):
    javac,java=shutil.which('javac'),shutil.which('java')
    if not javac or not java:pytest.skip('JDK required')
    files=[SOURCE/'PcmChunk.java',ROOT/'tests/android/PcmChunkProbe.java']
    p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    p=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.PcmChunkProbe'],capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stdout+p.stderr
