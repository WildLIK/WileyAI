"""Private framed pipe worker. Optional dependencies never enter the core process."""
import argparse
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(args.cache / "deps"), str(args.cache / "source")]
    protocol = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        import numpy as np
        import soundfile as sf
        import torch
        from openvoice.api import OpenVoiceBaseClass, ToneColorConverter
        torch.set_num_threads(4)
        converter = ToneColorConverter.__new__(ToneColorConverter)
        OpenVoiceBaseClass.__init__(converter, str(args.cache / "weights/config.json"), device="cpu")
        converter.watermark_model = None
        converter.version = "v2"
        checkpoint = torch.load(args.cache / "weights/checkpoint.pth", map_location="cpu", weights_only=True)
        converter.model.load_state_dict(checkpoint["model"], strict=True)
        del checkpoint
        target_key, target_embedding = None, None
        while line := sys.stdin.buffer.readline(48 * 1024**2 + 1):
            if len(line) > 48 * 1024**2:
                raise ValueError("oversized audio")
            payload = json.loads(line)
            reference = Path(payload["reference"])
            fingerprint = (str(reference), reference.stat().st_mtime_ns)
            if fingerprint != target_key:
                target_embedding = converter.extract_se([str(reference)])
                target_key = fingerprint
            with tempfile.TemporaryDirectory(prefix="wiley-openvoice-") as folder:
                source = Path(folder) / "source.wav"
                source.write_bytes(base64.b64decode(payload["audio"], validate=True))
                source_embedding = converter.extract_se([str(source)])
                audio = converter.convert(str(source), src_se=source_embedding, tgt_se=target_embedding, output_path=None)
            if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
                raise ValueError("invalid result")
            peak = float(np.abs(audio).max())
            if peak > .98:
                audio = audio * (.98 / peak)
            output = io.BytesIO()
            sf.write(output, audio, converter.hps.data.sampling_rate, format="WAV", subtype="PCM_16")
            result = output.getvalue()
            protocol.write(json.dumps({"size": len(result), "device": "cpu"}).encode() + b"\n" + result)
            protocol.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Dependency errors can contain file paths or request data. Keep the pipe
        # diagnostic bounded and independent of text/voice content.
        print("WILEY_ERROR:OpenVoice не смог преобразовать голос. Проверьте WAV-образец или переустановите преобразователь", file=sys.stderr)
        sys.exit(1)
