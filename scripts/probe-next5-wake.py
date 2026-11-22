"""Retrospective PCM benchmark for NEXT 5. Run each detector in a separate process."""

import argparse
from collections import Counter, defaultdict
import csv
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

import numpy as np

RATE = 16000
HOP = 1280
WINDOW = 12800
CALIBRATION_SOURCES = {"Timbrica", "TTSMaker"}
PINNED = {
    "melspectrogram.tflite": "96fa0adccb6e8cf95cb14465409a1a2898ee4a96a85bb9ed3c7eb0e68bf163e8",
    "embedding_model.tflite": "c0aea21eb84a4ce90a08c870da41b7a7173b45269e6a3207c71d67c40f3a59d8",
}


def load_sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def memory():
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
            (name, ctypes.c_size_t) for name in ("peak", "rss", "a", "b", "c", "d", "page", "e")]

    data = Counters()
    data.size = ctypes.sizeof(data)
    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(data), data.size):
        return {"rss_mib": round(data.rss / 2**20, 1), "peak_mib": round(data.peak / 2**20, 1)}
    return None


def decode(args, entry):
    return subprocess.run([
        str(args.ffmpeg), "-nostdin", "-loglevel", "error", "-t", "30", "-i",
        str(args.corpus / "audios" / entry["audio_file"]), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1",
    ], capture_output=True, check=True, timeout=60).stdout


class Acoustic:
    def __init__(self, folder):
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        from tensorflow import lite

        def load(name, shape):
            path = folder / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != PINNED[name]:
                raise ValueError(f"Unexpected weights: {name}")
            model = lite.Interpreter(model_path=str(path), num_threads=1)
            index = model.get_input_details()[0]["index"]
            model.resize_tensor_input(index, shape)
            model.allocate_tensors()
            return model, index, model.get_output_details()[0]["index"]

        self.mel = load("melspectrogram.tflite", [1, WINDOW])
        self.embed = load("embedding_model.tflite", [1, 76, 32, 1])
        self.weights = None
        self.threshold = None

    @staticmethod
    def invoke(engine, samples):
        model, input_index, output_index = engine
        model.set_tensor(input_index, samples)
        model.invoke()
        return model.get_tensor(output_index)

    def features(self, pcm, pad=False):
        data = np.frombuffer(pcm, dtype="<i2")
        window = np.zeros(WINDOW, dtype=np.float32)
        for end in range(HOP, len(data) + (RATE if pad else 0) + 1, HOP):
            chunk = data[end - HOP:end]
            window[:-HOP] = window[HOP:]
            tail = window[-HOP:]
            tail.fill(0)
            tail[:len(chunk)] = chunk
            mel = self.invoke(self.mel, window[None, :])[0, 0, -76:, :]
            embedding = self.invoke(self.embed, (mel / 10 + 2)[None, :, :, None]).ravel()
            normalized = embedding / max(1e-8, np.linalg.norm(embedding))
            yield end / RATE, np.append(normalized, np.float32(1))

    def scores(self, pcm, pad=False):
        return ((end, float(vector @ self.weights)) for end, vector in self.features(pcm, pad))

    @staticmethod
    def events(scores, threshold):
        consecutive = 0
        next_allowed = 0.0
        for seconds, score in scores:
            consecutive = consecutive + 1 if score >= threshold else 0
            if consecutive == 2 and seconds >= next_allowed:
                yield seconds
                next_allowed = seconds + 0.8

    def train(self, training, calibration, train_negative, validate_negative):
        positive, negative = [], []
        for entry, pcm in training:
            end = entry["end_energy_s"]
            start = entry["start_energy_s"]
            for seconds, vector in self.features(pcm, True):
                if end <= seconds <= end + 0.32:
                    positive.append(vector)
                elif seconds <= start + (end - start) * 0.55:
                    negative.append(vector)
        for pcm in train_negative:
            negative.extend(vector for index, (_, vector) in enumerate(self.features(pcm)) if index % 2 == 0)
        pos, neg = np.array(positive), np.array(negative)
        gram = pos.T @ pos / len(pos) + neg.T @ neg / len(neg)
        self.weights = np.linalg.solve(gram + np.eye(gram.shape[0]) * 0.02, pos.mean(axis=0) - neg.mean(axis=0))
        calibration_scores = [(entry, list(self.scores(pcm, True))) for entry, pcm in calibration]
        negative_scores = [list(self.scores(pcm)) for pcm in validate_negative]
        for entry, pcm in calibration:
            half = entry["start_energy_s"] + (entry["end_energy_s"] - entry["start_energy_s"]) * 0.55
            negative_scores.append(list(self.scores(pcm[:2 * round(half * RATE)], True)))

        diagnostics = []
        for threshold in np.linspace(-0.5, 1.5, 201):
            false = sum(len(list(self.events(values, threshold))) for values in negative_scores)
            found, early = Counter(), 0
            for row, values in calibration_scores:
                hit = next(self.events(values, threshold), None)
                if hit is not None:
                    early += hit < row["end_energy_s"]
                    if row["end_energy_s"] <= hit <= row["duration_s"] + 0.5:
                        found[row["declared_variant"]] += 1
            diagnostics.append((false + early, -min(found["Вайли"], found["Уайли"]), -sum(found.values()), float(threshold)))
        best = min(diagnostics)
        self.threshold = best[-1]
        return {"threshold": self.threshold, "false_or_early": best[0], "found_by_worst_variant": -best[1],
                "completed_positives": -best[2], "positive_windows": len(pos), "negative_windows": len(neg),
                "weights": self.weights.tolist(), "upstream_sha256": PINNED}

    def run(self, pcm, pad):
        return list(self.events(self.scores(pcm, pad), self.threshold))


