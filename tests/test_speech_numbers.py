import re
from types import SimpleNamespace

import pytest

from core.speech_numbers import silero_numbers
from core.voice import Voice


@pytest.mark.parametrize("source,expected", [
    ("Сейчас: 3.7 °C.", "Сейчас: три целых семь десятых градуса Цельсия."),
    ("Ощущается как -2.9 °C.", "Ощущается как минус две целых девять десятых градуса Цельсия."),
    ("Ветер 8.65 м/с.", "Ветер восемь целых шестьдесят пять сотых метра в секунду."),
    ("Температура 1.4…4 °C.", "Температура от одной целой четырёх десятых до четырёх градусов Цельсия."),
    ("Температура -7…-1 °C.", "Температура от минус семи до минус одного градуса Цельсия."),
    ("Осадки: 88%.", "Осадки: восемьдесят восемь процентов."),
    ("+1 °С, 2 °C, 5 °C", "плюс один градус Цельсия, два градуса Цельсия, пять градусов Цельсия"),
    ("Скорость: 21 км/ч.", "Скорость: двадцать один километр в час."),
    ("-0.7; 0,01; 125; 1000; 6.", "минус ноль целых семь десятых; ноль целых одна сотая; сто двадцать пять; одна тысяча; шесть."),
    ("Дата 21.10.2026.", "Дата двадцать первое октября две тысячи двадцать шестого года."),
    ("Расчёт на 2026-10-21T15:30.", "Расчёт на двадцать первое октября две тысячи двадцать шестого года в пятнадцать часов тридцать минут."),
    ("В 01:21.", "В один час двадцать одна минута."),
    ("Данные проверены. [1]", "Данные проверены."),
    ("Список: [1, 2]", "Список: [один, два]"),
])
def test_silero_numbers_and_units_are_spoken(source, expected):
    assert silero_numbers(source) == expected
    assert silero_numbers(expected) == expected


@pytest.mark.parametrize("engine", ["silero", "silero_v5_6"])
def test_silero_model_receives_words_before_chunking(tmp_path, monkeypatch, engine):
    voice, received = Voice(tmp_path), []
    monkeypatch.setattr(voice, "tts_available", lambda: True)
    monkeypatch.setattr(voice, "tts_installed", lambda *args: True)
    monkeypatch.setattr(voice, "_load_tts", lambda *args: None)
    class Audio:
        def numpy(self): return [0.0] * 100
    def speak(**body):
        received.append(body["text"])
        return Audio()
    voice.tts_model = SimpleNamespace(apply_tts=speak)
    wave = voice.synthesize("Сейчас 3.7 °C. " * 25 + "Ощущается как -2.9 °C. Ветер 8.65 м/с. Осадки 88%.", "xenia", engine=engine)
    assert wave.startswith(b"RIFF") and len(received) > 1
    assert all(not re.search(r"\d", text) and len(text) <= 240 for text in received)
    assert "минус две целых девять десятых" in " ".join(received)
