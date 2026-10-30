"""Real pure-Java plan parsing, scope, schema and date logic. Device execution is tested separately."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'

@pytest.fixture(scope='module')
def tools_probe(tmp_path_factory):
    binaries=Path(os.environ.get('JAVA_HOME',''))/'bin'
    javac=str(binaries/'javac.exe') if (binaries/'javac.exe').exists() else shutil.which('javac')
    java=str(binaries/'java.exe') if (binaries/'java.exe').exists() else shutil.which('java')
    if not javac or not java:pytest.skip('JDK 17 required')
    classes=tmp_path_factory.mktemp('android-tools')
    files=[SOURCE/name for name in ['StrictJson.java','AndroidTools.java','ToolRun.java','StructuredActionAdapter.java']]+[ROOT/'tests/android/AndroidToolsProbe.java']
    result=subprocess.run([javac,'-encoding','UTF-8','-d',str(classes),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return java,classes

@pytest.mark.parametrize('scenario',['strict-json','validate','plan-limits','consent-cancel-expiry','reminder-time','retrieval-and-injection'])
def test_android_tool_policy(tools_probe,scenario):
    java,classes=tools_probe
    result=subprocess.run([java,'-cp',str(classes),'AndroidToolsProbe',scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
