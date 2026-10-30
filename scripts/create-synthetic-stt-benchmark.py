"""Create a small explicitly synthetic corpus; no microphone is used."""
import argparse
import io
import json
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.voice import Voice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", type=Path, default=Path("data"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    voice = Voice(args.root)
    phrases = [("Открой Блендер.", "Блендер"), ("Запусти О Б С.", "О Б С"), ("Не открывай Блендер.", ""), ("Расскажи про программу.", "")]
    rows = []
    for index, (phrase, target) in enumerate(phrases):
        path = args.output / f"synthetic-{index}.wav"
        path.write_bytes(voice.synthesize(phrase, "irina", engine="piper"))
        rows.append({"audio": path.name, "reference": phrase, "expected_target": target, "category": "synthetic-piper"})
    path = args.output / "silence.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000); output.writeframes(b"\0" * 32000)
    rows.append({"audio": path.name, "reference": "", "expected_target": "", "category": "synthetic-silence"})
    # Add a reproducible instrumental-like tone underneath the first phrase.
    with wave.open(str(args.output / "synthetic-0.wav"), "rb") as source:
        rate = source.getframerate(); raw = source.readframes(source.getnframes())
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    backing = [max(-32768, min(32767, int(value + 1400 * math.sin(2 * math.pi * 220 * index / rate)))) for index, value in enumerate(samples)]
    with wave.open(str(args.output / "synthetic-music.wav"), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(struct.pack("<" + "h" * len(backing), *backing))
    rows.append({"audio": "synthetic-music.wav", "reference": "Открой Блендер.", "expected_target": "Блендер", "category": "synthetic-music"})
    for label, phrase, target in [("unknown", "Открой квантовый редактор.", "квантовый редактор"), ("repeat", "Открой блендер. Открой блендер.", "")]:
        path = args.output / f"synthetic-{label}.wav"
        path.write_bytes(voice.synthesize(phrase, "irina", engine="piper"))
        rows.append({"audio": path.name, "reference": phrase, "expected_target": target, "category": "synthetic-" + label})
    # Synthesized words separated by a one-second PCM pause.
    parts = []
    for phrase in ("Открой", "блендер"):
        with wave.open(io.BytesIO(voice.synthesize(phrase, "irina", engine="piper")), "rb") as source:
            if source.getframerate() != rate or source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise ValueError("Unexpected Piper PCM format")
            parts.append(source.readframes(source.getnframes()))
    with wave.open(str(args.output / "synthetic-pause.wav"), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(parts[0] + b"\0" * rate * 2 + parts[1])
    rows.append({"audio": "synthetic-pause.wav", "reference": "Открой блендер", "expected_target": "блендер", "category": "synthetic-pause"})
    (args.output / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "manifest.json")


if __name__ == "__main__":
    main()
