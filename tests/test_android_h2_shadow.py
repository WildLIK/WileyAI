import subprocess
from pathlib import Path


def test_h2_bounded_copy_drop_capture_reset_and_decisions(tmp_path):
    root = Path(__file__).resolve().parents[1]
    src = root/'android/app/src/main/java/ru/wildlik/wileyai/mobile'
    subprocess.run(['javac','-encoding','UTF-8','-d',str(tmp_path),str(src/'H2Windows.java'),
                    str(root/'tests/android/H2WindowsProbe.java')],check=True)
    subprocess.run(['java','-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.H2WindowsProbe'],check=True)

