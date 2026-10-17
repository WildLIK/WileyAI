import asyncio
import json

import httpx
import pytest

from core.config import Settings
from core import providers


@pytest.mark.parametrize("provider", ["ollama", "compatible"])
@pytest.mark.parametrize("ending", ["stop", "length", "missing"])
def test_response_budget_and_completion_are_not_silently_ignored(monkeypatch, provider, ending):
    requests, received = [], []
    def handler(request):
        requests.append(json.loads(request.content))
        if provider == "ollama":
            lines = [json.dumps({"message": {"content": "Начало ответа. Нужно ли"}, "done": False})]
            if ending != "missing": lines.append(json.dumps({"done": True, "done_reason": ending}))
        else:
            lines = ['data: ' + json.dumps({"choices": [{"delta": {"content": "Начало ответа. Нужно ли"}}]})]
            if ending != "missing": lines += ['data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": ending}]}), 'data: [DONE]']
        return httpx.Response(200, text="\n".join(lines) + "\n")
    monkeypatch.setattr(providers, "client", lambda settings: httpx.AsyncClient(base_url="http://127.0.0.1/", transport=httpx.MockTransport(handler)))
    async def scenario():
        async for text in providers.chat(Settings(provider=provider, response_tokens=3072, context_tokens=8192), [{"role": "user", "content": "Вопрос"}]):
            received.append(text)
    if ending == "stop": asyncio.run(scenario())
    else:
        with pytest.raises(providers.IncompleteResponse): asyncio.run(scenario())
    assert "".join(received) == "Начало ответа. Нужно ли"
    assert (requests[0]["options"]["num_predict"] if provider == "ollama" else requests[0]["max_tokens"]) == 3072


def test_answer_does_not_implicitly_expand_context_memory():
    assert providers.response_limit(Settings(context_tokens=4096, response_tokens=8192)) == 2048


@pytest.mark.parametrize("provider", ["ollama", "compatible"])
def test_structured_decision_uses_native_schema_and_a_small_output_budget(monkeypatch, provider):
    requests = []
    schema = {"type": "object", "properties": {"mode": {"type": "string", "enum": ["full", "fragments"]}}, "required": ["mode"], "additionalProperties": False}
    def handler(request):
        requests.append(json.loads(request.content))
        if provider == "ollama":
            text = json.dumps({"message": {"content": '{"mode":"full"}'}, "done": True}) + "\n"
        else:
            text = 'data: ' + json.dumps({"choices": [{"delta": {"content": '{"mode":"full"}'}, "finish_reason": "stop"}]}) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=text)
    monkeypatch.setattr(providers, "client", lambda config: httpx.AsyncClient(base_url="http://127.0.0.1/", transport=httpx.MockTransport(handler)))
    settings = Settings(provider=provider).model_copy(update={"response_tokens": 64, "temperature": 0})
    assert asyncio.run(providers.structured(settings, [{"role": "user", "content": "прочитай"}], schema)) == '{"mode":"full"}'
    assert len(requests) == 1
    if provider == "ollama":
        assert requests[0]["format"] == schema and requests[0]["options"]["num_predict"] == 64
    else:
        assert requests[0]["response_format"]["json_schema"]["schema"] == schema and requests[0]["max_tokens"] == 64


@pytest.mark.parametrize("status,detail,retry", [(400, "response_format unsupported", True), (422, "json_schema unsupported", True), (400, "model is invalid", False), (401, "auth", False), (429, "quota", False), (500, "response_format failure", False)])
def test_only_unsupported_compatible_format_gets_one_retry(monkeypatch, status, detail, retry):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(status, json={"error": detail})
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{\\"mode\\":\\"fragments\\"}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(providers, "client", lambda config: httpx.AsyncClient(base_url="http://127.0.0.1/", transport=httpx.MockTransport(handler)))
    if retry:
        assert asyncio.run(providers.structured(Settings(provider="compatible"), [], {"type": "object"})) == '{"mode":"fragments"}'
        assert len(requests) == 2 and "response_format" in requests[0] and "response_format" not in requests[1]
        assert "схеме" in requests[1]["messages"][0]["content"] and '"type": "object"' in requests[1]["messages"][0]["content"]
    else:
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(providers.structured(Settings(provider="compatible"), [], {"type": "object"}))
        assert len(requests) == 1


def test_structured_long_drafts_are_bounded_and_the_stream_is_closed(monkeypatch):
    closed = []
    async def chat(*args, **kwargs):
        try:
            yield "а" * 2049
        finally:
            closed.append(True)
    monkeypatch.setattr(providers, "chat", chat)
    with pytest.raises(ValueError, match="длинный"):
        asyncio.run(providers.structured(Settings(), [], {"type": "object"}))
    assert closed == [True]
    assert len(asyncio.run(providers.structured(Settings(), [], {"type": "object"}, max_chars=8192))) == 2049
    assert closed == [True, True]
