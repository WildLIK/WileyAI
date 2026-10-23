"""Read-only Core Audio session meters. No microphone, PCM, files or network audio."""
from contextlib import contextmanager
import ctypes as c
import math
import os
import statistics
import threading
import time

import psutil

from .windows_audio import GUID, check, invoke, release


PLAYERS = {
    "aimp.exe": "AIMP", "yandexmusic.exe": "Яндекс Музыка",
    "яндекс музыка.exe": "Яндекс Музыка", "yandex music.exe": "Яндекс Музыка",
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
    "msedgewebview2.exe": "Встроенный браузер",
    "browser.exe": "Яндекс Браузер", "opera.exe": "Opera",
    "vlc.exe": "VLC", "wmplayer.exe": "Windows Media Player",
    "foobar2000.exe": "foobar2000", "spotify.exe": "Spotify",
}


def query(pointer, iid):
    result = c.c_void_p()
    guid = GUID.parse(iid)
    invoke(pointer, 0, [c.POINTER(GUID), c.POINTER(c.c_void_p)], c.byref(guid), c.byref(result))
    return result


@contextmanager
def session_meters():
    """COM objects are created, sampled and released on the same MTA thread."""
    if os.name != "nt":
        raise ValueError("Измеритель звука доступен в Windows")
    ole = c.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [c.c_void_p, c.c_uint32]
    ole.CoInitializeEx.restype = c.c_int32
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, c.c_uint32, c.POINTER(GUID), c.POINTER(c.c_void_p)]
    ole.CoCreateInstance.restype = c.c_int32
    initialized = ole.CoInitializeEx(None, 0)
    check(initialized)
    pointers, meters = [], []
    def own(pointer):
        pointers.append(pointer)
        return pointer
    def out(pointer, slot, types, *args):
        value = c.c_void_p()
        invoke(pointer, slot, [*types, c.POINTER(c.c_void_p)], *args, c.byref(value))
        return own(value)
    try:
        enumerator = c.c_void_p()
        clsid, iid = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E"), GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
        check(ole.CoCreateInstance(c.byref(clsid), None, 23, c.byref(iid), c.byref(enumerator)))
        own(enumerator)
        devices = out(enumerator, 3, [c.c_int, c.c_uint32], 0, 1)  # active render endpoints, including non-default outputs
        count = c.c_uint32()
        invoke(devices, 3, [c.POINTER(c.c_uint32)], c.byref(count))
        names = {}
        def collect_device(index):
            device = out(devices, 4, [c.c_uint32], index)
            master_iid = GUID.parse("5CDF2C82-841E-4546-9722-0CF74078229A")
            master = out(device, 3, [c.POINTER(GUID), c.c_uint32, c.c_void_p], c.byref(master_iid), 23, None)
            iid = GUID.parse("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")  # IAudioSessionManager2
            manager = out(device, 3, [c.POINTER(GUID), c.c_uint32, c.c_void_p], c.byref(iid), 23, None)
            sessions = out(manager, 5, [])
            total = c.c_int()
            invoke(sessions, 3, [c.POINTER(c.c_int)], c.byref(total))
            for row in range(min(total.value, 256)):
                control = out(sessions, 4, [c.c_int], row)
                try:
                    control2 = own(query(control, "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"))
                    pid = c.c_uint32()
                    invoke(control2, 14, [c.POINTER(c.c_uint32)], c.byref(pid))
                    if pid.value not in names:
                        names[pid.value] = psutil.Process(pid.value).name().casefold() if pid.value else ""
                    label = PLAYERS.get(names[pid.value])
                    if label:
                        meter = own(query(control, "C02216F6-8C67-4B5B-9D00-D008E73E0064"))
                        volume = own(query(control, "87CE5498-68D6-44E5-9215-6DA47EF883D8"))
                        meters.append((label, meter, volume, master))
                except (ValueError, psutil.Error):
                    continue
        failed = 0
        for index in range(min(count.value, 32)):
            try:
                collect_device(index)
            except ValueError:
                failed += 1  # One invalid/disconnecting output must not hide the others.
        if count.value and failed == min(count.value, 32):
            raise ValueError("Нет доступных устройств вывода для измерителя")
        yield meters
    finally:
        for pointer in reversed(pointers):
            if pointer:
                release(pointer)
        ole.CoUninitialize()


