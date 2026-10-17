"""Optional local experiment: Piper/Silero -> OpenVoice V2, outside the app runtime.

Run with the project's .venv Python. --prepare installs extra libraries under
local/ and downloads pinned code/checkpoints; it does not change that venv.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import wave
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
CACHE = PROJECT / "local/openvoice-probe"
SOURCE_REV = "74a1d147b17a8c3092dd5430504bd83ef6c7eb23"
MODEL_REV = "f36e7edfe1684461a8343844af60babc2efbb727"
FILES = {
    "config.json": (838, "9dfff60350b8c63f2c664efd92a61b2516efb22671466960f0e5dfebd881fa47"),
    "checkpoint.pth": (131320490, "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e"),
}
DEPENDENCIES = ["librosa==0.10.2.post1", "soundfile==0.13.1", "inflect==7.5.0", "unidecode==1.3.8",
                "eng_to_ipa==0.0.2", "cn2an==0.5.23", "jieba==0.42.1", "pypinyin==0.53.0"]
sys.path.insert(0, str(PROJECT))


def prepare():
    import httpx
    subprocess.run(["uv", "pip", "install", "--python", sys.executable, "--target", str(CACHE / "deps"), *DEPENDENCIES], check=True)
    source = CACHE / "source"
    response = httpx.get(f"https://codeload.github.com/myshell-ai/OpenVoice/zip/{SOURCE_REV}", timeout=120)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            relative = "/".join(name.split("/")[1:])
            if not ((relative.startswith("openvoice/") and relative.endswith(".py")) or relative == "LICENSE"):
                continue
            target = (source / relative).resolve()
            if not target.is_relative_to(source.resolve()):
                raise ValueError("Invalid source archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    for name, (size, digest) in FILES.items():
        target = CACHE / "weights" / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", f"https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/{MODEL_REV}/converter/{name}", follow_redirects=True, timeout=180) as response:
            response.raise_for_status()
            received = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > size:
                        raise ValueError("Checkpoint exceeds expected size")
                    output.write(chunk)
        if received != size or hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise ValueError("Checkpoint verification failed")
        temporary.replace(target)


def baseline(args):
    import torch
    from core.voice import Voice
    torch.set_num_threads(4)
    voice = Voice(args.data_dir)
    results = {}
    for name, engine, speaker in [("piper", "piper", "irina"), ("silero", "silero_v5_6", "xenia")]:
        began = time.perf_counter()
        voice.synthesize(args.text, speaker, engine=engine)
        cold = time.perf_counter() - began
        began = time.perf_counter()
        audio = voice.synthesize(args.text, speaker, engine=engine)
        warm = time.perf_counter() - began
        target = args.output / f"{name}-original.wav"
        target.write_bytes(audio)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
        results[name] = {"engine": engine, "speaker": speaker, "cold_tts_seconds": round(cold, 3),
                         "warm_tts_seconds": round(warm, 3), "audio_seconds": round(seconds, 3)}
        print(name, results[name], flush=True)
    (args.output / "baseline.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def convert(args):
    for name, (size, digest) in FILES.items():
        target = CACHE / "weights" / name
        if not target.is_file() or target.stat().st_size != size or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Prepare the verified converter with --prepare first")
    # The baseline process uses the existing TTS environment; extra experiment
    # dependencies only enter this process, never the app or the original venv.
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--baseline-only", "--data-dir", str(args.data_dir),
                    "--output", str(args.output), "--text", args.text], check=True, cwd=PROJECT)
    sys.path[:0] = [str(CACHE / "deps"), str(CACHE / "source")]
    began = time.perf_counter()
    import numpy as np
    import psutil
    import soundfile as sf
    import torch
    from openvoice.api import OpenVoiceBaseClass, ToneColorConverter
    torch.set_num_threads(4)
    # Initialize only the tone converter. The upstream convenience constructor
    # otherwise downloads a separate watermark model, unnecessary for this probe.
    converter = ToneColorConverter.__new__(ToneColorConverter)
    OpenVoiceBaseClass.__init__(converter, str(CACHE / "weights/config.json"), device="cpu")
    converter.watermark_model = None
    converter.version = "v2"
    checkpoint = torch.load(CACHE / "weights/checkpoint.pth", map_location="cpu", weights_only=True)
    converter.model.load_state_dict(checkpoint["model"], strict=True)
    del checkpoint
    loaded = time.perf_counter() - began
    began = time.perf_counter()
    reference = converter.extract_se([str(args.reference)])
    reference_time = time.perf_counter() - began
    result = {"source_revision": SOURCE_REV, "model_revision": MODEL_REV, "device": "cpu", "text": args.text,
              "reference": str(args.reference), "load_seconds": round(loaded, 3),
              "reference_seconds": round(reference_time, 3), "samples": {}}
    base = json.loads((args.output / "baseline.json").read_text(encoding="utf-8"))
    for name in base:
        source = args.output / f"{name}-original.wav"
        began = time.perf_counter()
        embedding = converter.extract_se([str(source)])
        embedding_time = time.perf_counter() - began
        began = time.perf_counter()
        audio = converter.convert(str(source), src_se=embedding, tgt_se=reference, output_path=None)
        conversion_time = time.perf_counter() - began
        if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
            raise ValueError("Converter returned invalid audio")
        peak = float(np.abs(audio).max())
        if peak > 0.98:
            audio = audio * (0.98 / peak)
        target = args.output / f"{name}-mita.wav"
        sf.write(target, audio, converter.hps.data.sampling_rate, subtype="PCM_16")
        result["samples"][name] = {**base[name], "speaker_extraction_seconds": round(embedding_time, 3),
                                   "conversion_seconds": round(conversion_time, 3), "file": str(target)}
        print(name, result["samples"][name], flush=True)
    memory = psutil.Process().memory_info()
    result["process_peak_ram_mib"] = round(getattr(memory, "peak_wset", memory.rss) / 1024**2, 1)
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Install the optional converter without generating audio")
    parser.add_argument("--baseline-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reference", type=Path, default=PROJECT / "local/voice-samples/fish-mita.mp3")
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    parser.add_argument("--output", type=Path, default=PROJECT / "local/voice-conversion")
    parser.add_argument("--text", default="Привет! Я Уайли. Давай спокойно обсудим твои планы.")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.data_dir = args.data_dir.resolve()
    args.reference = args.reference.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.prepare or args.prepare_only:
        prepare()
    if args.prepare_only:
        return
    if args.baseline_only:
        baseline(args)
    else:
        if not args.reference.is_file() or not (CACHE / "deps/librosa").is_dir():
            parser.error("A reference recording and --prepare are required")
        convert(args)


if __name__ == "__main__":
    main()
