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


def request_prefix(text, extra_verbs=()):
    """Drop only a bounded leading filler before a whole action grammar.

    Quoted/reported/conditional speech and the negation itself stay intact.
    The downstream parser still validates the entire remaining utterance.
    """
    if len(text) > 1000 or any(c in text for c in '"«»“”\n\r'): return text
    value = text.strip()
    candidate = value
    for _ in range(3):
        changed = re.sub(r"^(?:а[- ]а|ну(?:-ка)?|слушай|а\s+теперь|теперь)[,! ]+", "", candidate, count=1, flags=re.I)
        if changed == candidate: break
        candidate = changed
    extra = "|" + "|".join(re.escape(verb) for verb in extra_verbs) if extra_verbs else ""
    if re.match(r"(?:не\s+)?(?:открой|запусти|включи|продолжи|возобнови|поставь|сделай|убавь|прибавь|найди|следующий|предыдущий|пауза|давай|можешь" + extra + r")\b", candidate, re.I):
        return candidate
    return value


def repair_open_punctuation(text):
    # One ASR-inserted dot immediately after an imperative only. Never join
    # subsequent clauses, remove negation, or repair a quoted instruction.
    match = re.fullmatch(r"(открой|запусти|открывай|запускай)\.\s+([^\n.!?;]+)[.! ]*", text.strip(), re.I)
    if match and not re.search(r"\b(?:не|и|затем|потом|открой|запусти|удали|закрой|выключи)\b", match[2], re.I):
        return match[1] + " " + match[2].strip()
    return text


def control_intent(text, name="Уайли"):
    """Local non-opening intents cannot be delegated to a conversational LLM."""
    if not isinstance(text, str) or len(text) > 500 or any(c in text for c in '\"«»“”\n\r'):
        return None
    value = request_prefix(re.sub(r"^" + re.escape(name) + r"[,!. ]+", "", text.strip(), flags=re.I))
    prohibited = re.fullmatch(r"(?:не\s+(?:открывай|открой|запускай|запусти)|не\s+надо\s+(?:открывать|запускать))\s+(.+?)[.! ]*", value, re.I)
    if prohibited:
        return Intent("prohibited", "open", prohibited[1], permission="")
    cancelled = re.fullmatch(r"отмени\s+(?:запуск|открытие)(?:\s+(.+?))?[.! ]*", value, re.I)
    if cancelled:
        return Intent("cancelled", "open", cancelled[1] or "", permission="")
    closed = re.fullmatch(r"(?:закрой|закрывай|(?:ты\s+)?можешь\s+закрыть)\s+(.+?)[.!? ]*", value, re.I)
    if closed:
        return Intent("unsupported", "close", closed[1], permission="")
    running = re.fullmatch(r"проверь,?\s+(?:открыт|открыта|работает|запущен|запущена)\s+(?:ли\s+)?(.+?)[.!? ]*", value, re.I)
    if running:
        return Intent("inspect_running", "status", running[1], permission="")
    if re.match(r"(?:открой|открывай|запусти|запускай)\b", value, re.I) and (
            re.search(r"[.!?;]\s*(?:открой|запусти|закрой|удали|выключи)\b", value, re.I)
            or re.search(r"\b(?:и|затем|потом)\s+(?:открой|запусти|закрой|удали|выключи)\b", value, re.I)):
        return Intent("needs_clarification", "action", "", permission="")
    return None


def action_request(text, name="Уайли"):
    """An unresolved whole request needs clarification, never invented execution.

    This is only a fallback after existing tools; it does not select tools.
    """
    value = request_prefix(re.sub(r"^" + re.escape(name) + r"[,!. ]+", "", text.strip(), flags=re.I))
    if any(c in value for c in '\"«»“”\n\r') or re.match(r"(?:как|почему|когда|расскажи|объясни|если|он\s|она\s)\b", value, re.I):
        return False
    verb = r"(?:не\s+(?:надо\s+)?)?(?:открой|открывай|открыть|запусти|запускай|запускать|закрой|закрывай|сделай|уменьши|увеличь|создай|удали|отправь|сохрани|включи|выключи|отмени|проверь|подготовь)\b"
    return bool(re.match(r"(?:(?:ты\s+)?можешь[, ]+|пожалуйста[, ]+|давай[, ]+|а\s+теперь\s+)?" + verb, value, re.I)
                or re.match(r"(?:[\w-]+[,.!]\s*){1,3}" + verb, value, re.I))


def interpret(text, name="Уайли"):
    if not isinstance(text, str) or len(text) > 500 or any(ord(c) < 32 for c in text) or any(c in text for c in '"«»“”'):
        return None
    from .device_audio import request_form
    normalization = {}
    form = request_form(text, name, diagnostics=normalization)
    value = form if normalization.get("applied") else text.strip()
    if re.search(r"\b(?:не|никогда|если|например|расскажи|объясни|почему|как|попросил|попросила|сказал|сказала)\b", value, re.I):
        return None
    value = re.sub(r"^" + re.escape(name) + r"[,! ]+", "", value, flags=re.I)
    value = request_prefix(value)
    value = re.sub(r"^(?:а\s+теперь|теперь|пожалуйста)[, ]+", "", value, flags=re.I)
    value = re.sub(r",?\s+пожалуйста(?=[.!? ]*$)", "", value, flags=re.I)
    value = repair_open_punctuation(value)
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