def peaks(meters):
    result = {}
    masters = {}
    for label, meter, volume, master in meters:
        level, muted, gain = c.c_float(), c.c_int32(), c.c_float()
        try:
            invoke(meter, 3, [c.POINTER(c.c_float)], c.byref(level))
            invoke(volume, 6, [c.POINTER(c.c_int32)], c.byref(muted))
            invoke(volume, 4, [c.POINTER(c.c_float)], c.byref(gain))
            if master.value not in masters:
                master_gain, master_muted = c.c_float(), c.c_int32()
                invoke(master, 9, [c.POINTER(c.c_float)], c.byref(master_gain))
                invoke(master, 15, [c.POINTER(c.c_int32)], c.byref(master_muted))
                masters[master.value] = 0 if master_muted.value else master_gain.value
            # Volume controls determine mute/zero-volume, not sensitivity. Scaling
            # the meter by both sliders made quiet audible music fall below the
            # detector threshold (and could attenuate a session peak twice).
            value = 0 if muted.value or gain.value <= 0 or masters[master.value] <= 0 else level.value
            if math.isfinite(value):
                result[label] = max(result.get(label, 0), min(1, max(0, value)))
        except ValueError:
            continue  # A closed/switched session will be rediscovered shortly.
    return result


class Rhythm:
    def __init__(self):
        self.average = 0.0
        self.last = None
        self.last_sound = -100.0
        self.since = None
        self.sound_time = 0
        self.onset = -100.0
        self.intervals = []
        self.phase = 0.0
        self.source = ""

    def update(self, levels, now):
        source, peak = max(levels.items(), key=lambda pair: pair[1], default=("", 0))
        dt = min(.2, max(0, now - self.last)) if self.last is not None else .05
        self.last = now
        if peak > .0004:
            self.source = source
            self.last_sound = now
            if self.since is None:
                self.since = now
            self.sound_time += dt
        elif now - self.last_sound > .7:
            self.since = None
            self.sound_time = 0
            self.intervals.clear()
        active = self.since is not None and self.sound_time >= .3 and now - self.since >= .65 and now - self.last_sound < .7
        if peak > max(.0012, self.average * 1.45) and now - self.onset > .27:
            interval = now - self.onset
            if .3 <= interval <= 1.5:
                self.intervals = (self.intervals + [interval])[-8:]
            self.onset = now
            self.phase = round(self.phase)
        self.average += (peak - self.average) * (1 - math.exp(-dt * 3))
        period = statistics.median(self.intervals) if len(self.intervals) >= 3 else .5
        self.phase += dt / period
        return {"active": active, "source": self.source if active else "", "level": round(min(1, math.sqrt(peak)), 3),
                "beat": round(math.exp(-max(0, now - self.onset) * 9), 3) if active else 0,
                "phase": round(self.phase, 3), "bpm": round(60 / period) if len(self.intervals) >= 3 and active else None, "error": "", "players": sorted(levels)}


SILENT = {"active": False, "source": "", "level": 0, "beat": 0, "phase": 0, "bpm": None, "error": ""}


class MusicMeter:
    """A single shared worker, leased by visible avatar streams only."""
    def __init__(self, enabled):
        self.enabled = enabled
        self.lock = threading.Lock()
        self.clients = 0
        self.closed = threading.Event()
        self.thread = None
        self.value = dict(SILENT)

    @contextmanager
    def subscribe(self):
        with self.lock:
            self.clients += 1
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name="avatar-music-meter", daemon=True)
                self.thread.start()
        try:
            yield
        finally:
            with self.lock:
                self.clients -= 1

    def _run(self):
        rhythm = Rhythm()
        while not self.closed.is_set():
            with self.lock:
                if not self.clients:
                    self.value = dict(SILENT)
                    self.thread = None
                    return
            if not self.enabled():
                self.value = dict(SILENT)
                self.closed.wait(.2)
                continue
            try:
                with session_meters() as meters:
                    until = time.monotonic() + 1.5
                    while not self.closed.is_set() and time.monotonic() < until:
                        if not self.clients or not self.enabled():
                            break
                        self.value = rhythm.update(peaks(meters), time.monotonic())
                        self.closed.wait(.05)
            except Exception:
                self.value = {**SILENT, "error": "Не удалось прочитать уровень звука Windows"}
                self.closed.wait(2)

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=3)
