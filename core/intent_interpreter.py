"""Bounded interpretation of whole user utterances; never produces paths or tool IDs."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Intent:
    intent: str
    action: str
    target: str
    device: str = "computer"
    parameters: tuple = ()
    confidence: float = 1.0
    requires_confirmation: bool = False
    permission: str = "apps.open"


def interpret(text, name="Уайли"):
    if not isinstance(text, str) or len(text) > 500 or any(ord(c) < 32 for c in text) or any(c in text for c in '"«»“”'):
        return None
    value = text.strip()
    if re.search(r"\b(?:не|никогда|если|например|расскажи|объясни|почему|как|попросил|попросила|сказал|сказала)\b", value, re.I):
        return None
    value = re.sub(r"^" + re.escape(name) + r"[,! ]+", "", value, flags=re.I)
    value = re.sub(r"^(?:а\s+теперь|теперь|пожалуйста)[, ]+", "", value, flags=re.I)
    value = re.sub(r",?\s+пожалуйста(?=[.!? ]*$)", "", value, flags=re.I)
    device = "phone" if re.search(r"\s+на\s+(?:телефоне|смартфоне)[.!? ]*$", value, re.I) else "computer"
    value = re.sub(r"\s+на\s+(?:телефоне|смартфоне)(?=[.!? ]*$)", "", value, flags=re.I)
    value = re.sub(r"\s+на\s+(?:компьютере|пк)(?=[.!? ]*$)", "", value, flags=re.I)
    if re.search(r"[.!?;]\s*(?:открой|открывай|запусти|запускай|включи|выключи|удали|отправь)\b", value, re.I):
        return None
    if re.search(r"\b(?:и|затем|потом|после)\s+(?:открой|запусти|включи|выключи|удали|сделай|отправь|поставь)\b", value, re.I):
        return None
    indirect = re.fullmatch(r"мне\s+(?:нужен|нужна|нужно)\s+(.+?)[.! ]*", value, re.I)
    if indirect:
        return Intent("open", "open", indirect[1].strip(), device=device, confidence=.6, requires_confirmation=True)
    polite = re.fullmatch(r"(?:ты\s+)?можешь,?\s+(?:пожалуйста,?\s+)?(?:открыть|запустить|включить)\s+(?:мне\s+)?(.+?)\??[.! ]*", value, re.I)
    if polite:
        return Intent("open", "open", polite[1].strip(), device=device)
    direct = re.fullmatch(r"(?:(?:давай\s+)?(?:открой|открывай|запусти|запускай|включи)|давай\s+(?:откроем|запустим|включим))\s+(?:мне\s+)?(.+?)[.! ]*", value, re.I)
    if direct and "?" not in direct[1]:
        if re.match(r"(?:сайт\s+)?https?://", direct[1], re.I):
            return None  # Existing URL parser preserves the exact case and query.
        return Intent("open", "open", direct[1].strip(), device=device)
    return None
