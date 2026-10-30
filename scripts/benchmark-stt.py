"""Offline STT comparison; a user-supplied manifest is read, audio is never recorded.

Manifest: [{"audio": "relative.wav", "reference": "Открой OBS", "expected_target": "OBS", "category": "real"}].
It never executes actions; expected_target is empty for speech that must not be an opening command.
"""
import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from core.intent_interpreter import interpret
from core.voice import Voice


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = row
    return previous[-1]


def clean(text):
    return " ".join(re.findall(r"[\w]+", text.casefold().replace("ё", "е")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--engines", nargs="+", default=["small", "gigaam-v3"])
    parser.add_argument("--vocabulary", nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not 1 <= len(samples) <= 500:
        raise ValueError("Manifest must contain 1–500 samples")
    process = psutil.Process()
    report = {"method": "audio files supplied by owner; no action is dispatched", "engines": {}}
    for engine in args.engines:
        voice = Voice(args.root)
        result = {"available": voice.available(engine), "installed": voice.stt_installed(engine), "samples": []}
        report["engines"][engine] = result
        if not result["available"] or not result["installed"]:
            continue
        result["baseline_rss_bytes"] = process.memory_info().rss
        for sample in samples:
            path = (args.manifest.parent / sample["audio"]).resolve()
            audio = path.read_bytes()
            if len(audio) > 10 * 1024 * 1024:
                raise ValueError("Audio exceeds 10 MiB")
            stop = threading.Event()
            peak = [process.memory_info().rss]
            def sample_rss():
                while not stop.wait(.05):
                    peak[0] = max(peak[0], process.memory_info().rss)
            thread = threading.Thread(target=sample_rss, daemon=True); thread.start()
            started = time.perf_counter(); cpu = process.cpu_times()
            try:
                text = voice.transcribe(audio, engine, "Уайли", vocabulary=args.vocabulary)
                intent = interpret(text)
                elapsed = time.perf_counter() - started
                cpu_after = process.cpu_times()
            finally:
                stop.set(); thread.join()
            reference = clean(sample.get("reference", "")); actual = clean(text)
            expected = clean(sample.get("expected_target", ""))
            target = clean(intent.target) if intent and intent.device == "computer" else ""
            result["samples"].append({"audio": sample["audio"], "category": sample.get("category", "unspecified"), "reference": sample.get("reference", ""), "recognized": text,
                "word_errors": distance(reference.split(), actual.split()), "reference_words": len(reference.split()), "char_errors": distance(reference, actual), "reference_chars": len(reference),
                "target": target, "expected_target": expected, "correct_intent": target == expected, "false_action_candidate": bool(target and not expected),
                "seconds": round(elapsed, 3), "process_cpu_seconds": round(cpu_after.user + cpu_after.system - cpu.user - cpu.system, 3), "peak_rss_bytes": peak[0]})
        rows = result["samples"]
        words = sum(row["reference_words"] for row in rows); chars = sum(row["reference_chars"] for row in rows)
        result["wer"] = sum(row["word_errors"] for row in rows) / words if words else None
        result["cer"] = sum(row["char_errors"] for row in rows) / chars if chars else None
        result["intent_accuracy"] = sum(row["correct_intent"] for row in rows) / len(rows)
        result["false_action_candidates"] = sum(row["false_action_candidate"] for row in rows)
        result["idle_rss_bytes"] = process.memory_info().rss
        idle_before = process.cpu_times()
        time.sleep(.25)
        idle_after = process.cpu_times()
        result["idle_sample_seconds"] = .25
        result["idle_process_cpu_seconds"] = round(idle_after.user + idle_after.system - idle_before.user - idle_before.system, 3)
        import asyncio
        asyncio.run(voice.unload())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
