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


def test_music_profile_uses_stricter_neural_vad_and_app_vocabulary(tmp_path, monkeypatch):
    voice, captured = Voice(tmp_path), []
    def transcribe(path, **options):
        captured.append(options)
        return iter([SimpleNamespace(text="Открой Яндекс Браузер.")]), None
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=transcribe)}))
    assert voice.transcribe(b"audio", "small", quality="accurate", environment="music") == "Открой Яндекс Браузер."
    assert captured[0]["vad_parameters"] == {"threshold": 0.65, "min_speech_duration_ms": 200, "speech_pad_ms": 250}
    assert "Яндекс Браузер" in captured[0]["initial_prompt"] and "AIMP" in captured[0]["initial_prompt"]
    assert "продолжи музыку" in captured[0]["initial_prompt"] and "убавь громкость" in captured[0]["initial_prompt"]


def _wav(samples=1600):
    import io, wave
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x10" * samples)
    return out.getvalue()


def test_conversation_wav_is_decoded_in_memory_without_a_temp_file(tmp_path, monkeypatch):
    voice, received = Voice(tmp_path), []
    def transcribe(audio, **options):
        received.append(audio)
        return iter([SimpleNamespace(text="Открой Telegram.", no_speech_prob=0.01, avg_logprob=-0.2)]), None
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=transcribe)}))
    assert voice.transcribe(_wav(), "small", "Уайли") == "Открой Telegram."
    assert not isinstance(received[0], str) and len(received[0]) == 1600
    assert abs(float(received[0][0]) - 4096 / 32768) < 1e-6


@pytest.mark.parametrize("segments,expected", [
    ([("Продолжение следует...", 0.1, -0.3)], ""),
    ([("Субтитры сделал DimaTorzok", 0.2, -0.4)], ""),
    ([("Редактор субтитров А.Синецкая Корректор А.Егорова", 0.3, -0.5)], ""),
    ([("Спасибо за просмотр!", 0.1, -0.2)], ""),
    ([("Уайли, прибавь громкость на десять.", 0.02, -0.2), (" Ммм", 0.9, -1.1)], "Уайли, прибавь громкость на десять."),
    ([("Музыка, следующий трек.", 0.05, -0.3)], "Музыка, следующий трек."),
    ([("Уайли, прибавь громкость на десять. Уайли, убавь громкость. Уайли, продолжи музыку", 0.2, -0.3)], ""),
    ([("Прибавь громкость на десять.", 0.05, -0.2)], "Прибавь громкость на десять."),
])
def test_noise_inventions_and_prompt_replays_are_dropped(tmp_path, monkeypatch, segments, expected):
    voice = Voice(tmp_path)
    rows = [SimpleNamespace(text=text, no_speech_prob=silent, avg_logprob=logprob) for text, silent, logprob in segments]
    monkeypatch.setattr(voice, "_load_stt", lambda model: voice.models.update({model: SimpleNamespace(transcribe=lambda audio, **options: (iter(rows), None))}))
    assert voice.transcribe(_wav(), "small", "Уайли") == expected
