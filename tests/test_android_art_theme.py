from pathlib import Path
import shutil,subprocess,pytest
ROOT=Path(__file__).resolve().parents[1]
def test_art_geometry_and_animation_policy(tmp_path):
 java,javac=shutil.which('java'),shutil.which('javac')
 if not java or not javac:pytest.skip('JDK unavailable')
 files=[ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile/ArtThemeMath.java',ROOT/'tests/android/ArtThemeMathProbe.java']
 p=subprocess.run([javac,'-encoding','UTF-8','-d',str(tmp_path),*map(str,files)],capture_output=True,text=True);assert p.returncode==0,p.stderr
 p=subprocess.run([java,'-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.ArtThemeMathProbe'],capture_output=True,text=True);assert p.returncode==0,p.stderr

def test_webp_preserves_supplied_pixels():
 image=pytest.importorskip('PIL.Image')
 pairs=[('WileyAI_Aurora_Ocean.png','aurora.webp'),('WileyAI_Icy_Light_Blizzard.png','ice.webp'),('WileyAI_Red_Sakura.png','ember.webp'),('WileyAI_Cosmic_Nebula.png','nebula.webp')]
 for original,asset in pairs:
  with image.open(ROOT/'design/themes/source'/original) as a, image.open(ROOT/'android/app/src/main/assets/art_themes'/asset) as b:
   assert a.size==b.size
   assert a.convert('RGBA').tobytes()==b.convert('RGBA').tobytes()
