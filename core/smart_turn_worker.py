"""Optional, isolated CPU inference. No network access and no microphone."""
import base64
import json
import sys


def features(audio):
    import numpy as np
    # Smart Turn: last 8 seconds, left padding, waveform normalization, then
    # Whisper's 80-band Slaney log-Mel (400 FFT, 160 hop, periodic Hann).
    audio = np.asarray(audio[-128000:], dtype=np.float32)
    audio = np.pad(audio, (128000 - len(audio), 0))
    audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
    padded = np.pad(audio, (200, 200), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, 400)[::160]
    spectrum = np.fft.rfft(frames * np.hanning(401)[:-1], axis=-1)
    power = (np.abs(spectrum[:-1]) ** 2).T
    mels = np.linspace(0, 45.245640471924965, 82)
    hz = 200 / 3 * mels
    mask = mels >= 15
    hz[mask] = 1000 * np.exp(np.log(6.4) / 27 * (mels[mask] - 15))
    bins = np.fft.rfftfreq(400, 1 / 16000)
    ramps = hz[:, None] - bins[None, :]
    delta = np.diff(hz)
    filters = np.maximum(0, np.minimum(-ramps[:-2] / delta[:-1, None], ramps[2:] / delta[1:, None]))
    filters *= (2 / (hz[2:] - hz[:-2]))[:, None]
    log = np.log10(np.maximum(filters @ power, 1e-10))
    return ((np.maximum(log, log.max() - 8) + 4) / 4)[None].astype(np.float32)


def main():
    import numpy as np
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    session = ort.InferenceSession(sys.argv[1], sess_options=options, providers=["CPUExecutionProvider"])
    print('{"ready":true}', flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            pcm = base64.b64decode(request["pcm"], validate=True)
            if len(pcm) > 256000 or len(pcm) % 2: raise ValueError("Invalid PCM")
            audio = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
            result = float(session.run(None, {"input_features": features(audio)})[0].reshape(-1)[0])
            print(json.dumps({"score": result}), flush=True)
        except Exception:
            print('{"error":"Smart Turn inference failed"}', flush=True)


if __name__ == "__main__":
    main()
