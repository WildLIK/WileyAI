"""Fetch the public 3D-Speaker CAM++ export and pin the bytes used by Android."""

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen

NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{NAME}"
SIZE = 28_281_165
SHA256 = "53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b"


def valid(path):
    if not path.is_file() or path.stat().st_size != SIZE:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == SHA256


def main():
    target = Path(__file__).resolve().parents[1] / "local/android-public-models/wake-stage1/campplus.onnx"
    if valid(target):
        print("Verified CAM++ is already available.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
        partial = Path(stream.name)
    try:
        with urlopen(URL, timeout=60) as source, partial.open("wb") as stream:
            received = 0
            while block := source.read(128 * 1024):
                received += len(block)
                if received > SIZE:
                    raise ValueError("CAM++ download exceeds the pinned size")
                stream.write(block)
        if not valid(partial):
            raise ValueError("CAM++ checksum or size differs from the pinned release")
        os.replace(partial, target)
        print("Verified CAM++ ready for Android packaging.")
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
