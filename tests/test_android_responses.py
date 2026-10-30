"""Exact direct-account stream parser on the JVM, with synthetic events; no real account."""
from pathlib import Path
import os,shutil,subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'

@pytest.fixture(scope='module')
def responses_probe(tmp_path_factory):
    binaries=Path(os.environ.get('JAVA_HOME',''))/'bin'
    javac=str(binaries/'javac.exe') if (binaries/'javac.exe').exists() else shutil.which('javac')
    java=str(binaries/'java.exe') if (binaries/'java.exe').exists() else shutil.which('java')
    if not javac or not java:pytest.skip('JDK 17 required')
    classes=tmp_path_factory.mktemp('responses-java')
    files=[SOURCE/x for x in ['StrictJson.java','AndroidTools.java','BrainProvider.java','ProviderSse.java','ResponsesWire.java']]+[ROOT/'tests/android/ResponsesProbe.java']
    result=subprocess.run([javac,'-encoding','UTF-8','-d',str(classes),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return java,classes

@pytest.mark.parametrize('scenario',['text','native','duplicate-id','wrong-namespace','tools-off','partial','failed','duplicate-json','false-completion','cancel','bounded-comments','terminal'])
def test_direct_account_stream(responses_probe,scenario):
    java,classes=responses_probe
    result=subprocess.run([java,'-cp',str(classes),'ru.wildlik.wileyai.mobile.ResponsesProbe',scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
