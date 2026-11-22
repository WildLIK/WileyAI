import csv,io,importlib.util,wave,zipfile
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('wake_review',Path(__file__).resolve().parents[1]/'scripts/review_wake_annotations.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_wake_review_preserves_archive_and_saves_only_explicit_status(tmp_path):
    uid='12345678-1234-1234-1234-123456789abc'; b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(64000))
    z=tmp_path/'source.zip'
    with zipfile.ZipFile(z,'w') as archive:archive.writestr(uid+'.wav',b.getvalue())
    original=z.read_bytes();pcm,duration=m.read_wav(z,uid);assert duration==2
    with wave.open(io.BytesIO(m.clipped_wav(pcm,.25,.75))) as w:assert w.getnframes()==8000
    with pytest.raises(ValueError):m.clipped_wav(pcm,.8,2.1)
    with pytest.raises(ValueError):m.read_wav(z,'../bad')
    rows=[dict(id=uid,phrase='Вайли',wake_start_s='.25',wake_end_s='.75',status='confirmed'),dict(id='00000000-0000-0000-0000-000000000000',phrase='Вайли',wake_start_s='',wake_end_s='',status='manual_review')]
    result=tmp_path/'reviewed.csv';m.save_review(result,rows)
    with result.open(encoding='utf-8-sig',newline='') as f:saved=list(csv.DictReader(f))
    assert [x['status'] for x in saved]==['confirmed','manual_review'];assert z.read_bytes()==original
