from pathlib import Path
from types import SimpleNamespace

import pytest

from core.voice import Voice


@pytest.mark.parametrize("quality,beam", [("fast", 1), ("balanced", 3), ("accurate", 5)])
def test_recognition_uses_selected_search_and_cleans_recording(tmp_path, monkeypatch, quality, beam):
    voice = Voice(tmp_path)
    captured = []
    def transcribe(path, **options):
        assert Path(path).read_bytes() == b"recording"
        captured.append((path, options))
        return iter([SimpleNamespace(text=" Прибавь громкость на десять. ")]), None
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=transcribe)}))
    assert voice.transcribe(b"recording", "small", "Алиса", quality) == "Прибавь громкость на десять."
    path, options = captured[0]
    assert not Path(path).exists()
    assert options["beam_size"] == beam and options["temperature"] == 0
    assert options["language"] == "ru" and options["vad_filter"] is True
    assert options["condition_on_previous_text"] is False
    assert "Алиса" in options["initial_prompt"] and "прибавь" in options["initial_prompt"]


def test_recognition_cleans_recording_even_on_lazy_decoder_error(tmp_path, monkeypatch):
    voice, paths = Voice(tmp_path), []
    def broken(path, **options):
        paths.append(path)
        def segments():
            raise RuntimeError("decoder failed")
            yield
        return segments(), None
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=broken)}))
    with pytest.raises(RuntimeError, match="decoder failed"):
        voice.transcribe(b"recording", "small")
    assert all(not Path(path).exists() for path in paths)
