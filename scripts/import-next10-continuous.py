"""Convert only an explicitly selected NEXT 8 continuous recording to local WAV spans."""
import argparse
import csv
from datetime import datetime
from importlib import import_module
import json
from pathlib import Path
import tempfile
from uuid import UUID
import wave
from zipfile import ZipFile

replay=import_module('replay-wake-diagnostics')
validation=import_module('evaluate-next10-study')


def import_recording(archive,session,condition,ffmpeg):
    if str(UUID(session))!=session: raise ValueError('Expected session UUID')
    base=validation.WORK/'next10'
    plan=json.loads((base/'study-plan.json').read_text(encoding='utf8'))
    if condition not in plan['negative_conditions']: raise ValueError('Unknown planned condition')
    parent=base/'negative-import'
    parent.mkdir(exist_ok=True)
    dest=parent/session
    if dest.exists(): raise FileExistsError('Session already imported')
    with ZipFile(archive) as z:
        if len(z.namelist())!=len(set(z.namelist())): raise ValueError('Duplicate ZIP entry')
        entries=[json.loads(line) for line in replay.metadata(z,'events.jsonl')]
        continuous=[e for e in entries if e['session_id']==session and e['kind']=='continuous' and e.get('audio')]
        if len(continuous)!=1: raise ValueError('Expected one continuous recording; passive windows are ineligible')
        event=continuous[0]
        stamp=datetime.fromisoformat(event['utc'].replace('Z','+00:00'))
        started=int(stamp.timestamp()*1000)
        if started<=validation.FROZEN_MS or not event.get('spans'): raise ValueError('Missing provenance or old recording')
        pcm=replay.decode(z,str(ffmpeg),event)
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        folder=Path(tmp)/session
        folder.mkdir()
        rows=[]
        for span,(a,b) in zip(event['spans'],replay.segments(event,len(pcm))):
            file=folder/f'span-{len(rows)+1}.wav'
            with wave.open(str(file),'wb') as out:
                out.setparams((1,2,16000,0,'NONE','not compressed'))
                out.writeframes(pcm[a:b].tobytes())
            rows.append(dict(capture_id=span['capture_id'],file=str((dest/file.name).resolve()),
                source_start_sample=span['input_start'],split='test',condition=condition,consent='yes',no_intent='yes',started_at_ms=started))
        with (folder/'negative.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        folder.rename(dest)
    return dest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('--session',required=True);p.add_argument('--condition',required=True)
    p.add_argument('--ffmpeg',type=Path,required=True)
    p.add_argument('--consent-no-calls',action='store_true',required=True,help='All speakers agreed; no intended calls during this session')
    a=p.parse_args();print(import_recording(a.archive,a.session,a.condition,a.ffmpeg))

