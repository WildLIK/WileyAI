from pathlib import Path
import shutil, subprocess, pytest
ROOT=Path(__file__).resolve().parents[1]
def test_chat_readiness_without_android_or_user_settings(tmp_path):
 java,javac=shutil.which("java"),shutil.which("javac")
 if not java or not javac: pytest.skip("JDK unavailable")
 files=[ROOT/"android/app/src/main/java/ru/wildlik/wileyai/mobile/ChatReadiness.java",ROOT/"tests/android/ChatReadinessProbe.java"]
 p=subprocess.run([javac,"-encoding","UTF-8","-d",str(tmp_path),*map(str,files)],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([java,"-cp",str(tmp_path),"ru.wildlik.wileyai.mobile.ChatReadinessProbe"],capture_output=True,text=True);assert p.returncode==0,p.stderr
