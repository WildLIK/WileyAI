from pathlib import Path
import shutil,subprocess,pytest
ROOT=Path(__file__).resolve().parents[1]
def test_wave_geometry_and_fps(tmp_path):
 j,javac=shutil.which('java'),shutil.which('javac')
 if not j or not javac: pytest.skip('JDK unavailable')
 files=[ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile/NeonWaveMath.java',ROOT/'tests/android/NeonWaveMathProbe.java']
 p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([j,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.NeonWaveMathProbe'],capture_output=True,text=True);assert p.returncode==0,p.stderr


def test_fft_frequencies_and_dynamic_range(tmp_path):
 j,javac=shutil.which('java'),shutil.which('javac')
 if not j or not javac: pytest.skip('JDK unavailable')
 base=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'
 files=[base/'NeonWaveMath.java',base/'VoiceSpectrum.java',ROOT/'tests/android/VoiceSpectrumProbe.java']
 p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([j,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.VoiceSpectrumProbe'],capture_output=True,text=True);assert p.returncode==0,p.stderr
