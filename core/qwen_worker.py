"""One utterance per isolated process; killing it also releases model/GPU memory."""
import argparse
from contextlib import redirect_stdout
import io
import json
import sys
import wave

from .speech_text import plain_speech, speech_chunks


def select_device(torch, device):
    if device == "cpu":
        return "cpu"
    automatic = device == "auto"
    try:
        if not torch.cuda.is_available():
            if automatic:
                return "cpu"
            raise ValueError("CUDA недоступна. Выберите CPU в настройках Qwen3-TTS")
        free, _ = torch.cuda.mem_get_info()
    except RuntimeError as error:
        if automatic:
            return "cpu"
        raise ValueError("Не удалось подготовить CUDA. Выберите CPU в настройках Qwen3-TTS") from error
    if free < 3500 * 1024 * 1024:
        if automatic:
            return "cpu"
        raise ValueError("Для Qwen3-TTS нужно хотя бы 3,5 ГБ свободной видеопамяти. Освободите её или выберите CPU")
    return "cuda"


def load_model(model_path, device):
    import torch
    from qwen_tts import Qwen3TTSModel
    torch.set_num_threads(4)
    device = select_device(torch, device)
    print("WILEY_DEVICE:" + device, file=sys.stderr, flush=True)
    model = Qwen3TTSModel.from_pretrained(
        model_path, device_map=device, dtype=torch.bfloat16,
        attn_implementation="sdpa", local_files_only=True, use_safetensors=True,
    )
    return model, device


def generate(model_path, device, payload, runtime=None):
    import torch
    import numpy as np
    model, _ = runtime or load_model(model_path, device)
    parts = []
    rate = 24000
    with torch.inference_mode():
        for text in speech_chunks(plain_speech(payload["text"])):
            wavs, rate = model.generate_custom_voice(text=text, language="Russian", speaker=payload["speaker"],
                                                    do_sample=False, max_new_tokens=2048)
            audio = np.asarray(wavs[0], dtype=np.float32)
            if not audio.size or not np.isfinite(audio).all():
                raise ValueError("Модель вернула некорректный звук")
            peak = float(np.abs(audio).max()) if audio.size else 0
            audio = audio / max(1.0, peak / 0.95)
            parts.append((audio * 32767).astype("<i2").tobytes())
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(parts))
    return result.getvalue()


def describe_failure(error):
    message = str(error).lower()
    if isinstance(error, MemoryError) or getattr(error, "winerror", None) == 1455 or "1455" in message or "файл подкачки" in message:
        return "Windows не хватает памяти для Qwen3-TTS, включая файл подкачки. Освободите память и повторите озвучку"
    if "out of memory" in message:
        return "Недостаточно памяти для Qwen3-TTS. Освободите ресурсы или выберите другое устройство озвучки"
    return "Не удалось запустить Qwen3-TTS. Проверьте отдельное окружение и файлы модели"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--session", action="store_true")
    args = parser.parse_args()
    try:
        if args.session:
            runtime = None
            while line := sys.stdin.buffer.readline(100_000):
                payload = json.loads(line)
                with redirect_stdout(sys.stderr):
                    if runtime is None:
                        runtime = load_model(args.model, args.device)
                    audio = generate(args.model, args.device, payload, runtime)
                sys.stdout.buffer.write(json.dumps({"size": len(audio), "device": runtime[1]}).encode() + b"\n" + audio)
                sys.stdout.buffer.flush()
            return 0
        payload = json.loads(sys.stdin.buffer.read(100_000))
        # Dependency diagnostics must never corrupt the binary audio protocol.
        with redirect_stdout(sys.stderr):
            audio = generate(args.model, args.device, payload)
        sys.stdout.buffer.write(audio)
    except ValueError as error:
        print("WILEY_ERROR:" + str(error)[:300], file=sys.stderr)
        return 1
    except Exception as error:
        message = describe_failure(error)
        print("WILEY_ERROR:" + message, file=sys.stderr)
        print(type(error).__name__ + ": " + str(error)[:600], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
