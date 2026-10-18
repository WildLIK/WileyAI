"""Suggest corrections for short volume requests; guesses never execute directly."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import time

from pydantic import BaseModel, ConfigDict, Field

from .device_audio import AudioAction, request_text, resolve


TTL = 120
QUESTION_PREFIX = "Похоже, вы просили: «"
QUESTION = QUESTION_PREFIX + "{text}». Громкость пока не изменена. Выполнить? Ответьте «да» или «отмена»."
EXPIRED = "Уточнение громкости устарело. Повторите команду. Громкость не изменена."
RETRY = "Не удалось надёжно разобрать команду громкости. Громкость не изменена. Скажите, например: «прибавь громкость на 10» или «убавь громкость на 10». Распознанный текст можно исправить перед отправкой."


class Pending(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    assistant_id: str = Field(min_length=1, max_length=64)
    created: float
    text: str = Field(min_length=1, max_length=200)
    action: AudioAction


@dataclass
class Reply:
    text: str = ""
    action: AudioAction | None = None


def suggest(text, name="Уайли"):
    """Only a whole short request with a volume noun and nearby imperative qualifies."""
    value = request_text(text, name)
    if not value or re.search(r"\b(?:не|нет|если|например|как|что|почему|зачем)\b|[?;:]", value):
        return None
    words = value.split()
    if not 2 <= len(words) <= 7:
        return None
    verbs = ("прибавь", "убавь", "увеличь", "уменьши")
    scored = sorted(((SequenceMatcher(None, words[0], verb).ratio(), verb) for verb in verbs), reverse=True)
    if scored[0][0] < .6 or not any(SequenceMatcher(None, word, "громкость").ratio() >= .85 for word in words[1:3]):
        return None
    # Opposite directions close in spelling must be clarified with a fresh request.
    if scored[0][0] - scored[1][0] < .12:
        return Reply(RETRY)
    if SequenceMatcher(None, words[1], "громкость").ratio() < .85:
        return Reply(RETRY)
    corrected = scored[0][1] + " громкость" + (" " + " ".join(words[2:]) if len(words) > 2 else "")
    try:
        action = resolve(corrected)
    except ValueError:
        action = None
    if not action or action.action != "change_volume":
        return Reply(RETRY)
    return Reply(QUESTION.format(text=corrected), action)


def remember(store, assistant_id, suggestion):
    state = store.dialogue()
    for key in ("pending_open", "pending", "task_choice"):
        state.pop(key, None)
    # Only the last visible question may own a short reply.
    if isinstance(state.get("calendar"), dict):
        state["calendar"].pop("pending", None)
    state["pending_audio"] = Pending(assistant_id=assistant_id, created=time.time(), text=suggestion.text, action=suggestion.action).model_dump()
    store.save_dialogue(state)


def consume(store, text, name="Уайли"):
    state = store.dialogue()
    raw = state.pop("pending_audio", None)
    value = request_text(text, name)
    positive = value in {"да", "давай", "подтверждаю", "выполни", "да, выполни"}
    negative = value in {"нет", "отмена", "не надо", "отмени", "передумал", "передумала"}
    if raw is None:
        if positive or negative:
            history = store.list("messages", 2)
            if len(history) == 2 and history[0]["role"] == "assistant" and history[0]["content"].startswith(QUESTION_PREFIX) and "Громкость пока не изменена." in history[0]["content"]:
                return Reply(EXPIRED)
        return None
    store.save_dialogue(state)  # Any new message retires the suggestion.
    if not (positive or negative):
        return None
    try:
        pending = Pending.model_validate(raw)
        history = store.list("messages", 2)
        if not 0 <= time.time() - pending.created <= TTL or len(history) != 2 or history[0]["role"] != "assistant" or history[0]["id"] != pending.assistant_id or history[0]["content"] != pending.text or pending.action.action != "change_volume":
            raise ValueError("Предложение устарело")
    except (ValueError, TypeError):
        return Reply(EXPIRED)
    if negative:
        return Reply("Изменение громкости отменено. Громкость не изменена.")
    return Reply(action=pending.action)
