"""Fetch the exact reviewed llama.cpp source; no weights, SDKs or user settings."""
from pathlib import Path
import hashlib
import io
import urllib.request
import zipfile

REVISION = "8642541b255bfb5dc39cd351a178be09013a55d6"
SHA256 = "2f0805273e93ce4f140a8e9d3bf8864e2eafbb0b2edb468b4b2d520a258aba42"
ROOT = Path(__file__).resolve().parents[1] / "local/android-native"
TARGET = ROOT / ("llama.cpp-" + REVISION)

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    if (TARGET / ".wiley-source-verified").exists():
        print("llama.cpp source ready: " + REVISION)
        return
    archive = ROOT / "llama-source.zip"
    if not archive.exists():
        request = urllib.request.Request("https://codeload.github.com/ggml-org/llama.cpp/zip/" + REVISION, headers={"User-Agent": "WileyAI-build"})
        with urllib.request.urlopen(request, timeout=60) as source, archive.open("wb") as output:
            while chunk := source.read(1024 * 1024): output.write(chunk)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("llama.cpp source checksum mismatch; inspect local/android-native/llama-source.zip")
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            if not (ROOT / item.filename).resolve().is_relative_to(ROOT.resolve()): raise ValueError("Unsafe source ZIP")
        source.extractall(ROOT)
    (TARGET / ".wiley-source-verified").write_text(REVISION, encoding="ascii")
    print("llama.cpp source ready: " + REVISION)

if __name__ == "__main__": main()
