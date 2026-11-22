"""Real /chat routing and action guards with an isolated model catalog."""
import asyncio

import httpx
import pytest

from core import providers
from core.config import Settings
from core.model_routing import answer_model
from tests.test_voice365_e2e import scene, chat, outcome


def test_chat_tiers_and_disabled_setting(scene, monkeypatch):
    client, app, _, _ = scene
    store = app.state.store
    store.patch_settings({"model": "chosen:4b", "fast_model": "fast:1b", "intent_gate": False})
    inference, catalog = [], []

    async def installed(settings):
        catalog.append(settings.model)
        return [{"id": "fast:1b", "size": 100}]

    async def generate(settings, *args, **kwargs):
        inference.append(settings.model)
        yield "Готово."

    monkeypatch.setattr(providers, "list_models", installed)
    monkeypatch.setattr(providers, "chat", generate)

    # The audio fast path accepts and executes the existing command before model selection.
    assert outcome(chat(client, "Следующий трек"))["status"] == "confirmed"
    assert inference == catalog == []

    def ask(text):
        conversation_id = client.post("/conversations", json={"title": "Fixture"}).json()["id"]
        events = chat(client, text, conversation_id=conversation_id)
        return next(item for item in events if item["type"] == "voice_timing")

    store.patch_settings({"intent_gate": True})
    async def forbidden_classifier(*args, **kwargs):
        pytest.fail("A standalone fast question must not run the Intent Gate")
    monkeypatch.setattr(providers, "structured", forbidden_classifier)
    simple = ask("Сколько будет два плюс два?")
    store.patch_settings({"intent_gate": False})
    complex_ = ask("Объясни, почему днём не видны звёзды, и предложи способ это проверить.")
    assert inference == ["fast:1b", "chosen:4b"] and catalog == ["chosen:4b"]
    assert simple["model_tier"] == "fast" and complex_["model_tier"] == "selected"
    assert 0 <= simple["model_begin_ms"] <= simple["model_first_ms"]
    assert simple["request_id"]
    assert store.settings().model == "chosen:4b"

    store.patch_settings({"fast_model": ""})
    assert ask("Что такое инерция?")["model_tier"] == "manual"
    assert inference[-1] == "chosen:4b" and len(catalog) == 1


@pytest.mark.parametrize("catalog,reason", [
    ([], "fast_unavailable"),
    ([{"id": "fast:1b", "size": 0}], "fast_unavailable"),
    ([{"id": "fast:1b", "size": 10, "remote": True}], "fast_unavailable"),
    ([{"id": "fast:1b", "size": 10}], "fast"),
])
def test_fast_requires_local_installed_binary(monkeypatch, catalog, reason):
    async def installed(settings):
        return catalog
    monkeypatch.setattr(providers, "list_models", installed)
    settings = Settings(model="chosen:4b", fast_model="fast:1b")
    selection, route = asyncio.run(answer_model(settings, "Что такое инерция?", has_sources=False))
    assert route == reason
    assert selection.model == ("fast:1b" if reason == "fast" else settings.model)


def test_catalog_network_failure_is_bounded_and_no_cloud_lookup(monkeypatch):
    calls = []
    async def unavailable(settings):
        calls.append(1)
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(providers, "list_models", unavailable)
    settings = Settings(fast_model="fast:1b")
    question = "Что такое инерция?"
    assert asyncio.run(answer_model(settings, question, has_sources=False)) == (settings, "fast_unavailable")
    assert asyncio.run(answer_model(settings, question, has_sources=True)) == (settings, "selected")
    assert asyncio.run(answer_model(settings, "Сколько будет стоить ремонт квартиры?", has_sources=False)) == (settings, "selected")
    remote = settings.model_copy(update={"base_url": "https://example.invalid"})
    assert asyncio.run(answer_model(remote, question, has_sources=False)) == (remote, "manual")
    assert calls == [1]
