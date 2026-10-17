"""Typed, audited audio actions shared by the chat, command preview and controls."""
import asyncio
import re
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from anyio import CancelScope

from . import windows_audio
from .commands import normalize


class AudioAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["status", "set_volume", "change_volume", "mute", "unmute", "play_pause", "next", "previous", "stop"]
    value: int | None = Field(default=None, ge=-100, le=100)

    @model_validator(mode="after")
    def arguments(self):
        if self.action in {"set_volume", "change_volume"}:
            if self.value is None or (self.action == "set_volume" and self.value < 0):
                raise ValueError("Укажите громкость от 0 до 100 или изменение от −100 до 100")
        elif self.value is not None:
            raise ValueError("Это действие не принимает уровень громкости")
        return self


LABELS = {"status": "Текущая громкость", "set_volume": "Установить громкость", "change_volume": "Изменить громкость", "mute": "Выключить звук", "unmute": "Включить звук", "play_pause": "Воспроизведение / пауза", "next": "Следующий трек", "previous": "Предыдущий трек", "stop": "Остановить проигрыватель"}
UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100}


def percentage(text):
    text = re.sub(r"\s*(?:%|процент(?:а|ов)?)$", "", text).strip()
    if text.isdigit():
        value = int(text)
    else:
        parts = text.split()
        if text in UNITS:
            value = UNITS.index(text)
        elif len(parts) == 1 and parts[0] in TENS:
            value = TENS[parts[0]]
        elif len(parts) == 2 and parts[0] in TENS and parts[0] != "сто" and parts[1] in UNITS[1:10]:
            value = TENS[parts[0]] + UNITS.index(parts[1])
        else:
            raise ValueError("Укажите громкость числом от 0 до 100, например: «громкость 35 процентов»")
    if not 0 <= value <= 100:
        raise ValueError("Громкость должна быть от 0 до 100 процентов")
    return value


def resolve(text, name="Уайли"):
    # Only the user's whole utterance is a command. Quotes, negation, compound
    # instructions and text from documents never become executable actions.
    if len(text) > 200 or any(ord(char) < 32 for char in text) or any(char in text for char in '"«»“”'):
        return None
    value = normalize(text)
    value = re.sub(r"^" + re.escape(normalize(name)) + r"[,!]?(?:\s+)", "", value)
    value = re.sub(r"^пожалуйста[, ]+|,? пожалуйста$", "", value)
    # A direct, polite request remains executable; ordinary questions about how
    # audio works do not match. Keep the allowed imperative vocabulary bounded.
    polite = re.fullmatch(r"(?:ты )?можешь (?:пожалуйста )?((?:сделать (?:громче|тише|потише)|(?:увеличить|уменьшить|установить) громкость|(?:включить|выключить) звук)(?: [\w %]+)?)\??", value)
    if polite:
        value = polite[1]
        for source, target in (("сделать", "сделай"), ("увеличить", "увеличь"), ("уменьшить", "уменьши"), ("установить", "установи"), ("включить", "включи"), ("выключить", "выключи")):
            if value.startswith(source + " "):
                value = target + value[len(source):]
                break
    fixed = {
        "какая громкость": "status", "какая громкость?": "status", "покажи громкость": "status", "текущая громкость": "status",
        "выключи звук": "mute", "отключи звук": "mute", "убери звук": "mute", "включи звук": "unmute", "верни звук": "unmute",
        "следующий трек": "next", "переключи трек": "next", "включи следующий трек": "next", "предыдущий трек": "previous", "включи предыдущий трек": "previous",
        "переключи воспроизведение": "play_pause", "музыка пауза": "play_pause", "музыка продолжить": "play_pause",
        "останови музыку": "stop", "останови проигрыватель": "stop",
    }
    if value in fixed:
        return AudioAction(action=fixed[value])
    if value in {"сделай громче", "громче", "увеличь громкость", "прибавь громкость", "прибавь звук"}:
        return AudioAction(action="change_volume", value=10)
    if value in {"сделай тише", "тише", "сделай потише", "потише", "уменьши громкость", "убавь громкость", "убавь звук"}:
        return AudioAction(action="change_volume", value=-10)
    match = re.fullmatch(r"(?:установи |выстави |поставь |сделай )?громкость(?: на)? ([\w %]+)", value)
    if match:
        return AudioAction(action="set_volume", value=percentage(match[1]))
    match = re.fullmatch(r"(?:(увеличь|уменьши) громкость|(сделай громче|сделай тише|громче|тише)) на ([\w %]+)", value)
    if match:
        return AudioAction(action="change_volume", value=percentage(match[3]) * (-1 if match[1] == "уменьши" or "тише" in (match[2] or "") else 1))
    return None


class AudioTools:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def catalog(self):
        return [{"id": "windows.audio." + action, "kind": "audio", "name": label, "scope": "device.audio", "enabled": self.store.settings().allow_audio_control} for action, label in LABELS.items()]

    def status(self):
        try:
            with self.lock, windows_audio.endpoint() as device:
                return {"available": True, "enabled": self.store.settings().allow_audio_control, **device.read()}
        except (ValueError, OSError) as error:
            return {"available": False, "enabled": self.store.settings().allow_audio_control, "error": str(error)}

    def execute(self, command: AudioAction, dry_run=False):
        target = command.action + (f":{command.value}" if command.value is not None else "")
        try:
            with self.lock:
                if not self.store.settings().allow_audio_control:
                    raise ValueError("Управление звуком отключено. Включите доступ в разделе «Команды».")
                if dry_run:
                    text = f"Проверено: {LABELS[command.action]}" + (f" ({command.value})" if command.value is not None else "") + ". Действие не выполнялось."
                    result = {"text": text}
                elif command.action in windows_audio.MEDIA_KEYS:
                    windows_audio.send_media(command.action)
                    result = {"text": f"Windows получила медиаклавишу «{LABELS[command.action]}». Результат зависит от активного проигрывателя."}
                else:
                    with windows_audio.endpoint() as device:
                        if command.action == "set_volume":
                            device.set_volume(command.value)
                        elif command.action == "change_volume":
                            device.set_volume(max(0, min(100, device.read()["volume"] + command.value)))
                        elif command.action in {"mute", "unmute"}:
                            device.set_mute(command.action == "mute")
                        state = device.read()
                    suffix = " Звук выключен." if state["muted"] else " Звук включён."
                    result = {"text": f"Громкость Windows: {state['volume']}%." + suffix, **state}
        except Exception:
            self.store.audit("device.audio", target, "error")
            raise
        self.store.audit("device.audio", target, "preview" if dry_run else "ok")
        return result


async def run_action(tools, command, progress):
    """A dispatched Windows operation finishes before another chat is admitted."""
    operation = asyncio.create_task(asyncio.to_thread(tools.execute, command))
    try:
        result = await asyncio.shield(operation)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            try:
                progress.append((await operation)["text"])
            except Exception as error:
                progress.append(f"Команда звука не выполнена: {error}")
        raise
    progress.append(result["text"])
    return result["text"]
