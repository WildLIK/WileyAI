"""Compare frozen detectors on a local WileyAI NEXT 8 ZIP without using the microphone."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import wave
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from wake_next6 import AudioWindows, RATE, events, open_scores

ROOT = "WileyAI_Wake_Diagnostics/"
MAX_PCM_BYTES = 600 * RATE * 2
MAX_ENTRY = MAX_PCM_BYTES + 256 * 1024
VARIANTS = {
    "вайли": {"вайли", "уайли", "вай ли", "окей вайли", "окей уайли", "окей вай ли"},
    "окей вайли": {"окей вайли", "окей уайли", "окей вай ли"},
    "привет помощник": {"привет помощник"},
    "слушай помощник": {"слушай помощник"},
}
FROZEN_HEAD = "428d30048347b72ba75c006f8587d0220f0d319574bb8f5c1dfbd0c36c0beafb"


def exact_wake(text, preset):
    text = " ".join(re.sub(r"[,.!?]", " ", text.lower().replace("ё", "е")).split())
    return text.removesuffix(" давай поговорим") in VARIANTS[preset]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def metadata(bundle, name):
    entry = bundle.getinfo(ROOT + name)
    if entry.file_size > 24 * 1024 * 1024:
        raise ValueError(f"Metadata exceeds limit: {name}")
    return bundle.read(entry).decode("utf-8").splitlines()


def decode(bundle, ffmpeg, event):
    name = event["audio"]
    if not re.fullmatch(r"audio/[a-f0-9-]{36}_[a-z0-9_-]{1,60}\.(?:flac|wav)", name):
        raise ValueError("Unexpected audio member")
    entry = bundle.getinfo(ROOT + name)
    if entry.file_size > MAX_ENTRY:
        raise ValueError("Audio exceeds recording limit")
    encoded = bundle.read(entry)
    if sha(encoded) != event["sha256"]:
        raise ValueError("Audio checksum mismatch")
    if name.endswith(".flac"):
        if encoded[:4] != b"fLaC" or len(encoded) < 42 or encoded[4] & 127 or int.from_bytes(encoded[5:8], "big") != 34:
            raise ValueError("Invalid FLAC STREAMINFO")
        stream = int.from_bytes(encoded[18:26], "big")
        layout = (stream >> 44, 1 + ((stream >> 41) & 7), 1 + ((stream >> 36) & 31), stream & ((1 << 36) - 1))
    else:
        with wave.open(io.BytesIO(encoded)) as wav:
            layout = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth() * 8, wav.getnframes())
    if layout != (RATE, 1, 16, event["samples"]):
        raise ValueError("Encoded PCM format disagrees with metadata")
    raw = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", "pipe:0", "-t", "600.001",
                          "-acodec", "pcm_s16le", "-f", "s16le", "pipe:1"], input=encoded, check=True,
                         capture_output=True, timeout=60).stdout
    if len(raw) > MAX_PCM_BYTES or len(raw) % 2 or len(raw) // 2 != event["samples"]:
        raise ValueError("Decoded PCM length disagrees with event metadata")
    return np.frombuffer(raw, dtype="<i2")


def segments(event, length):
    starts = [s["file_start"] for s in event.get("spans", [])]
    if not starts:
        return [(0, length)]
    if starts[0] != 0 or any(a >= b for a, b in zip(starts, starts[1:])) or starts[-1] >= length:
        raise ValueError("Invalid discontinuity index")
    return list(zip(starts, starts[1:] + [length]))


def vosk_runner(model_path, *, detailed=False):
    import vosk

    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_path))

    def run(pcm, grammar, preset):
        decoder = vosk.KaldiRecognizer(model, RATE, grammar)
        decoder.SetWords(True)
        hits = []
        finals = []
        for start in range(0, len(pcm), 2048):
            block = pcm[start:start + 2048]
            if decoder.AcceptWaveform(block.tobytes()):
                result = json.loads(decoder.Result())
                words = result.get("result", ())
                confidence = min((w.get("conf", 0) for w in words), default=0)
                accepted = 0.75 <= confidence <= 1 and exact_wake(result.get("text", ""), preset)
                if detailed:
                    finals.append(dict(sample=start + len(block), confidence=confidence if words else None,
                                       text=result.get("text", ""), words=words, accepted=accepted))
                if accepted:
                    hits.append(start + len(block))
        return {"hits": hits, "finals": finals} if detailed else hits

    return run


def plix_runner(exports, frozen_path, *, detailed=False, intervention=None):
    from plix_next6 import PLiX, file_hash

    if file_hash(frozen_path) != FROZEN_HEAD:
        raise ValueError("Unexpected NEXT 6 configuration hash")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if any(file_hash(exports / name) != digest for name, digest in frozen["assets"].items()):
        raise ValueError("Unexpected PLiX artifact hash")
    encode = PLiX(exports, "multi")
    anchors = np.array(frozen["variant_prototypes"]["3"], dtype=np.float32)
    background = np.array(frozen["negative_bank"], dtype=np.float32)
    threshold = frozen["thresholds"]["3"]["threshold"]
    if intervention:
        from wake_next7 import detector
        config = json.loads(intervention.read_text(encoding="utf-8"))
        mode = config["method"]
        expected = {"short": "31a12ef25e66dc54856d33d837eeff4643f26d8f88a9e159a9a8ebe61c45451c",
                    "floor": "19329c2fbf116107abbff7ba4b7f1285af842e94cf578d4e9240cffd018962c4"}
        if file_hash(intervention) != expected.get(mode) or config["next6_config_sha256"] != FROZEN_HEAD:
            raise ValueError("Unexpected NEXT 7 configuration")
        encode = detector(encode, mode)
        threshold = config["calibration"]["threshold"]

    def run(pcm, grammar, preset):
        windows = AudioWindows()
        scores = []
        for start in range(0, len(pcm), 2048):
            for end, window in windows.feed(pcm[start:start + 2048]):
                score = open_scores(encode(window)[None, :], anchors, background)[0]
                scores.append((end / RATE, float(score)))
        hits = [round(time * RATE) for time in events(scores, threshold)]
        if detailed:
            return {"hits": hits, "scores": [(round(t * RATE), s) for t, s in scores], "threshold": threshold}
        return hits

    return run


def replay(bundle, ffmpeg, detectors):
    names = [entry.filename for entry in bundle.infolist()]
    if len(set(names)) != len(names) or len(names) > 3000:
        raise ValueError("Duplicate or oversized ZIP index")
    manifest = json.loads(metadata(bundle, "manifest.json")[0])
    if (manifest["schema"], manifest["sample_rate"], manifest["channels"], manifest["bits"]) != (1, RATE, 1, 16):
        raise ValueError("Unsupported audio format")
    rows = [json.loads(line) for line in metadata(bundle, "events.jsonl") if line.strip()]
    keys = [(item["session_id"], item["id"]) for item in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate event ID")
    presets = {}
    for row in rows:
        if row.get("grammar") and row.get("preset") in VARIANTS:
            previous = presets.get(row["session_id"])
            choice = (row["grammar"], row["preset"])
            if previous and choice != previous:
                # A continuous recording may cross configurations. Prefer the individual row only.
                presets[row["session_id"]] = (None, None)
            else:
                presets[row["session_id"]] = choice
    runs, linked, digests = {}, [], {}
    for event in rows:
        key = (event["session_id"], event["id"])
        parent = (key[0], event.get("audio_ref") or key[1])
        linked.append((key, parent, event))
        if not event.get("audio"):
            continue
        pcm = decode(bundle, ffmpeg, event)
        digest = sha(pcm.tobytes())
        digests.setdefault(digest, []).append(key)
        grammar, preset = event.get("grammar"), event.get("preset")
        if not grammar or preset not in VARIANTS:
            grammar, preset = presets.get(key[0], (None, None))
        local = {}
        for method, run in detectors.items():
            local[method] = []
            spans = event.get("spans", ())
            for i, (lo, hi) in enumerate(segments(event, len(pcm))):
                span = spans[i] if spans else {}
                span_grammar = span.get("grammar") or grammar
                span_preset = span.get("preset") or preset
                if method == "vosk" and (not span_grammar or span_preset not in VARIANTS):
                    local[method] = None
                    break
                local[method].extend(lo + hit for hit in run(pcm[lo:hi], span_grammar, span_preset))
        runs[key] = local

    compared = []
    for key, parent, event in linked:
        marker = event.get("file_event_sample", event.get("pre_samples"))
        start = event.get("file_start_sample", 0)
        stop = start + event.get("samples", 0)
        values = {}
        for method, hits in runs.get(parent, {}).items():
            values[method] = None if hits is None else [
                {"sample": hit, "ms_from_original_event": None if marker is None else round((hit - marker) * 1000 / RATE, 2)}
                for hit in hits if start <= hit <= stop
            ]
        compared.append({"session_id": key[0], "id": key[1], "kind": event.get("kind"),
                         "label": event.get("label"), "original_accepted": event.get("accepted"), "replay": values})
    return {
        "protocol": "2048 samples; no synthetic silence; resets at clip start and recorded discontinuities; "
                    "all finals; no shell, app actions or audio recording",
        "audio_files": len(runs),
        "duplicate_pcm": [keys for keys in digests.values() if len(keys) > 1],
        "events": compared,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--vosk-model", type=Path)
    parser.add_argument("--plix-exports", type=Path)
    parser.add_argument("--plix-config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeline", action="store_true", help="Audit and join overlapping passive event clips")
    parser.add_argument("--next7-dir", type=Path, help="Include both frozen NEXT 7 interventions in a timeline audit")
    args = parser.parse_args()
    if bool(args.plix_exports) != bool(args.plix_config) or not (args.vosk_model or args.plix_exports):
        parser.error("Choose Vosk and/or provide both frozen PLiX paths")
    detectors = {}
    if args.vosk_model:
        detectors["vosk"] = vosk_runner(args.vosk_model, detailed=args.timeline)
    if args.plix_exports:
        detectors["plix_next6"] = plix_runner(args.plix_exports, args.plix_config, detailed=args.timeline)
    if args.next7_dir:
        if not args.timeline or not args.plix_config:
            parser.error("--next7-dir requires --timeline and PLiX")
        for mode in ("short", "floor"):
            detectors[mode] = plix_runner(args.plix_exports, args.plix_config, detailed=True,
                                          intervention=args.next7_dir / (mode + ".config.json"))
    with ZipFile(args.archive) as bundle:
        if args.timeline:
            from wake_diagnostic_timeline import audit
            result = audit(bundle, args.ffmpeg, detectors, decode, metadata)
        else:
            result = replay(bundle, args.ffmpeg, detectors)
    with args.archive.open("rb") as archive:
        result["archive_sha256"] = hashlib.file_digest(archive, "sha256").hexdigest()
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
