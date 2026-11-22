"""Local PLiX TinyNet-E weight loading and ONNX parity checks."""

import argparse
import hashlib
import io
import json
import wave
import zipfile
from pathlib import Path

import numpy as np
from scipy.fft import rfft

from wake_next6 import RATE, unit

REVISION = '80e18934275fc14ced9cde742949c00c5928be26'
MODELS = {
    'ru': '3a89d0223e2b07f1b6346eb071f155a9d4748fcb5a453d61b766ff7eeda584c7',
    'multi': 'abded0108beef3494f7c88a6242cd78a6766b72d3744968f79c434210bdc39e2',
}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logmel(pcm, window, filters):
    data = np.asarray(pcm, dtype=np.float32) / 32768
    if data.shape != (RATE,):
        raise ValueError('PLiX requires exactly one second of PCM')
    reflected = np.pad(data, 512, mode='reflect')
    frames = np.lib.stride_tricks.sliding_window_view(reflected, 1024)[::160]
    spectrum = rfft(frames * window)
    power = spectrum.real ** 2 + spectrum.imag ** 2
    return np.log(power @ filters + np.float32(1e-6)).T[None, None, :, :].copy()


def build_onnx(folder, language, output):
    import onnx
    import timm
    import torch
    from torch import nn

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    path = folder / f'small_{language}_model.pt'
    if file_hash(path) != MODELS[language]:
        raise ValueError('Wrong PLiX checkpoint SHA-256')
    state = torch.load(path, map_location='cpu', weights_only=True)
    window = state.pop('backbone.melspec.spectrogram.window')
    filters = state.pop('backbone.melspec.mel_scale.fb')
    network = timm.create_model('tinynet_e', pretrained=False, in_chans=1, num_classes=0, global_pool='').eval()
    prefix = 'backbone.encoder.'
    if any(not key.startswith(prefix) for key in state):
        raise ValueError('Unknown PLiX weight key')
    network.load_state_dict({key[len(prefix):]: value for key, value in state.items()}, strict=True)

    class Pool(nn.Module):
        def __init__(self, encoder):
            super().__init__()
            self.encoder = encoder

        def forward(self, features):
            return self.encoder(features).mean(dim=(2, 3))

    model = Pool(network).eval()
    target = output / f'{language}.onnx'
    if target.exists() or (output / f'{language}-frontend.npz').exists():
        raise FileExistsError('Use a new output directory')
    hann = np.pad(window.numpy(), (312, 312))
    filterbank = filters.numpy()
    np.savez(output / f'{language}-frontend.npz', hann=hann, filters=filterbank)
    example = torch.zeros((1, 1, 64, 101), dtype=torch.float32)
    with torch.inference_mode():
        torch.onnx.export(model, example, target, input_names=['logmel'], output_names=['embedding'],
                          opset_version=17, dynamo=False)
    graph = onnx.load(target, load_external_data=False)
    onnx.checker.check_model(graph)
    return model, window, filters


class PLiX:
    def __init__(self, folder: Path, language):
        import onnxruntime as ort

        onnx_file = folder / f'{language}.onnx'
        feature_file = folder / f'{language}-frontend.npz'
        with np.load(feature_file, allow_pickle=False) as features:
            self.hann, self.filters = features['hann'], features['filters']
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.runtime = ort.InferenceSession(str(onnx_file), sess_options=opts, providers=['CPUExecutionProvider'])
        self.asset_bytes = onnx_file.stat().st_size + feature_file.stat().st_size

    def raw_embedding(self, pcm):
        feature = logmel(pcm, self.hann, self.filters)
        return self.runtime.run(['embedding'], {'logmel': feature})[0]

    def __call__(self, pcm):
        return unit(self.raw_embedding(pcm))[0]


def verify_parity(model, window, filters, runtime, examples):
    import torch

    feature_error = 0.0
    output_error = 0.0
    min_cosine = 1.0
    with torch.inference_mode():
        for pcm in examples:
            src = torch.from_numpy(np.asarray(pcm).astype(np.float32) / 32768)
            power = torch.stft(src, 1024, hop_length=160, win_length=400, window=window, return_complex=True).abs() ** 2
            features = torch.log(power.T @ filters + 1e-6).T[None, None, :, :]
            expected = model(features).numpy()
            actual = runtime.raw_embedding(pcm)
            frontend = logmel(pcm, runtime.hann, runtime.filters)
            feature_error = max(feature_error, float(np.max(np.abs(features.numpy() - frontend))))
            output_error = max(output_error, float(np.max(np.abs(actual - expected))))
            min_cosine = min(min_cosine, float(np.sum(unit(actual) * unit(expected))))
    if not np.isfinite(output_error) or output_error > 0.015 or min_cosine < 0.999:
        raise ValueError('ONNX and PyTorch parity failed')
    return {'logmel_max_abs_error': feature_error, 'embedding_max_abs_error': output_error, 'min_cosine': min_cosine}


def export(args):
    from wake_next6 import AudioWindows

    # Parity examples come from registration only. Evaluation files are untouched here.
    source = args.work / 'owner-export-20261116-184820.zip'
    splits = json.loads((args.work / 'b6/owner-splits.json').read_text(encoding='utf-8-sig'))
    examples = [np.zeros(RATE, dtype=np.int16)]
    with zipfile.ZipFile(source) as bundle:
        for key in splits['train'][:3]:
            with wave.open(io.BytesIO(bundle.read(key + '.wav')), 'rb') as wav:
                pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
            examples.extend(window for end, window in AudioWindows().feed(pcm) if end in (RATE * 8 // 10, RATE * 16 // 10))
    model, window, filters = build_onnx(args.work / 'next6', args.language, args.exports)
    runtime = PLiX(args.exports, args.language)
    parity = verify_parity(model, window, filters, runtime, examples)
    files = (f'{args.language}.onnx', f'{args.language}-frontend.npz')
    report = {'revision': REVISION, 'checkpoint_sha256': MODELS[args.language], 'parity_examples': len(examples),
              'parameters': sum(p.numel() for p in model.parameters()), 'asset_bytes': runtime.asset_bytes,
              'assets_sha256': {name: file_hash(args.exports / name) for name in files}, **parity}
    with (args.exports / f'{args.language}-export.json').open('x', encoding='utf8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('language', choices=MODELS)
    parser.add_argument('--work', default=Path('local/wakeword26b'), type=Path)
    parser.add_argument('--exports', required=True, type=Path)
    options = parser.parse_args()
    options.exports.mkdir(parents=True, exist_ok=True)
    export(options)
