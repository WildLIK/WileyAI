"""Bounded audio corrections; a guess requires one explicit, scoped confirmation."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .device_audio import AudioAction, request_text, resolve, music_help
from .music_intents import request as music_request


TTL = 120
QUESTION_PREFIX = "Похоже, вы просили: «"
QUESTION = QUESTION_PREFIX + "{text}». Громкость пока не изменена. Выполнить? Ответьте «да» или «отмена»."
EXPIRED = "Уточнение команды устарело. Повторите просьбу. Действие не выполнялось."
RETRY = "Не удалось надёжно разобрать команду громкости. Громкость не изменена. Скажите, например: «прибавь громкость на 10» или «убавь громкость на 10». Распознанный текст можно исправить перед отправкой."


class Pending(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    assistant_id: str = Field(min_length=1, max_length=64)
    created: float
    text: str = Field(min_length=1, max_length=200)
    action: AudioAction
    target: Literal["auto", "yandex"] = "auto"
    selected_player: Literal["auto", "yandex"] = "auto"


@dataclass
class Reply:
    text: str = ""
    action: AudioAction | None = None
    target: Literal["auto", "yandex"] = "auto"
    selected_player: Literal["auto", "yandex"] = "auto"


def suggest(text, name="Уайли", *, player="auto"):
    """Only a whole short request with an audio noun and nearby verb qualifies."""
    raw, explicit = music_request(text, name)
    value = request_text(raw, name) if raw is not None else None
    if not value or re.search(r"\b(?:не|нет|если|например|как|что|почему|зачем)\b|[?;:]", value):
        return None
    if music_help(value, name) is not None:
        return None  # A correctly understood request still needs its source workflow.
    target = "yandex" if explicit or player == "yandex" else "auto"
    value = re.sub(r"\bгромкость (?:музыки|плеера)\b", "громкость", value)
    words = value.split()
    if not 2 <= len(words) <= 7:
        return None
    verbs = ("прибавь", "убавь", "увеличь", "уменьши")
    scored = sorted(((SequenceMatcher(None, words[0], verb).ratio(), verb) for verb in verbs), reverse=True)
    if scored[0][0] < .6 or not any(SequenceMatcher(None, word, "громкость").ratio() >= .85 for word in words[1:3]):
        # A short verb plus an exact music noun can propose playback, never
        # execute it. A title, arbitrary filler or multiple clauses cannot.
        if words[-1] not in {"музыку", "песню", "трек", "воспроизведение"}:
            return None
        if len(words) == 2:
            spoken = words[0]
        elif len(words) == 3 and words[0] == "и":
            spoken = "".join(words[:2])
        else:
            return None
        candidates = {"play": ("продолжи", "возобнови", "включи", "играй"), "pause": ("останови", "приостанови")}
        scores = sorted((max(SequenceMatcher(None, spoken, verb).ratio() for verb in verbs), action) for action, verbs in candidates.items())
        if scores[-1][0] < .6 or scores[-1][0] - scores[-2][0] < .1:
            return None
        action = AudioAction(action=scores[-1][1])
        corrected = "продолжи музыку" if action.action == "play" else "поставь музыку на паузу"
        source = "Яндекс Музыка" if target == "yandex" else "активный проигрыватель Windows"
        question = QUESTION_PREFIX + corrected + f"». Плеер: {source}. Команда ещё не выполнялась. Выполнить? Ответьте «да» или «отмена»."
        return Reply(question, action, target, player)
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
    question = QUESTION.format(text=corrected)
    if target == "yandex":
        question = question.replace("Громкость пока", "Плеер: Яндекс Музыка. Громкость пока")
    return Reply(question, action, target, player)


def remember(store, assistant_id, suggestion):
    state = store.dialogue()
    for key in ("pending_open", "pending", "task_choice"):
        state.pop(key, None)
    # Only the last visible question may own a short reply.
    if isinstance(state.get("calendar"), dict):
        state["calendar"].pop("pending", None)
    state["pending_audio"] = Pending(assistant_id=assistant_id, created=time.time(), text=suggestion.text, action=suggestion.action, target=suggestion.target, selected_player=suggestion.selected_player).model_dump()
    store.save_dialogue(state)


def consume(store, text, name="Уайли"):
    state = store.dialogue()
    raw = state.pop("pending_audio", None)
    value = request_text(text, name)
    positive = value in {"да", "давай", "подтверждаю", "выполни", "да выполни"}
    negative = value in {"нет", "отмена", "не надо", "отмени", "передумал", "передумала"}
    if raw is None:
        if positive or negative:
            history = store.list("messages", 2)
            if len(history) == 2 and history[0]["role"] == "assistant" and history[0]["content"].startswith(QUESTION_PREFIX) and any(marker in history[0]["content"] for marker in ("Громкость пока не изменена.", "Команда ещё не выполнялась.")):
                return Reply(EXPIRED)
        return None
    store.save_dialogue(state)  # Any new message retires the suggestion.
    if not (positive or negative):
        return None
    try:
        pending = Pending.model_validate(raw)
        history = store.list("messages", 2)
        if not 0 <= time.time() - pending.created <= TTL or len(history) != 2 or history[0]["role"] != "assistant" or history[0]["id"] != pending.assistant_id or history[0]["content"] != pending.text or pending.action.action not in {"change_volume", "play", "pause"} or pending.selected_player != store.settings().music_player:
            raise ValueError("Предложение устарело")
    except (ValueError, TypeError):
        return Reply(EXPIRED)
    if negative:
        return Reply("Изменение громкости отменено. Громкость не изменена." if pending.action.action == "change_volume" else "Команда плеера отменена. Действие не выполнялось.")
    return Reply(action=pending.action, target=pending.target, selected_player=pending.selected_player)
