"""Review local ASR hypotheses near negative detections. No raw audio is written."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import sherpa_onnx

from audit_wake_study import read_audio


def check(archive, results):
    root=Path('local/wakeword26b/gigaam-device-model')
    model=sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(root/'encoder.int8.onnx'),decoder=str(root/'decoder.onnx'),joiner=str(root/'joiner.onnx'),
        tokens=str(root/'tokens.txt'),num_threads=2,sample_rate=16000,feature_dim=64,model_type='nemo_transducer')
    with ZipFile(archive) as bundle:
        for sample in results['samples']:
            row=sample['row']
            if row['kind']!='negative':
                continue
            pcm=np.frombuffer(read_audio(bundle,row['id']+'.wav'),dtype='<i2')
            times={}
            for method, output in sample['detectors'].items():
                for at in output['hits']:
                    times.setdefault(at,[]).append(method)
            # For long ASR streams, also decode contiguous 12s blocks.
            parts=[]
            if not row['gigaam'] and len(pcm)>192000:
                for start in range(0,len(pcm),192000):
                    st=model.create_stream()
                    st.accept_waveform(16000,pcm[start:start+192000].astype(np.float32)/32768)
                    model.decode_stream(st)
                    parts.append(dict(start_s=start/16000, text=st.result.text))
            events=[]
            for at, detected in sorted(times.items()):
                left=max(0,at-32000)
                right=min(len(pcm),at+4000)
                st=model.create_stream()
                st.accept_waveform(16000,pcm[left:right].astype(np.float32)/32768)
                model.decode_stream(st)
                events.append(dict(detectors=detected,start_s=left/16000,end_s=right/16000,
                                   decision_s=at/16000,gigaam=st.result.text))
            yield dict(id=row['id'],gigaam=row['gigaam'],long_clip_parts=parts,events=events)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','replay','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.replay.read_text(encoding='utf8'))
    rows=list(check(args.archive,data))
    with args.output.open('x',encoding='utf8') as file: json.dump(rows,file,ensure_ascii=False,indent=2)

