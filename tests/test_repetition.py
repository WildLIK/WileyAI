import asyncio
import json

import httpx
import pytest

from core import providers
from core.config import Settings
from core.repetition import RepetitionGuard, history_text


LOOP = " ".join(f"Я готова, чтобы вы увидели, как я могу быть той, кто делает ваш день {word}, через свои эмоции." for word in ["ярким", "весёлым", "тёплым", "красивым", "живым", "счастливым"] * 10)


@pytest.mark.parametrize("provider", ["ollama", "compatible"])
@pytest.mark.parametrize("chunk", [1, 47, 20000])
def test_stream_stops_varying_repeated_prose_before_the_token_limit(monkeypatch, provider, chunk):
    def handler(request):
        lines = []
        for index in range(0, len(LOOP), chunk):
            text = LOOP[index:index + chunk]
            value = {"message": {"content": text}} if provider == "ollama" else {"choices": [{"delta": {"content": text}}]}
            lines.append(("" if provider == "ollama" else "data: ") + json.dumps(value) + "\n")
        lines.append(json.dumps({"done": True}) if provider == "ollama" else 'data: [DONE]')
        return httpx.Response(200, text="\n".join(lines))
    monkeypatch.setattr(providers, "client", lambda settings: httpx.AsyncClient(base_url="http://127.0.0.1/", transport=httpx.MockTransport(handler)))
    result = []
    async def run():
        async for value in providers.chat(Settings(provider=provider), [{"role": "user", "content": "Как дела?"}]):
            result.append(value)
    with pytest.raises(providers.RepetitionStopped, match="повтор"):
        asyncio.run(run())
    assert 100 < len("".join(result)) < len(LOOP) / 3


def test_repeated_code_quotes_tables_and_varied_long_prose_remain_usable():
    repeated = "Это длинная повторяющаяся цитата для проверки сохранения исходного текста без вмешательства в данные."
    samples = ["```python\n" + ("print('hello world')\n" * 100) + "```", "> " + ("\n> ".join([repeated] * 20)), "\n".join(["| " + repeated + " |"] * 20), " ".join(f"Параметр {i} имеет значение {i * 3} и относится к группе {i % 7}." for i in range(100))]
    for sample in samples:
        guard = RepetitionGuard()
        assert not any(guard.repetitive(sample[i:i + 31]) for i in range(0, len(sample), 31))


def test_short_word_loop_is_bounded():
    guard = RepetitionGuard()
    assert any(guard.repetitive("да " * 20) for _ in range(10))


def test_old_loop_is_compressed_without_losing_the_useful_ending():
    compact = history_text("Начало ответа. " + LOOP + " Последний вопрос: какую главу разобрать?")
    assert len(compact) < 600
    assert compact.startswith("Начало ответа.")
    assert compact.endswith("Последний вопрос: какую главу разобрать?")
