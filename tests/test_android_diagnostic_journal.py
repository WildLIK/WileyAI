from pathlib import Path
import shutil,subprocess,pytest
ROOT=Path(__file__).resolve().parents[1]
def test_bounded_private_journal(tmp_path):
 java,javac=shutil.which("java"),shutil.which("javac")
 if not java or not javac: pytest.skip("JDK unavailable")
 files=[ROOT/"android/app/src/main/java/ru/wildlik/wileyai/mobile/DiagnosticJournal.java",ROOT/"android/app/src/main/java/ru/wildlik/wileyai/mobile/DiagnosticFormatter.java",ROOT/"tests/android/DiagnosticJournalProbe.java"]
 p=subprocess.run([javac,"-encoding","UTF-8","-d",str(tmp_path),*map(str,files)],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([java,"-cp",str(tmp_path),"ru.wildlik.wileyai.mobile.DiagnosticJournalProbe",str(tmp_path)],capture_output=True,text=True);assert p.returncode==0,p.stderr
