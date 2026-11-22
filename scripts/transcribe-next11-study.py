"""Read vetted ZIP members for local GigaAM v3 inference with the existing speech venv."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import sherpa_onnx

from audit_wake_study import read_audio

root = Path('local/wakeword26b/gigaam-device-model')
recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=str(root/'encoder.int8.onnx'), decoder=str(root/'decoder.onnx'),
    joiner=str(root/'joiner.onnx'),tokens=str(root/'tokens.txt'),
    num_threads=2,sample_rate=16000,feature_dim=64,model_type='nemo_transducer')
archive, *members = sys.argv[1:]
out = {}
with ZipFile(archive) as bundle:
    for name in members:
        pcm = np.frombuffer(read_audio(bundle,name),dtype='<i2')
        stream = recognizer.create_stream()
        stream.accept_waveform(16000,pcm.astype(np.float32)/32768)
        recognizer.decode_stream(stream)
        result = stream.result
        out[name] = dict(giga=result.text,tokens=list(result.tokens),timestamps=list(result.timestamps))
print(json.dumps(out, ensure_ascii=True))

