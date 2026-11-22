"""Bounded candidate rules for the offline NEXT 12 replay."""
from dataclasses import dataclass
import math

RATE = 16000
BLOCK = 2048
FRONT_END_GUARD = 1920
RING = 8 * RATE
PARAMS = dict(min_confidence=.75, max_age_samples=2*RATE, front_end_guard=FRONT_END_GUARD,
              stable_blocks=3, partial_min_end_age=3840, partial_max_end_shift=1600,
              multi_left=1280, multi_right=5120)
NAMES = (('окей','вай','ли'),('окей','уайли'),('окей','вайли'),
         ('вай','ли'),('уайли',),('вайли',))


@dataclass(frozen=True)
class Candidate:
    phrase: str
    start: int
    end: int
    decision: int
    confidence: float
    suffix: str

    @property
    def handoff(self):
        # Preserve up to 120 ms before the first estimated boundary.
        return max(0,self.end-FRONT_END_GUARD)


def parse(words, tick, *, ambiguous):
    tokens=tuple(w.get('word') for w in words)
    for name in NAMES:
        if tokens[:len(name)]!=name:
            continue
        tail=tokens[len(name):]
        if ambiguous and tail not in (('ли',),('ли','ли'),('поговорим',)):
            return None
        if not ambiguous and tail:
            return None
        try:
            start,end=map(lambda x:round(float(x)*RATE),(words[0]['start'],words[len(name)-1]['end']))
            conf=min(float(item.get('conf',1. if not ambiguous else 0.)) for item in words[:len(name)])
            if any(not math.isfinite(float(word.get('conf',1. if not ambiguous else 0.))) for word in words[:len(name)]):
                return None
        except (ValueError,TypeError,KeyError,OverflowError):
            return None
        if not (0<=start<end<=tick and 0.15*RATE<=end-start<=1.5*RATE
                and tick-end<=PARAMS['max_age_samples'] and PARAMS['min_confidence']<=conf<=1):
            return None
        if tail:
            try:
                onset=round(float(words[len(name)]['start'])*RATE)
            except (ValueError,TypeError,KeyError,OverflowError):
                return None
            if not end-160<=onset<=min(tick,end+9600):
                return None
        return Candidate(' '.join(name),start,end,tick,conf,' '.join(tail))
    return None


def confirm(candidate, timestamp):
    return candidate.end-PARAMS['multi_left']<=timestamp<=min(
        candidate.decision,candidate.end+PARAMS['multi_right'])


class StablePartial:
    def __init__(self):
        self.previous=None
        self.count=0

    def update(self, words, tick):
        current=parse(words,tick,ambiguous=False)
        old=self.previous
        if (current is not None and old is not None and current.phrase==old.phrase
                and tick-old.decision==BLOCK
                and abs(current.end-old.end)<=PARAMS['partial_max_end_shift']):
            self.count+=1
        else:
            self.count=int(current is not None)
        self.previous=current
        if current and self.count>=PARAMS['stable_blocks'] and tick-current.end>=PARAMS['partial_min_end_age']:
            return current
        return None

