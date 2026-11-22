"""Pin the bounded Vosk prefix recovery and sample geometry before any Android rollout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from wake_next12 import Candidate,StablePartial,confirm,parse


def w(word, start, end, conf=1):
    return {'word':word,'start':start,'end':end,'conf':conf}


def test_suffix_recovery_uses_name_boundary_not_vosk_suffix_end():
    words=[w('вай',.4,.65),w('ли',.65,.8),w('ли',1.,1.4,.6)]
    c=parse(words,32000,ambiguous=True)
    assert c and c.end==12800 and c.handoff==10880
    assert c.confidence==1 and c.suffix=='ли'


def test_recovery_does_not_accept_arbitrary_suffix_late_or_weak_prefix():
    prefix=[w('уайли',.45,.85)]
    assert parse(prefix+[w('поговорим',1.,1.5)],32000,ambiguous=True)
    assert parse(prefix+[w('это',1.,1.5)],32000,ambiguous=True) is None
    assert parse([w('вай',.45,.85),w('поговорим',1.,1.5)],32000,ambiguous=True) is None
    assert parse([w('уайли',.45,.85,.74),w('ли',1,1.3)],32000,ambiguous=True) is None
    assert parse(prefix+[w('ли',1.,1.5)],64000,ambiguous=True) is None


def test_plix_cannot_confirm_from_the_future_or_far_from_the_word():
    c=Candidate('уайли',4000,16000,18000,1,'ли')
    assert confirm(c,17920)
    assert not confirm(c,19000)
    assert not confirm(c,12000)


def test_partial_requires_adjacent_evidence_and_a_completed_bound():
    partial=StablePartial()
    words=[w('уайли',.1,.42)]
    assert partial.update(words,8192) is None
    assert partial.update(words,10240) is None
    assert partial.update(words,12288)
    assert partial.update([],14336) is None
    assert partial.update(words,16384) is None

