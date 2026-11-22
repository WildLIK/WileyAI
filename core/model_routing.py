"""Optional answer-model selection after the existing command handlers decline."""
import asyncio
import re
from urllib.parse import urlsplit

import httpx

from . import providers
from .config import Settings

_ARITHMETIC = r"(?:[\d +*/×÷−-]|ноль|один|два|три|четыре|пять|шесть|семь|восемь|девять|десять|плюс|минус|умножить|делить|на)+"
_SIMPLE = re.compile(
    rf"(?:что такое [\w -]+|переведи на (?:английский|русский) [\w -]+|"
    rf"сколько будет {_ARITHMETIC})[?.!]?"
)
_COMPLEX = re.compile(r"\b(?:и|или|затем|сравни|объясни|почему|как|докажи|подробно|распиши|план|который|которого)\b")


async def answer_model(settings: Settings, text: str, *, has_sources: bool) -> tuple[Settings, str]:
    if not settings.fast_model.strip():
        return settings, "manual"
    endpoint = urlsplit(settings.base_url)
    if settings.provider != "ollama" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return settings, "manual"
    fast = settings.fast_model.strip()
    text = " ".join(text.casefold().split())
    if (has_sources or len(text) > 100 or len(text.split()) > 12 or not _SIMPLE.fullmatch(text)
            or _COMPLEX.search(text) or fast == settings.model or fast.casefold().endswith((":cloud", "-cloud"))):
        return settings, "selected"
    try:
        models = await asyncio.wait_for(providers.list_models(settings), timeout=1.0)
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
        return settings, "fast_unavailable"
    if not any(model["id"] == fast and model["size"] > 0 and not model.get("remote") for model in models):
        return settings, "fast_unavailable"
    return settings.model_copy(update={"model": fast}), "fast"
