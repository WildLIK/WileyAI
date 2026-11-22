"""Retrospective comparison of two fixed final-confidence rules. No transcripts or audio output."""
import argparse
from collections import Counter
import csv
import io
import json
from pathlib import Path
import statistics
import subprocess
import wave
import zipfile

import vosk

RATE = 16000
BLOCK_BYTES = 4096
THRESHOLDS = (0.75, 0.90)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_pcm(source):
    with wave.open(source, "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (RATE, 1, 2)
        return audio.readframes(audio.getnframes())


def replay(model, grammar, allowed, pcm, *, pad=False):
    if pad:
        pcm += bytes(RATE * 2)
    decoder = vosk.KaldiRecognizer(model, RATE, json.dumps(grammar, ensure_ascii=False))
    decoder.SetWords(True)
    hits = []
    for at in range(0, len(pcm), BLOCK_BYTES):
        chunk = pcm[at:at + BLOCK_BYTES]
        if not decoder.AcceptWaveform(chunk):
            continue
        result = json.loads(decoder.Result())
        words = result.get("result", [])
        text = " ".join(result.get("text", "").lower().replace("ё", "е").split())
        if not words or text not in allowed:
            continue
        confidence = min(word.get("conf", 0) for word in words)
        if 0.75 <= confidence <= 1.0:
            hits.append((confidence, (at + len(chunk)) / (2 * RATE), words[-1].get("end")))
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=Path("local/wakeword26b"))
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    work = args.work
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(work / "vosk-device-model"))
    grammar = read_json(work / "b10/vosk-audit-summary.json")["grammar"]
    # Also allow the complete canonical forms recognized by Android, outside the library grammar.
    allowed = set(grammar[:-1]) | {"вайли", "окей вайли", "вайли давай поговорим", "окей вайли давай поговорим"}
    counts = {str(t): Counter() for t in THRESHOLDS}
    totals = Counter()
    delay = {str(t): [] for t in THRESHOLDS}

    def positive(group, pcm, end=None):
        totals[group] += 1
        hits = replay(model, grammar, allowed, pcm, pad=True)
        for value in THRESHOLDS:
            qualifying = [row for row in hits if row[0] >= value]
            key = str(value)
            if qualifying:
                counts[key][group] += 1
                if end is not None:
                    first = qualifying[0][1]
                    counts[key]["owner_early"] += first < end
                    delay[key].append(first - end)

    with (work / "owner-annotations-reviewed.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    with zipfile.ZipFile(work / "owner-export-20261116-184820.zip") as archive:
        for row in rows:
            assert row["status"] == "confirmed"
            pcm = read_pcm(io.BytesIO(archive.read(row["id"] + ".wav")))
            start, end = float(row["wake_start_s"]), float(row["wake_end_s"])
            positive("owner", pcm, end)
            positive("truncated_owner_prefix", pcm[:2 * round(RATE * (start + end) / 2)])
    for row in read_json(work / "b11/synthetic-catalog.json")["records"]:
        positive("synthetic_" + row["declared_variant"], read_pcm(str(Path("WileyAI21Голос") / row["wav_path"])))

    negative_seconds = 0
    manifest = read_json(work / "b6/negative-manifest.json")["test"]
    for row in manifest:
        pcm = subprocess.run([
            str(args.ffmpeg), "-nostdin", "-loglevel", "error", "-t", "30", "-i",
            str(args.corpus / "audios" / row["audio_file"]), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1",
        ], capture_output=True, check=True, timeout=60).stdout
        negative_seconds += len(pcm) / (2 * RATE)
        hits = replay(model, grammar, allowed, pcm)
        for value in THRESHOLDS:
            counts[str(value)]["negative_events"] += sum(row[0] >= value for row in hits)

    with (work / "b10/review-final.csv").open(encoding="utf-8-sig") as stream:
        labels = {r["event_id"] for r in csv.DictReader(stream) if r["verdict"] == "false_detection"}
    historical = [
        row.get("confidence", 0) for i, row in enumerate(read_json(work / "b10/vosk-final-events.json"), 1)
        if f"F{i:03d}" in labels
    ]
    result = {
        "inputs": dict(totals), "negative_files": len(manifest), "negative_seconds": negative_seconds,
        "retrospective_manual_false_count": len(historical),
        "results": {
            str(t): {
                **{key: counts[str(t)][key] for key in totals},
                "owner_early": counts[str(t)]["owner_early"],
                "owner_lag_median_ms": round(1000 * statistics.median(delay[str(t)]), 1) if delay[str(t)] else None,
                "negative_events": counts[str(t)]["negative_events"],
                "negative_events_per_hour": round(counts[str(t)]["negative_events"] * 3600 / negative_seconds, 2),
                "manual_false_retained": sum(value >= t for value in historical),
            } for t in THRESHOLDS
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
