"""Local GigaAM v3 E2E RNN-T via ONNX; no Torch, account or runtime downloads."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import httpx


MODEL_ID = "gigaam-v3"
MODEL_NAME = "GigaAM v3 E2E RNN-T"
REVISION = "322c3b29492673eb7d0b434bfa9dfb8653e34d02"
VAD_REVISION = "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6"
# Reviewed, unquantized ONNX exports by the onnx-asr author. No remote Python code.
# path: (repo, revision, filename, bytes, sha256)
FILES = {
    "config.json": ("istupakov/gigaam-v3-onnx", REVISION, "config.json", 135, "0641fcf73f4af791c73f05083e38a658ff5dcbee3534a0c61396c10f4b97f0fe"),
    "v3_e2e_rnnt_encoder.onnx": ("istupakov/gigaam-v3-onnx", REVISION, "v3_e2e_rnnt_encoder.onnx", 885084534, "cd60b3764a832e8560ae6d3ad0b10adc1a42ffae412b9476f25620aae4f4a508"),
    "v3_e2e_rnnt_decoder.onnx": ("istupakov/gigaam-v3-onnx", REVISION, "v3_e2e_rnnt_decoder.onnx", 4599910, "7b0a16d67fd2cb37061decc93c69e364a9ab27afee3c57495d55b1c974cf7231"),
    "v3_e2e_rnnt_joint.onnx": ("istupakov/gigaam-v3-onnx", REVISION, "v3_e2e_rnnt_joint.onnx", 2712896, "602ff7017a93311aad34df1437c8d7f49911353c13d6eae7a6ee7b041339465c"),
    "v3_e2e_rnnt_vocab.txt": ("istupakov/gigaam-v3-onnx", REVISION, "v3_e2e_rnnt_vocab.txt", 13354, "39abae20e692998290c574e606f11a9edef2902a1995463fcff63d1490cf22b7"),
    "vad/config.json": ("istupakov/silero-vad-onnx", VAD_REVISION, "config.json", 30, "1094039d370c82889582ba739a3d1caac5754c8b3a17a66a534200c9f72086e2"),
    "vad/silero_vad.onnx": ("istupakov/silero-vad-onnx", VAD_REVISION, "silero_vad.onnx", 2327524, "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"),
}
MAX_SAMPLES = 16000 * 300


def folder(root):
    return Path(root) / "models/gigaam/v3-e2e-rnnt"


def available():
    return all(importlib.util.find_spec(module) is not None for module in ("onnx_asr", "onnxruntime", "av"))


def installed(root):
    base = folder(root)
    try:
        marker = json.loads((base / "ready.json").read_text(encoding="utf-8"))
        return (marker == {"model": REVISION, "vad": VAD_REVISION}
                and all((base / path).is_file() and (base / path).stat().st_size == entry[3]
                        for path, entry in FILES.items()))
    except (OSError, ValueError):
        return False


def download(root, *, transport=None):
    """Resume verified files, publish readiness only after the entire set succeeds.

    The caller serializes downloads. A failed attempt leaves the old selection
    and verified files intact; partial files never count as installed.
    """
    base = folder(root)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(180, connect=30), follow_redirects=True) as client:
        for path, (repo, revision, name, size, digest) in FILES.items():
            target = base / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and target.stat().st_size == size:
                with target.open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() == digest:
                        continue
            partial = target.with_suffix(target.suffix + ".part")
            try:
                received, checksum = 0, hashlib.sha256()
                with client.stream("GET", f"https://huggingface.co/{repo}/resolve/{revision}/{name}") as response:
                    response.raise_for_status()
                    with partial.open("wb") as output:
                        for block in response.iter_bytes(1024 * 1024):
                            received += len(block)
                            if received > size:
                                raise ValueError("Файл GigaAM превышает ожидаемый размер. Повторите загрузку.")
                            checksum.update(block)
                            output.write(block)
                if received != size or checksum.hexdigest() != digest:
                    raise ValueError("Контрольная сумма GigaAM не совпала. Повторите загрузку.")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
    marker = base / "ready.part"
    marker.write_text(json.dumps({"model": REVISION, "vad": VAD_REVISION}), encoding="utf-8")
    marker.replace(base / "ready.json")


def decode_audio(data):
    """Decode Chromium WebM/Opus or a WAV upload in memory, with bounded duration."""
    import av
    import numpy as np
    chunks, count = [], 0

    def append(frames):
        nonlocal count
        for frame in frames:
            samples = frame.to_ndarray().reshape(-1)
            count += len(samples)
            if count > MAX_SAMPLES:
                raise ValueError("Для GigaAM разделите запись на части до пяти минут.")
            chunks.append(samples)

    try:
        with av.open(io.BytesIO(data)) as source:
            if not source.streams.audio:
                raise ValueError("В записи нет звуковой дорожки.")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
            for frame in source.decode(audio=0):
                append(resampler.resample(frame))
            append(resampler.resample(None))
    except (av.error.FFmpegError, EOFError) as error:
        raise ValueError("Не удалось прочитать запись. Повторите запись микрофона.") from error
    return np.concatenate(chunks).astype(np.float32, copy=False) if chunks else np.empty(0, dtype=np.float32)


class GigaAM:
    def __init__(self, root):
        if not available():
            raise ValueError("Установите компонент GigaAM ONNX в разделе «Модели → Компоненты» и перезапустите WileyAI.")
        if not installed(root):
            raise ValueError("Сначала скачайте GigaAM v3 в разделе «Модели → Распознавание голоса».")
        import onnx_asr
        import onnxruntime as rt
        import psutil
        options = rt.SessionOptions()
        options.intra_op_num_threads = min(8, psutil.cpu_count(logical=False) or 4)
        options.inter_op_num_threads = 1
        kwargs = {"providers": ["CPUExecutionProvider"], "sess_options": options}
        # Existing local directories force offline resolution. No Hub account,
        # torch import, code downloads or network calls during preparation/inference.
        self.model = onnx_asr.load_model("gigaam-v3-e2e-rnnt", folder(root), **kwargs)
        self.vad = onnx_asr.load_vad("silero", folder(root) / "vad", **kwargs)

    def transcribe(self, data, audio=None, environment="normal"):
        import numpy as np
        audio = decode_audio(data) if audio is None else audio
        if len(audio) > MAX_SAMPLES:
            raise ValueError("Для GigaAM разделите запись на части до пяти минут.")
        if not len(audio):
            return ""
        if not np.isfinite(audio).all():
            raise ValueError("В записи повреждённые звуковые данные.")
        # VAD removes silence and splits continuous speech below the model's
        # 25-second limit, including manual recordings and 120-second turns.
        segments = self.model.with_vad(
            self.vad, batch_size=1, threshold=0.65 if environment == "music" else 0.5,
            min_speech_duration_ms=200, min_silence_duration_ms=300,
            speech_pad_ms=250, max_speech_duration_s=20,
        ).recognize(audio, sample_rate=16000)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())
