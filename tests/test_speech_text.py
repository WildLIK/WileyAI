import asyncio
import json
from types import SimpleNamespace

import pytest

from core.speech_text import plain_speech, speech_chunks
from core.voice import Voice


@pytest.mark.parametrize("source,expected", [
    ("**Работа с документами:** Я могу читать файлы.", "Работа с документами: Я могу читать файлы."),
    ("* **Управление задачами:** Создаю списки.\n* **Память:** Храню факты.", "Управление задачами: Создаю списки.\nПамять: Храню факты."),
    ("**Важная незакрытая фраза", "Важная незакрытая фраза"),
    ("***Привет*** и *курсив*, __жирный текст__, _обычный_.", "Привет и курсив, жирный текст, обычный."),
    ("# План\n1. Купить хлеб.\n- Проверить почту.\n> Готово.", "План\nКупить хлеб.\nПроверить почту.\nГотово."),
    ("[Инструкция](https://example.org/a_(b)) и ![Схема](https://example.org/p.png)", "Инструкция и Схема"),
    ("[Документ][source]\n[source]: https://example.org/", "Документ"),
    ("```python\nprint('Привет')\n```\nИмя: `snake_case`.", "print('Привет')\nИмя: snake_case."),
    ("| Имя | Дата |\n| :--- | ---: |\n| План | завтра |", "Имя; Дата\nПлан; завтра"),
    ("<b>Привет</b> &amp; &ast;&ast;мир&ast;&ast;!<!-- скрыто -->", "Привет & мир!"),
    ("Два: 2 * 3 = 6. Файл user_name.txt", "Два: 2 умножить на 3 = 6. Файл user_name.txt"),
    ("Уда́рение, ёлка, 3.14 и 2026 год.", "Уда́рение, ёлка, 3.14 и 2026 год."),
])
def test_markdown_is_read_as_plain_text(source, expected):
    assert plain_speech(source) == expected


@pytest.mark.parametrize("text", ["", "  \n ", "***", "---\n```\n```", "![](https://example.org/)"])
def test_markup_only_has_a_clear_error(text):
    with pytest.raises(ValueError, match="нет текста для озвучки"):
        plain_speech(text)


def test_long_markdown_cannot_split_silero_emphasis_across_chunks():
    raw = "Привет. " * 28 + "**Работа с документами и календарём:** Я могу помочь. " * 10
    parts = speech_chunks(plain_speech(raw))
    assert len(parts) > 1
    assert all("*" not in part and len(part) <= 240 for part in parts)
    assert " ".join(parts) == plain_speech(raw)


def test_chunking_prefers_a_complete_sentence_and_keeps_all_text():
    sentences = ["Это первое предложение.", "Это второе предложение, которое длиннее первого.", "Готово?"]
    parts = speech_chunks(" ".join(sentences), limit=65)
    assert parts == [sentences[0], " ".join(sentences[1:])]
    assert max(map(len, speech_chunks("я" * 600))) <= 240


def test_piper_receives_plain_text_before_chunking(tmp_path, monkeypatch):
    voice = Voice(tmp_path)
    spoken = []
    class Model:
        def synthesize(self, text):
            spoken.append(text)
            yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=b"\0\0" * 100)
    monkeypatch.setattr(voice.piper, "load", lambda name: Model())
    audio = voice.synthesize("* **Работа с документами:** Читаю файлы.", "irina", engine="piper")
    assert spoken == ["Работа с документами: Читаю файлы."]
    assert audio.startswith(b"RIFF")


def test_sapi_receives_plain_text_on_stdin(tmp_path, monkeypatch):
    async def scenario():
        voice = Voice(tmp_path)
        received = []
        class Process:
            returncode = 0
            async def communicate(self, data):
                received.append(json.loads(data))
                return b"RIFFaudio", b""
        async def spawn(*args, **kwargs):
            return Process()
        monkeypatch.setattr("core.voice.os", SimpleNamespace(name="nt"))
        monkeypatch.setattr("core.voice.asyncio.create_subprocess_exec", spawn)
        assert await voice.render("**Работа с документами:** Читаю файлы.", "", "sapi") == b"RIFFaudio"
        assert received[0]["text"] == "Работа с документами: Читаю файлы."
    asyncio.run(scenario())
