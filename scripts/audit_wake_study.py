"""Audit one or more Android study exports locally, without extracting WAV files."""

import argparse
import csv
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import wave
import zipfile

RATE = 16000
MAX_PCM = 120 * RATE * 2
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ALIAS = re.compile(r"[a-z0-9][a-z0-9_-]{1,23}")
SPLITS = {"development", "validation", "test"}


def require(condition, error):
    if not condition:
        raise ValueError(error)


def read_audio(bundle, member):
    require(bundle.getinfo(member).file_size <= MAX_PCM + 65536, "WAV exceeds size limit")
    with wave.open(io.BytesIO(bundle.read(member)), "rb") as wav:
        require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, RATE), "Expected PCM16 mono 16 kHz")
        frames = wav.getnframes()
        require(8000 <= frames <= MAX_PCM // 2, "Unexpected duration")
        pcm = wav.readframes(frames)
        require(len(pcm) == 2 * frames, "Truncated WAV")
        return pcm


def inspect(paths, prior_pcm_hashes=(), reviewed=None):
    known = set(prior_pcm_hashes)
    sessions, speakers, ids = {}, {}, set()
    counts, sample_counts = Counter(), Counter()
    inputs = []
    for path in paths:
        with zipfile.ZipFile(path) as bundle:
            members = bundle.namelist()
            names = set(members)
            require(len(names) == len(members) <= 201, "Duplicate ZIP entry or too many files")
            require("manifest.csv" in names and bundle.getinfo("manifest.csv").file_size <= 65536, "Missing or oversized manifest")
            manifest = csv.DictReader(io.StringIO(bundle.read("manifest.csv").decode("utf-8-sig")))
            expected = {"manifest.csv"}
            for row in manifest:
                sample, session, speaker = row["id"], row["session_id"], row["speaker_id"]
                require(UUID.fullmatch(sample) and UUID.fullmatch(session) and ALIAS.fullmatch(speaker), "Invalid sample or session identity")
                require(sample not in ids, "Sample ID repeated across exports")
                ids.add(sample)
                split, kind = row["split"], row["kind"]
                require(split in SPLITS and kind in {"positive", "negative"}, "Invalid split or label type")
                file, sidecar = sample + ".wav", sample + ".json"
                require(row["file"] == file and {file, sidecar} <= names, "Missing WAV or JSON")
                require(bundle.getinfo(sidecar).file_size <= 8192, "JSON exceeds size limit")
                expected.update((file, sidecar))
                meta = json.loads(bundle.read(sidecar))
                require(meta["schema"] == 1 and meta["sample_rate"] == RATE and meta["channels"] == 1
                        and meta["format"] == "pcm_s16le", "Unexpected sample schema")
                require(all(str(meta[key]) == row[key] for key in
                            ("id", "session_id", "speaker_id", "split", "kind", "phrase", "voice_level",
                             "environment", "started_at_ms", "samples")), "Manifest and JSON differ")
                require(meta["distance_cm"] / 100 == float(row["distance_m"]), "Distance metadata differs")
                require(meta["vosk"]["status"] == row["vosk_status"] in
                        {"accepted", "not_detected", "unavailable"}, "Vosk status differs")
                role = meta.get("speaker_role", "")
                speech = meta.get("speech_kind", "")
                require(role in {"", "unknown", "owner", "other"}, "Invalid speaker role")
                require(speech in ({"", "wake"} if kind == "positive" else {"", "confusable", "ordinary", "noise"}),
                        "Speech category disagrees with label")
                require(row.get("speaker_role", "") == role and row.get("speech_kind", "") == speech,
                        "Manifest speech metadata differs")
                require(speakers.setdefault(speaker, split) == split, "A speaker spans more than one split")
                session_fields = tuple(row[key] for key in ("speaker_id", "split", "voice_level", "distance_m", "environment", "started_at_ms"))
                require(sessions.setdefault(session, session_fields) == session_fields, "A session has conflicting metadata")
                pcm = read_audio(bundle, file)
                samples = len(pcm) // 2
                require(samples == int(row["samples"]), "Duration metadata differs")
                sha = hashlib.sha256(pcm).hexdigest()
                require(sha not in known, "Duplicate decoded PCM in new or earlier data")
                known.add(sha)
                if reviewed is not None:
                    start_text, end_text = reviewed[sample] if kind == "positive" else ("", "")
                else:
                    start_text, end_text = row["wake_start_s"], row["wake_end_s"]
                start, end = None, None
                if start_text or end_text:
                    require(kind == "positive" and start_text and end_text, "Unexpected or partial wake timing")
                    start, end = float(start_text), float(end_text)
                    require(math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= samples / RATE,
                            "Reviewed interval outside audio")
                counts[split, kind] += 1
                sample_counts[split, kind] += samples
                inputs.append({"archive": path, "member": file, "split": split, "kind": kind, "start": start,
                               "end": end, "pcm_sha256": sha, "speaker": speaker, "session_id": session,
                               "session_start_ms": int(row["started_at_ms"]), "phrase": row["phrase"]})
            require(names == expected, "Unlisted entry in ZIP")
    require(ids, "No recordings found")
    return {"schema": 1, "sessions": len(sessions), "speakers": len(speakers),
            "counts": {f"{split}_{kind}": count for (split, kind), count in counts.items()},
            "seconds": {f"{split}_{kind}": n / RATE for (split, kind), n in sample_counts.items()},
            "positives_needing_review": sum(r["kind"] == "positive" and r["end"] is None for r in inputs)}, inputs


def owner_fingerprints(path):
    with zipfile.ZipFile(path) as bundle:
        return {hashlib.sha256(read_audio(bundle, name)).hexdigest()
                for name in bundle.namelist() if name.endswith(".wav")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--prior-owner", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    previous = owner_fingerprints(args.prior_owner) if args.prior_owner is not None else ()
    report, _ = inspect(args.archives, previous)
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        with args.output.open("x", encoding="utf-8") as file:
            file.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
