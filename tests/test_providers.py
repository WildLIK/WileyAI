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
