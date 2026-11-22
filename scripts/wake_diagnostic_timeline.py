"""Audit passive NEXT 8 exports on the original capture sample clock."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import time

import numpy as np

RATE = 16000
ROOT = "WileyAI_Wake_Diagnostics/"


def joined(clips):
    """Yield coverage islands. Any differing samples on an overlap invalidate its coordinates."""
    start = None
    audio = None
    for pos, pcm in sorted(clips, key=lambda item: item[0]):
        if audio is None or pos > start + len(audio):
            if audio is not None:
                yield start, audio
            start, audio = pos, pcm
            continue
        offset = pos - start
        overlap = min(len(audio) - offset, len(pcm))
        if not np.array_equal(audio[offset:offset + overlap], pcm[:overlap]):
            raise ValueError("PCM mismatch on capture overlap")
        if overlap < len(pcm):
            audio = np.concatenate((audio, pcm[overlap:]))
    if audio is not None:
        yield start, audio


def keyed(rows, fields):
    result = {}
    for row in rows:
        k = tuple(row[name] for name in fields)
        if k in result:
            raise ValueError("Duplicate identity: " + str(k))
        result[k] = row
    return result


def audit(bundle, ffmpeg, detectors, decode, metadata):
    members = bundle.namelist()
    if len(set(members)) != len(members) or len(members) > 3000 or sum(e.file_size for e in bundle.infolist()) > 600 * 1024**2:
        raise ValueError("Unexpected ZIP index or size")
    if bundle.testzip():
        raise ValueError("Invalid ZIP CRC")
    def lines(name):
        return [json.loads(line) for line in metadata(bundle, name) if line.strip()]
    def document(name):
        return json.loads("\n".join(metadata(bundle, name)))
    manifest = document("manifest.json")
    if (manifest["schema"], manifest["sample_rate"], manifest["channels"], manifest["bits"]) != (1, RATE, 1, 16):
        raise ValueError("Unsupported PCM")
    settings, summary, device = (document(k + ".json") for k in ("settings", "summary", "device"))
    records = lines("events.jsonl")
    ids = ("session_id", "id")
    events = keyed(records, ids)
    rec = keyed(lines("recognition.jsonl"), ids)
    markers = keyed(lines("voice_tests.jsonl"), ids)
    sessions = keyed(settings["sessions"], ["session_id"])
    if set(rec) != {key for key, e in events.items() if e["kind"] == "candidate"} or not markers.keys() <= events.keys():
        raise ValueError("Dangling or missing recognition/trial metadata")
    names = {e["audio"] for e in records}
    if len(names) != len(records) or names != {m[len(ROOT):] for m in members if m.startswith(ROOT+"audio/")}:
        raise ValueError("Expected one physical file per passive event")
    if (len(records), len(names)) != (summary["events"], summary["audio_files"]):
        raise ValueError("Summary counts disagree")
    routes, perf = lines("audio_route.jsonl"), lines("performance.jsonl")
    stops = keyed([row for row in perf if row.get("kind") == "session_stop"], ["session_id"])
    grouped = defaultdict(list)
    observed = defaultdict(list)
    cfg = {}
    fingerprints = Counter()
    for key, e in events.items():
        sid = (e["session_id"],)
        if sid not in sessions or e.get("audio_ref") or "source_start" not in e:
            raise ValueError("Timeline requires direct event clips with original capture offsets")
        if not (sessions[sid]["elapsed_ms"] <= e["elapsed_ms"] and
                (sid not in stops or e["elapsed_ms"] <= stops[sid]["elapsed_ms"])):
            raise ValueError("Event outside recorded session")
        if key in rec and rec[key]["utc"] != e["utc"]:
            raise ValueError("Recognition UTC mismatch")
        if key in markers and markers[key]["elapsed_ms"] != e["elapsed_ms"]:
            raise ValueError("Marker clock mismatch")
        start = e["source_start"]
        if start < 0 or e["capture_sample"] != start + e["pre_samples"] or e["samples"] != e["pre_samples"] + e["post_samples"]:
            raise ValueError("Invalid PCM geometry")
        pcm = decode(bundle, ffmpeg, e)
        fingerprints[hashlib.sha256(pcm).hexdigest()] += 1
        group = (key[0], e["capture_id"])
        grouped[group].append((start, pcm))
        grammar = (e["grammar"], e["preset"])
        if cfg.setdefault(group, grammar) != grammar:
            raise ValueError("Grammar changed within capture")
        observed[group].append(e)
    islands = []
    cpu, wall = Counter(), Counter()
    for group, chunks in sorted(grouped.items()):
        timeline = sorted(observed[group], key=lambda e: e["capture_sample"])
        dates = [datetime.fromisoformat(e["utc"].replace("Z", "+00:00")) for e in timeline]
        if dates != sorted(dates) or [e["elapsed_ms"] for e in timeline] != sorted(e["elapsed_ms"] for e in timeline):
            raise ValueError("Capture timeline reversed")
        for start, pcm in joined(chunks):
            stop = start + len(pcm)
            block = dict(session_id=group[0], capture_id=group[1], start=start, end=stop, models={})
            for name, detector in detectors.items():
                pc, wc = time.process_time(), time.perf_counter()
                result = detector(pcm, *cfg[group])
                cpu[name] += time.process_time() - pc
                wall[name] += time.perf_counter() - wc
                block["models"][name] = result
            islands.append(block)
    return dict(protocol="Positions in model output are relative to their island start. Reset at each gap, no padding at end.",
                manifest=manifest, device=device, settings=settings, archive_summary=summary,
                stops=list(stops.values()), routes=routes, markers=list(markers.values()),
                sessions_with_audio=len(grouped), events=records, recognition=list(rec.values()),
                islands=islands, cpu_seconds=cpu, wall_seconds=wall,
                source_samples=sum(e["samples"] for e in records), unique_samples=sum(b["end"]-b["start"] for b in islands),
                duplicate_pcm_files=sum(n-1 for n in fingerprints.values()))
