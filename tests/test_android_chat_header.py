from pathlib import Path
import shutil, subprocess, pytest
ROOT=Path(__file__).resolve().parents[1]
def test_source_changes_only_after_an_explicit_matching_choice(tmp_path):
 java,javac=shutil.which('java'),shutil.which('javac')
 if not java or not javac:pytest.skip('JDK unavailable')
 files=[ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile/ChatHeaderPolicy.java',ROOT/'tests/android/ChatHeaderPolicyProbe.java']
 result=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 result=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.ChatHeaderPolicyProbe'],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
