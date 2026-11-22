"""Real observation policy and service against fake Android nodes; no real screen."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'

def test_fake_accessibility_tree(tmp_path):
    javac,java=shutil.which('javac'),shutil.which('java')
    if not javac or not java:pytest.skip('JDK required')
    files=[SOURCE/x for x in ['ScreenPrivacy.java','ScreenRequest.java','ScreenObservationService.java']]
    files += list((ROOT/'tests/android/screen_stubs').rglob('*.java'))
    files.append(ROOT/'tests/android/ScreenObservationProbe.java')
    p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    p=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.ScreenObservationProbe'],capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stdout+p.stderr

def test_screen_model_gate_fake_provider(tmp_path):
    javac,java=shutil.which('javac'),shutil.which('java')
    if not javac or not java:pytest.skip('JDK required')
    files=[SOURCE/x for x in ['StrictJson.java','AndroidTools.java','ToolRun.java','StructuredActionAdapter.java','BrainProvider.java','ScreenModelGate.java','ScreenRequest.java']]
    files.append(ROOT/'tests/android/ScreenModelGateProbe.java')
    p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    p=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.ScreenModelGateProbe'],capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stdout+p.stderr

def test_screen_observation_read_only_and_isolated():
    """No actions, gestures, logging, history or preference writes on the C9 path."""
    main=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    for name in ('ScreenObservationService.java','ScreenDispatcher.java'):
        code=(main/name).read_text(encoding='utf-8')
        for banned in ('performAction','dispatchGesture','GLOBAL_ACTION','setClipboard','setText(','android.util.Log','LocalChatRepository','history.submit','.edit()'):
            assert banned not in code,f'{name}: {banned}'
    gate=(main/'ScreenModelGate.java').read_text(encoding='utf-8')
    assert 'Cloud' not in gate and 'LOCAL' in gate  # screen data reaches only the local provider
