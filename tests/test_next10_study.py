import importlib
import csv
import json
import sys
import wave
from zipfile import ZipFile
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
study = importlib.import_module('evaluate-next10-study')


def test_continuous_negatives_must_be_consented_and_disjoint(tmp_path):
    path = tmp_path/'test.wav'
    with wave.open(str(path),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'))
        f.writeframes(bytes(32000))
    row=dict(file=str(path),source_start_sample='0',split='test',capture_id='one',consent='yes',no_intent='yes',started_at_ms=study.FROZEN_MS+1)
    seen=set()
    spans=defaultdict(list)
    assert len(study.negative_wav(row,seen,spans))==32000
    for changed, error in [({'source_start_sample':'100'},'overlapping'),({'capture_id':'two'},'Duplicate'),
                           ({'consent':'no'},'consent'),({'split':'validation'},'provenance'),({'started_at_ms':'0'},'predates')]:
        with pytest.raises(ValueError,match=error):
            study.negative_wav(dict(row,**changed),seen,spans)


def test_import_continuous_uses_capture_ranges_and_cannot_import_passive(tmp_path,monkeypatch):
    importer=importlib.import_module('import-next10-continuous')
    folder=tmp_path/'next10'
    folder.mkdir()
    (folder/'study-plan.json').write_text('{"negative_conditions":["room"]}')
    monkeypatch.setattr(study,'WORK',tmp_path)
    monkeypatch.setattr(importer.replay,'decode',lambda *args: study.np.zeros(32000,dtype='<i2'))
    session='00000000-0000-4000-8000-000000000001'
    entry={'session_id':session,'kind':'continuous','audio':'a','utc':'2026-11-25T10:00:00Z',
           'spans':[{'file_start':0,'input_start':123,'capture_id':'mic1'},
                    {'file_start':16000,'input_start':42000,'capture_id':'mic1'}]}
    archive=tmp_path/'fixture.zip'
    def store(row):
        with ZipFile(archive,'w') as z:
            z.writestr(importer.replay.ROOT+'events.jsonl',json.dumps(row))
    store(dict(entry,kind='candidate'))
    with pytest.raises(ValueError,match='continuous'): importer.import_recording(archive,session,'room','unused')
    store(entry)
    dest=importer.import_recording(archive,session,'room','unused')
    with (dest/'negative.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    assert [r['source_start_sample'] for r in rows]==['123','42000']
    assert all(Path(r['file']).exists() for r in rows)
    with pytest.raises(FileExistsError): importer.import_recording(archive,session,'room','unused')

