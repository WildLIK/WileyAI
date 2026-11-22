from contextlib import contextmanager
import ctypes as c
from types import SimpleNamespace

import pytest
from core import audio_sessions
from core.audio_sessions import set_volume as native_set_volume


@pytest.mark.parametrize("scenario", ["confirmed", "refused", "stale_session", "reused_pid", "exited_process"])
def test_exact_mixer_session_and_process_are_revalidated_before_one_write(monkeypatch, scenario, tmp_path):
    exe = str(tmp_path / "player.exe")
    row = {"id": "selected", "pid": 42, "created": 12, "executable": exe, "volume": 60}
    @contextmanager
    def sessions(): yield [(row, "COM_VOLUME")]
    monkeypatch.setattr(audio_sessions, "sessions", sessions)
    def process(pid):
        if scenario == "exited_process": raise audio_sessions.psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: 13 if scenario == "reused_pid" else 12, exe=lambda: exe)
    monkeypatch.setattr(audio_sessions.psutil, "Process", process)
    writes = []; level = [60]
    def invoke(pointer, slot, types, *args):
        assert pointer == "COM_VOLUME"
        if slot == 3:
            writes.append(args[0]);
            if scenario != "refused": level[0] = args[0] * 100
        elif slot == 4: c.cast(args[0], c.POINTER(c.c_float)).contents.value = level[0] / 100
        else: pytest.fail("Unexpected COM mutation")
    monkeypatch.setattr(audio_sessions, "invoke", invoke)
    if scenario == "confirmed":
        assert native_set_volume("selected", exe, 12, -10)["volume"] == 50
        assert writes == [.5]
    else:
        with pytest.raises(ValueError): native_set_volume("gone" if scenario == "stale_session" else "selected", exe, 12, -10)
        assert writes == ([.5] if scenario == "refused" else [])
