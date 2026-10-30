"""Explicit test-only provider. It never impersonates a real service."""
import asyncio
import time

from ..protocol import Capability, GatewayError, KeylessAdapter, Model, ProviderEvent


class TestAdapter(KeylessAdapter):
    async def status(self, account):
        return {"status": "connected", "test_only": True}

    async def models(self, account):
        return [Model(id="test-text-v1", name="Тест протокола — не нейросеть", capabilities={
            feature: Capability(state="verified", evidence="local_test_fixture", observed_at=time.time())
            for feature in ("text", "streaming")})]

    async def stream(self, account, model, messages, options):
        prompt = messages[-1]["content"]
        if isinstance(prompt, list):
            prompt = next((item.get("text", "") for item in prompt if item.get("type") == "input_text"), "")
        text = "Проверка Gateway: " + str(prompt)
        for word in text.split(" "):
            await asyncio.sleep(0.04)
            yield ProviderEvent("message.delta", {"text": word + " "})
            if prompt == "test-partial-error":
                raise GatewayError("rate_limited", "Тестовый лимит. Частичный текст сохранён.", 429)
        if prompt == "test-citation":
            yield ProviderEvent("citation.added", {"url": "https://example.com/source", "title": "Тестовый источник"})
