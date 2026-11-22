"""Fixture-only STT checks: no real decoder, microphone, tools or downloads."""
import io
import wave
from types import SimpleNamespace
import pytest

from core.voice import Voice, speech_prompt
from core.stt_guard import assess_transcript


def audio(seconds):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b"\x00\x10" * int(16000 * seconds))
    return stream.getvalue()


def model(monkeypatch, voice, text, seconds):
    calls = []
    def transcribe(samples, **options):
        calls.append(options)
        return iter([SimpleNamespace(text=text, no_speech_prob=.01, avg_logprob=-.2)]), SimpleNamespace(duration=seconds, duration_after_vad=seconds)
    monkeypatch.setattr(voice, "_load_stt", lambda name: voice.models.update({name: SimpleNamespace(transcribe=transcribe)}))
    return calls


def test_short_clip_program_loop_cannot_be_returned_as_a_command(tmp_path, monkeypatch):
    voice = Voice(tmp_path)
    text = ("Blender, AIMP, Chrome, Firefox, Telegram, Blender. " * 10)[:452]
    model(monkeypatch, voice, text, .744)
    result = voice.transcribe(audio(.744), "small", "Вайли", vocabulary=["Blender", "AIMP", "Chrome", "Firefox"])
    assert result == ""
    assert result.reason == "stt_repetitive_transcript" and result.characters == 452


@pytest.mark.parametrize("text,seconds", [
    ("Открой Blender, AIMP, Chrome, Firefox и Telegram.", 5),
    ("Blender, AIMP, Chrome, Firefox, Telegram. " * 12, 60),
    ("Я диктую длинный текст о Луне и планетах. " * 40, 120),
    ("Повтори слово да. Да, да, да, да, да, да, да, да, да, да.", 12),
    ("Не открывай Blender и не запускай музыку.", 3),
    ("Уайли, прибавь громкость на десять. Уайли, убавь громкость. Уайли, продолжи музыку", 15),
], ids=["app-list", "long-app-list", "dictation", "deliberate-repetition", "negative-command", "spoken-prompt"])
def test_valid_lists_dictation_negation_and_deliberate_repetition_survive(tmp_path, monkeypatch, text, seconds):
    voice = Voice(tmp_path); calls = model(monkeypatch, voice, text, seconds)
    assert voice.transcribe(audio(seconds), "small", "Уайли") == text.strip()
    assert len(calls) == 1
    assert "max_new_tokens" not in calls[0]


def test_short_prompt_is_bounded_and_decoder_has_a_short_clip_only_budget(tmp_path, monkeypatch):
    voice = Voice(tmp_path); calls = model(monkeypatch, voice, "Открой Blender.", .744)
    assert voice.transcribe(audio(.744), "small", "Уайли", vocabulary=["Blender", "AIMP", "Chrome", "Firefox", "Telegram"]) == "Открой Blender."
    assert calls[0]["max_new_tokens"] == 64
    prompt = calls[0]["initial_prompt"]
    assert "Blender" in prompt and "Telegram" not in prompt
    assert "прибавь" not in prompt and len(prompt) < 200
    assert "продолжи музыку" in speech_prompt("Уайли")


def test_digital_silence_does_not_load_or_run_a_decoder(tmp_path, monkeypatch):
    voice = Voice(tmp_path)
    monkeypatch.setattr(voice, "_load_stt", lambda name: pytest.fail("Digital silence must not invoke a model"))
    data = bytearray(audio(.744)); data[44:] = b"\0" * (len(data) - 44)
    result = voice.transcribe(bytes(data), "small")
    assert result == "" and result.reason == "stt_no_signal"


def test_unknown_duration_is_not_invented_from_text_length():
    text = "Blender, AIMP, Firefox, Telegram. " * 12
    assert assess_transcript(text, "", None) == text.strip()
    assert assess_transcript(text, "", float("nan")) == text.strip()


def test_decoder_metadata_bounds_encoded_audio_without_retry(tmp_path, monkeypatch):
    voice = Voice(tmp_path); text = "Blender AIMP Chrome Firefox Telegram " * 15
    calls = model(monkeypatch, voice, text, .744)
    result = voice.transcribe(b"encoded", "small")
    assert result == "" and result.reason == "stt_repetitive_transcript" and len(calls) == 1


def test_api_rejected_transcript_has_metadata_but_no_text_or_execution_ticket(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from core.api import create_app
    text = "Blender AIMP Chrome Firefox Telegram " * 15
    calls = []
    def transcribe(self, *args):
        calls.append(1)
        return assess_transcript(text, "", .744)
    monkeypatch.setattr(Voice, "transcribe", transcribe)
    with TestClient(create_app(tmp_path, "stt-reliability-0123456789"), headers={"Authorization": "Bearer stt-reliability-0123456789"}) as client:
        result = client.post("/voice/transcribe", files={"file": ("clip.wav", audio(.744), "audio/wav")}, data={"trace": "true"})
        assert result.status_code == 200
        value = result.json()
        assert value["text"] == "" and value["rejected_reason"] == "stt_repetitive_transcript"
        assert value["rejected_characters"] == len(text.strip()) and "recognition_id" not in value
        assert client.get("/messages").json() == [] and calls == [1]
        assert "Blender" not in result.text
