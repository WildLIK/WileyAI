import math
import os
import time
import threading
import ctypes as c

import pytest

from core.music_meter import MusicMeter, Rhythm, session_meters, peaks


def test_rhythm_tracks_synthetic_pulses_and_stops_on_pause():
    rhythm = Rhythm()
    result = None
    for i in range(200):
        now = i * .05
        result = rhythm.update({"AIMP": .7 if i % 10 == 0 else .04}, now)
    assert result["active"] and result["source"] == "AIMP"
    assert result["bpm"] == 120
    beat = rhythm.update({"AIMP": .8}, 10)
    assert beat["beat"] > .5
    for i in range(1, 25):
        result = rhythm.update({"AIMP": 0}, 10 + i * .05)
    assert not result["active"] and result["bpm"] is None


def test_notification_and_silence_do_not_start_a_dance():
    rhythm = Rhythm()
    for i in range(50):
        result = rhythm.update({"Chrome": .8 if i == 1 else 0}, i * .05)
        assert not result["active"]


def test_quiet_music_is_not_lost_by_multiplying_volume_sliders(monkeypatch):
    import core.music_meter as module
    meter, volume, master = c.c_void_p(1), c.c_void_p(2), c.c_void_p(3)
    values = {(1, 3): .0008, (2, 6): 0, (2, 4): .02, (3, 9): .03, (3, 15): 0}
    def invoke(pointer, slot, types, *args):
        args[-1]._obj.value = values[pointer.value, slot]
    monkeypatch.setattr(module, "invoke", invoke)
    meters = [("Яндекс Музыка", meter, volume, master)]
    levels = peaks(meters)
    assert levels["Яндекс Музыка"] == pytest.approx(.0008)
    rhythm = Rhythm()
    for i in range(30):
        result = rhythm.update(levels, i * .05)
    assert result["active"] and result["source"] == "Яндекс Музыка"
    values[2, 6] = 1
    assert peaks(meters)["Яндекс Музыка"] == 0
    values[2, 6], values[3, 15] = 0, 1
    assert peaks(meters)["Яндекс Музыка"] == 0
    values[3, 15], values[3, 9] = 0, 0
    assert peaks(meters)["Яндекс Музыка"] == 0


def test_worker_is_shared_released_and_closes_without_clients(monkeypatch):
    from contextlib import contextmanager
    import core.music_meter as module
    entries = []
    started = threading.Event()
    @contextmanager
    def meters():
        entries.append("opened")
        started.set()
        try:
            yield []
        finally:
            entries.append("closed")
    monkeypatch.setattr(module, "session_meters", meters)
    monkeypatch.setattr(module, "peaks", lambda meters: {"AIMP": .1})
    worker = MusicMeter(lambda: True)
    with worker.subscribe():
        assert started.wait(timeout=1)
        thread = worker.thread
        with worker.subscribe():
            assert worker.thread is thread and worker.clients == 2
    worker.close()
    assert worker.clients == 0 and not thread.is_alive()
    assert entries.count("opened") == entries.count("closed")


@pytest.mark.skipif(os.name != "nt", reason="Windows COM metering")
def test_native_session_meter_is_read_only_and_finite():
    # No playback or microphone capture; validates actual COM slots and cleanup.
    with session_meters() as meters:
        for value in peaks(meters).values():
            assert math.isfinite(value) and 0 <= value <= 1