class Vosk:
    def __init__(self, work):
        self.impl = load_sibling("probe-next4-vosk")
        self.impl.vosk.SetLogLevel(-1)
        self.model = self.impl.vosk.Model(str(work / "vosk-device-model"))
        self.grammar = read_json(work / "b10/vosk-audit-summary.json")["grammar"]
        self.allowed = set(self.grammar) - {"[unk]"}

    def run(self, pcm, pad):
        return [seconds for _, seconds, _ in self.impl.replay(self.model, self.grammar, self.allowed, pcm, pad=pad)]


def summary(delays):
    if not delays:
        return None
    return {"p50_ms": round(float(np.percentile(delays, 50)), 1), "p95_ms": round(float(np.percentile(delays, 95)), 1)}


def evaluate_study(args):
    import audit_wake_study as study

    work = args.work
    prior = study.owner_fingerprints(work / "owner-export-20261116-184820.zip")
    annotations = rows(args.reviewed)
    reviewed = {row["id"]: (row["wake_start_s"], row["wake_end_s"]) for row in annotations}
    if len(reviewed) != len(annotations):
        raise ValueError("Repeated reviewed ID")
    if args.detector == "acoustic":
        if not args.head or not args.head_sha or hashlib.sha256(args.head.read_bytes()).hexdigest() != args.head_sha:
            raise ValueError("Closed test requires the previously frozen head and its SHA-256")
        detector = Acoustic(work / "next5")
        head = read_json(args.head)
        detector.weights = np.array(head["weights"])
        detector.threshold = float(head["threshold"])
    else:
        detector = Vosk(work)
    report, inputs = study.inspect(args.study_archive, prior, reviewed)
    if any(row["split"] != "test" for row in inputs):
        raise ValueError("Send only the closed test exports to this evaluation")
    counts, lag = defaultdict(Counter), defaultdict(list)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    for row in inputs:
        with zipfile.ZipFile(row["archive"]) as bundle:
            pcm = study.read_audio(bundle, row["member"])
        if hashlib.sha256(pcm).hexdigest() != row["pcm_sha256"]:
            raise ValueError("Study export changed during evaluation")
        positive = row["kind"] == "positive"
        hits = detector.run(pcm, positive)
        group = [row["kind"]]
        if positive:
            group.append("Уайли" if "уайли" in row["phrase"].lower() else "Вайли")
            if "сколько времени" in row["phrase"].lower():
                group.append("wake_and_command")
            if args.owner_alias:
                group.append("owner" if row["speaker"] == args.owner_alias else "other_speaker")
        for key in group:
            current = counts[key]
            current["clips"] += 1
            current["seconds"] += len(pcm) / (2 * RATE)
            current["events"] += len(hits)
            current["clips_with_events"] += bool(hits)
            if positive:
                current["early"] += bool(hits and hits[0] < row["end"])
                current["completed"] += bool(hits and hits[0] >= row["end"])
                if hits and hits[0] >= row["end"]:
                    lag[key].append((hits[0] - row["end"]) * 1000)
    negative = counts["negative"]
    if negative["seconds"]:
        negative["events_per_hour"] = round(negative["events"] * 3600 / negative["seconds"], 2)
    write_new(args.output, {"audit": report, "detector": args.detector, "head_sha256": args.head_sha,
                            "memory": memory(), "cpu_s": time.process_time() - start_cpu,
                            "wall_s": time.perf_counter() - start_wall,
                            "groups": {key: {**value, "lag": summary(lag[key])} for key, value in counts.items()}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detector", choices=("vosk", "acoustic"))
    parser.add_argument("--work", type=Path, default=Path("local/wakeword26b"))
    parser.add_argument("--synthetic", type=Path, default=Path("WileyAI21Голос"))
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--study-archive", type=Path, action="append")
    parser.add_argument("--reviewed", type=Path)
    parser.add_argument("--head", type=Path)
    parser.add_argument("--head-sha")
    parser.add_argument("--owner-alias")
    args = parser.parse_args()
    if args.study_archive:
        if args.reviewed is None:
            parser.error("--study-archive requires --reviewed")
        evaluate_study(args)
        return
    if args.corpus is None or args.ffmpeg is None:
        parser.error("Historical evaluation requires --corpus and --ffmpeg")
    work = args.work
    import wave

    def read_pcm(source):
        with wave.open(source, "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
                raise ValueError("Unexpected PCM format")
            return wav.readframes(wav.getnframes())

    synthetic = [(row, read_pcm(str(args.synthetic / row["wav_path"])))
                 for row in read_json(work / "b11/synthetic-catalog.json")["records"]]
    cv = read_json(work / "b6/negative-manifest.json")
    cv_speakers = {split: {r["speaker_split_hash"] for r in cv[split]} for split in ("validation", "test")}
    if cv_speakers["validation"] & cv_speakers["test"]:
        raise ValueError("The negative corpus contains speaker overlap")
    train_cv = {s for i, s in enumerate(sorted(cv_speakers["validation"])) if i % 2 == 0}
    train_neg = [decode(args, row) for row in cv["validation"] if row["speaker_split_hash"] in train_cv]
    cal_neg = [decode(args, row) for row in cv["validation"] if row["speaker_split_hash"] not in train_cv]
    training_inputs = [pcm for _, pcm in synthetic] + train_neg + cal_neg
    if len({hashlib.sha256(pcm).digest() for pcm in training_inputs}) != len(training_inputs):
        raise ValueError("Duplicate PCM in development or validation")
    load_before = memory()
    started = time.perf_counter()
    if args.detector == "acoustic":
        detector = Acoustic(work / "next5")
        load_seconds = time.perf_counter() - started
        calibration = [(row, pcm) for row, pcm in synthetic if row["source"] in CALIBRATION_SOURCES]
        training = [(row, pcm) for row, pcm in synthetic if row["source"] not in CALIBRATION_SOURCES]
        head = detector.train(training, calibration, train_neg, cal_neg)
        head.update(training=len(training), calibration=len(calibration),
                    training_negative_seconds=sum(map(len, train_neg)) / (2 * RATE),
                    calibration_negative_seconds=sum(map(len, cal_neg)) / (2 * RATE))
        frozen = args.output.with_suffix(".head.json")
        write_new(frozen, head)
        lock = hashlib.sha256(frozen.read_bytes()).hexdigest()
        weights_size = sum((work / "next5" / file).stat().st_size for file in PINNED) + detector.weights.nbytes
    else:
        detector = Vosk(work)
        load_seconds = time.perf_counter() - started
        lock = None
        weights_size = sum(p.stat().st_size for p in (work / "vosk-device-model").rglob("*") if p.is_file())
    result = {"detector": args.detector, "head_sha256": lock, "weights_bytes": weights_size,
              "load_s": round(load_seconds, 3), "memory_before_load": load_before}
    metrics, delays = defaultdict(Counter), defaultdict(list)
    seen = defaultdict(list)
    cpu, wall = Counter(), Counter()

    def run(group, pcm, end=None, *, pad=False):
        t_cpu, t_wall = time.process_time(), time.perf_counter()
        hits = detector.run(pcm, pad)
        cpu[group] += time.process_time() - t_cpu
        wall[group] += time.perf_counter() - t_wall
        data = metrics[group]
        data["clips"] += 1
        data["seconds"] += len(pcm) / (2 * RATE)
        data["clips_with_events"] += bool(hits)
        data["events"] += len(hits)
        if end is not None:
            data["early"] += bool(hits and hits[0] < end)
            data["completed"] += bool(hits and hits[0] >= end)
            if hits and hits[0] >= end:
                delays[group].append((hits[0] - end) * 1000)

    def fingerprint(group, pcm):
        seen[hashlib.sha256(pcm).hexdigest()].append(group)

    for phase, clips in zip(("train_cv", "calibration_cv"), (train_neg, cal_neg)):
        for pcm in clips:
            fingerprint(phase, pcm)
    with zipfile.ZipFile(work / "owner-export-20261116-184820.zip") as archive:
        for row in rows(work / "owner-annotations-reviewed.csv"):
            if row["status"] != "confirmed":
                raise ValueError("Expected reviewed wake timing")
            pcm = read_pcm(io.BytesIO(archive.read(row["id"] + ".wav")))
            end, start = float(row["wake_end_s"]), float(row["wake_start_s"])
            fingerprint("owner", pcm)
            run("owner", pcm, end, pad=True)
            if "," in row["phrase"] and not row["phrase"].split(",")[0].startswith("Окей"):
                run("owner_wake_and_command", pcm, end, pad=True)
            run("owner_half_word", pcm[:2 * round((end + start) / 2 * RATE)], pad=True)
    for row, pcm in synthetic:
        split = "calibration" if row["source"] in CALIBRATION_SOURCES else "training"
        fingerprint("synthetic_" + split, pcm)
        run("synthetic_" + split + "_" + row["declared_variant"], pcm, row["end_energy_s"], pad=True)
    hard = defaultdict(list)
    audit = {row["event_id"]: row for row in read_json(work / "b10/vosk-final-events.json")}
    for label in rows(work / "b10/review-final.csv"):
        record = audit[label["event_id"]]
        if record["source"] != label["source"] or abs(record["time_s"] - float(label["time_s"])) > 0.001:
            raise ValueError("Mismatched reviewed event")
        if label["verdict"] == "false_detection":
            hard[record["source"]].append(record)
    for row in cv["test"]:
        pcm = decode(args, row)
        fingerprint("test_cv", pcm)
        run("negative", pcm)
        for fragment in hard.pop(row["audio_file"], []):
            start = max(0, round((fragment["word_start_s"] - 0.32) * RATE))
            stop = round((fragment["time_s"] + 0.16) * RATE)
            run("historical_hard_subset", pcm[2 * start:2 * stop], pad=True)
    if hard:
        raise ValueError("Reviewed subset is outside the evaluated corpus")
    result["dataset_audit"] = {
        "pcm_duplicates": [groups for groups in seen.values() if len(groups) > 1],
        "cv_speakers": {split: len(speakers) for split, speakers in cv_speakers.items()},
        "training_cv_speakers": len(train_cv), "calibration_cv_speakers": len(cv_speakers["validation"] - train_cv),
        "historical_hard_subset_overlaps_negative": True,
    }
    result["memory_after"] = memory()
    result["groups"] = {group: {**values, "seconds": round(values["seconds"], 3),
                                 "cpu_s": round(cpu[group], 3), "wall_s": round(wall[group], 3),
                                 "completed_lag": summary(delays[group])} for group, values in metrics.items()}
    data = result["groups"]["negative"]
    data.update(events_per_hour=round(data["events"] * 3600 / data["seconds"], 2),
                realtime_factor=round(wall["negative"] / data["seconds"], 4))
    write_new(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
