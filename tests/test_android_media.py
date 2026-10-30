"""Real Java command and conversation policy checks without Android framework mocks."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"android/app/src/main/java/ru/wildlik/wileyai/mobile"

@pytest.fixture(scope="module")
def media_probe(tmp_path_factory):
    binaries=Path(os.environ.get("JAVA_HOME",""))/"bin"
    javac=str(binaries/"javac.exe") if (binaries/"javac.exe").exists() else shutil.which("javac")
    java=str(binaries/"java.exe") if (binaries/"java.exe").exists() else shutil.which("java")
    if not javac or not java: pytest.skip("JDK 17 required")
    classes=tmp_path_factory.mktemp("media-java")
    files=[SOURCE/name for name in ["SpokenNames.java","PhoneCommands.java","MediaCommands.java","ConversationMode.java","WakePhrase.java"]]+[ROOT/"tests/android/MediaCommandsProbe.java",ROOT/"tests/android/PhoneCommandsProbe.java"]
    result=subprocess.run([javac,"-encoding","UTF-8","-d",str(classes),*map(str,files)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return java,classes

@pytest.mark.parametrize("scenario",["transport","routing","search","seek","reject","conversation","wake-conversation"])
def test_media_and_conversation(media_probe,scenario):
    java,classes=media_probe
    result=subprocess.run([java,"-cp",str(classes),"MediaCommandsProbe",scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr

def test_previous_phone_commands(media_probe):
    java,classes=media_probe
    result=subprocess.run([java,"-cp",str(classes),"PhoneCommandsProbe"],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
