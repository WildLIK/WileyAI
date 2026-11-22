from pathlib import Path
import shutil,subprocess,pytest
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'
def test_app_selection(tmp_path):
 javac,java=shutil.which('javac'),shutil.which('java')
 if not javac or not java:pytest.skip('JDK missing')
 files=[SRC/x for x in ['AppSelection.java','AppRegistry.java','SpokenNames.java']]+[ROOT/'tests/android/AppSelectionProbe.java']
 result=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True);assert result.returncode==0,result.stderr
 result=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.AppSelectionProbe'],capture_output=True,text=True);assert result.returncode==0,result.stderr
