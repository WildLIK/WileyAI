import importlib
import io
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wake_diagnostic_timeline import joined, keyed
from wake_next6 import RATE

replay = importlib.import_module("replay-wake-diagnostics")
report = importlib.import_module("summarize-wake-timeline")


def test_contained_overlap_adjacency_and_gap():
    pcm = np.arange(20, dtype=np.int16)
    blocks = list(joined([(18, pcm[18:]), (3, pcm[3:6]), (0, pcm[:9]), (7, pcm[7:12]), (12, pcm[12:14])]))
    assert [start for start, _ in blocks] == [0, 18]
    np.testing.assert_array_equal(blocks[0][1], pcm[:14])


def test_conflicting_overlap_rejected():
    with pytest.raises(ValueError, match="overlap"):
        list(joined([(0, np.array([1, 2])), (1, np.array([3]))]))


def test_identity_is_session_scoped():
    rows = [dict(s="a", id=1), dict(s="b", id=1)]
    assert len(keyed(rows, ("s", "id"))) == 2
    with pytest.raises(ValueError, match="Duplicate"):
        keyed(rows + rows[:1], ("s", "id"))


def test_geometry_overrules_header_metadata():
    name = "audio/11111111-1111-1111-1111-111111111111_event.flac"
    streaminfo = ((8000 << 44) | (15 << 36) | 1).to_bytes(8, "big")
    data = b"fLaC\x80\x00\x00\x22" + bytes(10) + streaminfo + bytes(16)
    with ZipFile(io.BytesIO(), "w") as z:
        z.writestr(replay.ROOT+name, data)
        event = dict(audio=name, sha256=replay.sha(data), samples=1)
        with pytest.raises(ValueError, match="format"):
            replay.decode(z, "must-never-run", event)
        with pytest.raises(ValueError, match="checksum"):
            replay.decode(z, "must-never-run", dict(event, sha256="wrong"))


def test_association_uses_word_interval_and_capture_origin():
    words = [{"start":.1,"end":.4}]
    assert report.matching_words(words, RATE, 18000, 22000)
    assert not report.matching_words(words, RATE, 24000, 26000)


def test_overlapping_rows_reference_one_scored_hit():
    common = dict(session_id="s",capture_id="c",kind="candidate",source_start=0,samples=16000,
                  pre_samples=10000,post_samples=6000,elapsed_ms=5,utc="2026-11-20T01:00:00Z",
                  accepted=True,label=0,decision="exact_wake",capture_sample=10000)
    other = dict(common, id="near", accepted=False, source_start=3000,samples=12000)
    event = dict(common,id="primary")
    recognition = dict(session_id="s",id="primary",vosk_final={"result":[{"start":.1,"end":.3}]})
    model = dict(hits=[5120],scores=[(5120,.2)],threshold=.15)
    island = dict(session_id="s",capture_id="c",start=0,end=16000,models={"plix":model})
    rows,hits=report.correlate(dict(events=[event,other], islands=[island],recognition=[recognition],routes=[]),
                               {"no_intent_utc_dates":["2026-11-20"]})
    assert len(hits)==1 and hits[0]["associated_ids"]==["primary"] and hits[0]["date_no_intent"]
    assert all(r["plix_clip_hits"]==[5120] for r in rows)

