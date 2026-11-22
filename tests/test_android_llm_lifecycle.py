"""Production Java lifecycle, fake native boundary. Not physical-device inference evidence."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'
CASES = ['reuse-json-independent','idle','model-change','pressure-idle','pressure-active',
         'memory-after','cancel-reuse','cancel-load','parallel','queued-cancel','late-cancel','switch-active',
         'close-service','owner-reopen','idle-active','ui-nonblocking','probe-exclusive','probe-cancel','utf8','stress',
         *('error-'+phase for phase in ['create','load','prepare','grammar','begin','next','finish'])]

@pytest.fixture(scope='module')
def lifecycle_probe(tmp_path_factory):
    binaries=Path(os.environ.get('JAVA_HOME',''))/'bin'
    javac=str(binaries/'javac.exe') if (binaries/'javac.exe').exists() else shutil.which('javac')
    java=str(binaries/'java.exe') if (binaries/'java.exe').exists() else shutil.which('java')
    if not java or not javac:pytest.skip('JDK 17 required')
    classes=tmp_path_factory.mktemp('android-c8')
    files=[SOURCE/'LocalModelSession.java',SOURCE/'LocalLlm.java',ROOT/'tests/android/LocalModelSessionProbe.java',ROOT/'tests/android/LocalLlmUiProbe.java',*sorted((ROOT/'tests/android/c8stubs').rglob('*.java'))]
    result=subprocess.run([javac,'-encoding','UTF-8','-d',str(classes),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return java,classes

@pytest.mark.parametrize('scenario',['late-stop','closed-screen','response-preferences'])
def test_local_model_main_loop(lifecycle_probe,scenario):
    java,classes=lifecycle_probe
    result=subprocess.run([java,'-cp',str(classes),'ru.wildlik.wileyai.mobile.LocalLlmUiProbe',scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('scenario',CASES)
def test_local_model_lifecycle(lifecycle_probe,scenario):
    java,classes=lifecycle_probe
    result=subprocess.run([java,'-cp',str(classes),'ru.wildlik.wileyai.mobile.LocalModelSessionProbe',scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
