"""Typed, audited audio actions shared by the chat, command preview and controls."""
import asyncio
import re
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from anyio import CancelScope

from . import windows_audio, windows_media
from .commands import normalize


class AudioAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["status", "set_volume", "change_volume", "mute", "unmute", "play", "pause", "media_status", "play_pause", "next", "previous", "stop"]
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
LABELS.update(play="Продолжить воспроизведение", pause="Поставить на паузу", media_status="Проверить проигрыватель")
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


INFINITIVES = {"сделать": "сделай", "увеличить": "увеличь", "уменьшить": "уменьши", "прибавить": "прибавь", "убавить": "убавь", "установить": "установи", "включить": "включи", "выключить": "выключи", "продолжить": "продолжи", "возобновить": "возобнови", "остановить": "останови", "приостановить": "приостанови", "снять": "сними", "переключить": "переключи", "найти": "найди", "поставить": "поставь", "воспроизвести": "воспроизведи", "добавить": "добавь", "убрать": "убери"}
ASR_FORMS = {"продолжим": "продолжи", "поставим": "поставь", "убавим": "убавь", "прибавим": "прибавь", "переключим": "переключи", "возобновим": "возобнови", "остановим": "останови", "включим": "включи", "запустим": "запусти", "откроем": "открой"}


def request_form(text, name="Уайли", *, normalize_asr=True, player_context=False, diagnostics=None):
    """Strip request wrappers; repair only closed ASR forms with a supported target.

    Never infer a misspelled verb or rewrite words inside the arguments.
    ``normalize_asr=False`` lets C5 inspect the original action forms safely.
    """
    value = text.strip().rstrip(".! ")
    value = re.sub(r"^" + re.escape(name) + r"[,!]?[ ]+", "", value, flags=re.I)
    from .intent_interpreter import request_prefix
    value = request_prefix(value, extra_verbs=ASR_FORMS)
    value = re.sub(r"^пожалуйста[, ]+|,? пожалуйста$", "", value, flags=re.I).strip()
    invitation = bool(re.match(r"^давай[, ]+", value, re.I))
    value = re.sub(r"^давай[, ]+", "", value, flags=re.I)
    polite = re.fullmatch(r"(?:ты )?можешь[, ]+(?:пожалуйста[, ]+)?(\w+)[, ]+(.+?)\??", value, re.I)
    if polite and polite[1].casefold() in INFINITIVES:
        value = INFINITIVES[polite[1].casefold()] + " " + polite[2].rstrip("? ")
    if not normalize_asr: return value
    # Whole volume phrases only: never reorder words inside a song/app title.
    if not any(c in value for c in '"«»“”„?\n\r'):
        volume = re.fullmatch(r"(?:(?:сделай|сделаем|включи)\s+)?(?:(музыку|звук)\s+)?(погромче|громче|потише|тише)(?:\s+(музыку|звук)|\s+сделай)?", value, re.I)
        if volume and not (volume[1] and volume[3]):
            obj = volume[1] or volume[3]
            if obj and obj.casefold() == "звук": obj = None
            value = "сделай " + ((obj.casefold() + " ") if obj else "") + ("громче" if "громче" in volume[2].casefold() else "тише")
        elif re.fullmatch(r"подкрути\s+(?:звук|громкость)", value, re.I):
            value = "прибавь звук"
        else:
            musical_volume = re.fullmatch(r"(прибавь|убавь|увеличь|уменьши)\s+(?:музыку|музычку|музыкашку)", value, re.I)
            if musical_volume:
                value = "сделай музыку " + ("громче" if musical_volume[1].casefold() in {"прибавь", "увеличь"} else "тише")
    match = re.match(r"^(\w+)(?=$|[\s,.?!])", value)
    verb = match[1].casefold() if match else ""
    if verb not in ASR_FORMS:
        if diagnostics is not None:
            diagnostics.update(applied=False, reason="not_asr_form")
            # Explain refusal without treating a title/report/question as a
            # candidate command, and without retaining the surrounding text.
            if re.match(r'^(?:["«“„]|не\b|если\b|почему\b|как\b|когда\b|я\s+(?:сказал|сказала)\b|песня\s+называется\b)', value, re.I):
                reported = next((word.casefold() for word in re.findall(r"\w+", value) if word.casefold() in ASR_FORMS), None)
                if reported: diagnostics.update(source_verb=reported, normalized_verb=ASR_FORMS[reported], command_candidate=False, reason="non_command_context")
        return value
    detail = {"applied": False, "source_verb": verb, "normalized_verb": ASR_FORMS[verb], "command_candidate": True, "existing_invitation": invitation and verb in {"откроем", "запустим", "включим"}}
    def finish(reason, result=value):
        detail["reason"] = reason
        if diagnostics is not None: diagnostics.update(detail)
        return result
    if any(c in text for c in '"«»“”„\n\r'): return finish("quoted_or_multiline")
    if "?" in value: return finish("question")
    if re.search(r"\b(?:не|никогда|если|сказал|сказала|например|почему|когда)\b", value, re.I): return finish("non_action")
    from .music_intents import compound_request, resolve as music_resolve
    if compound_request(text, name): return finish("compound")
    remainder = value[match.end():]
    tail = re.sub(r"^(?:[,.]\s*|\s+)", "", remainder, count=1).strip()
    had_tail = bool(tail)
    if not tail:
        if verb not in {"продолжим", "возобновим"}: return finish("missing_target")
        if not player_context: return finish("missing_player_context")
        tail = "музыку"
    candidate = ASR_FORMS[verb] + " " + tail
    try:
        supported = resolve(candidate, name, normalize_asr=False)
    except ValueError:
        return finish("invalid_arguments")
    kind = "audio" if supported else ""
    if supported is None:
        music = music_resolve(candidate, preferred=True, name=name, allow_free=player_context)
        if music: kind = "music"
    if not kind and verb in {"откроем", "запустим"}:
        from .app_catalog import canonical_name
        from .commands import opening_target
        target = opening_target(candidate)
        if target: target = re.sub(r"\s+на (?:компьютере|пк|телефоне|смартфоне)$", "", target, flags=re.I)
        if target and (canonical_name(re.sub(r"^(?:приложение|программу)\s+", "", target, flags=re.I)) or target.casefold() in {"браузер", "браузер по умолчанию"}):
            kind = "application"
    if not kind: return finish("unsupported_target")
    detail.update(applied=True, context="selected_player" if not had_tail else kind)
    return finish("supported_command", candidate)


def request_text(text, name="Уайли", *, normalize_asr=True):
    # Only the user's whole utterance is a command. Quotes, negation, compound
    # instructions and text from documents never become executable actions.
    if len(text) > 200 or any(ord(char) < 32 for char in text) or any(char in text for char in '"«»“”'):
        return None
    value = normalize(request_form(text, name, normalize_asr=normalize_asr))
    # Device qualifiers at the end do not change the intent; only the same
    # bounded whole-utterance grammar below can become a command.
    value = re.sub(r"\s+на (?:компьютере|пк)$", "", value)
    value = re.sub(r"[, ]+", " ", value).strip()
    # ASR may insert a preposition between the verb and volume noun. Other
    # fillers, verb changes, negation and compound requests remain unmatched.
    value = re.sub(r"^(\w+) в (громкость|громкости|звук)\b", r"\1 \2", value)
    value = re.sub(r"^(прибавь|убавь|добавь|увеличь|уменьши|включи|выключи|отключи) мне ", r"\1 ", value)
    return value


def resolve(text, name="Уайли", *, normalize_asr=True):
    value = request_text(text, name, normalize_asr=normalize_asr)
    if value is None:
        return None
    fixed = {
        "какая громкость": "status", "какая громкость?": "status", "покажи громкость": "status", "текущая громкость": "status",
        "выключи звук": "mute", "отключи звук": "mute", "убери звук": "mute", "включи звук": "unmute", "верни звук": "unmute",
        "следующий трек": "next", "переключи трек": "next", "включи следующий трек": "next", "предыдущий трек": "previous", "включи предыдущий трек": "previous",
        "переключи воспроизведение": "play_pause", "музыка пауза": "play_pause", "музыка продолжить": "play_pause",
        "останови музыку": "stop", "останови проигрыватель": "stop",
        "поставь музыку на паузу": "pause", "поставь на паузу": "pause", "поставь плеер на паузу": "pause", "приостанови музыку": "pause", "пауза": "pause",
        "продолжи музыку": "play", "продолжи воспроизведение": "play", "возобнови музыку": "play", "возобнови воспроизведение": "play", "сними с паузы": "play", "воспроизведи музыку": "play", "играй музыку": "play",
        "включи песню": "play", "включи трек": "play", "продолжи песню": "play", "продолжи трек": "play", "сними песню с паузы": "play", "сними музыку с паузы": "play", "сними трек с паузы": "play",
        "где музыка": "media_status", "где музыка?": "media_status", "проверь проигрыватель": "media_status", "проверь музыку": "media_status", "музыка играет?": "media_status",
        "првоерь проигрыватель": "media_status", "проверь плеер": "media_status",
    }
    if value in fixed:
        return AudioAction(action=fixed[value])
    if value in {"сделай громче", "громче", "сделай музыку громче", "увеличь громкость", "прибавь громкость", "прибавь громкости", "добавь громкости", "добавь громкость", "прибавь звук", "прибавь громче"}:
        return AudioAction(action="change_volume", value=10)
    if value in {"сделай тише", "тише", "сделай потише", "сделай музыку тише", "сделай музыку потише", "потише", "уменьши громкость", "убавь громкость", "убавь громкости", "убавь звук"}:
        return AudioAction(action="change_volume", value=-10)
    match = re.fullmatch(r"(?:установи |выстави |поставь |сделай )?громкость(?: на)? ([\w %]+)", value)
    if match:
        return AudioAction(action="set_volume", value=percentage(match[1]))
    match = re.fullmatch(r"(?:(увеличь|уменьши|прибавь|убавь|добавь) (?:громкость|громкости|звук)|(сделай громче|сделай тише|сделай потише|громче|тише|потише)) на ([\w %]+)", value)
    if match:
        return AudioAction(action="change_volume", value=percentage(match[3]) * (-1 if match[1] in {"уменьши", "убавь"} or "тише" in (match[2] or "") else 1))
    return None


def music_help(text, name="Уайли"):
    """A request to start unspecified music cannot prove a player is running."""
    value = request_text(text, name)
    if value and re.fullmatch(r"(?:давай )?(?:(?:включи|включим|поставь|поставим|запусти|запустим|воспроизведи)|(?:ты )?можешь (?:включить|поставить|запустить)) (?:мне )?(?:музыку|какую-нибудь музыку)\??", value):
        return "Для запуска музыки нужен источник. Можно сказать «открой мне YouTube». Если проигрыватель уже открыт, доступна команда «переключи воспроизведение». Сейчас команда воспроизведения не отправлялась."
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

    def execute(self, command: AudioAction, dry_run=False, request_id=None):
        target = command.action + (f":{command.value}" if command.value is not None else "")
        try:
            with self.lock:
                if not self.store.settings().allow_audio_control:
                    raise ValueError("Управление звуком отключено. Включите доступ в разделе «Команды».")
                if request_id:
                    self.store.audit("command.permission", target, "allowed", {"request_id": request_id, "tool": "audio"})
                    self.store.audit("command.tool", target, "called", {"request_id": request_id, "tool": "audio"})
                if dry_run:
                    text = f"Проверено: {LABELS[command.action]}" + (f" ({command.value})" if command.value is not None else "") + ". Действие не выполнялось."
                    result = {"text": text}
                elif command.action in {"play", "pause", "media_status"}:
                    media = windows_media.perform("read" if command.action == "media_status" else command.action)
                    if command.action != "media_status": media["action"] = command.action
                    result = {"text": windows_media.describe(media), "media": media}
                elif command.action in windows_audio.MEDIA_KEYS:
                    # One player call; an unavailable session never triggers a global media key.
                    try:
                        media = windows_media.perform(command.action)
                    except (windows_media.Unavailable, OSError):
                        media = {"available": False}
                    if media.get("available"):
                        media["action"] = command.action
                        result = {"text": windows_media.describe(media), "media": media}
                    else:
                        result = {"text": "Доступная медиасессия не найдена. Команда не отправлена.", "media": {"available": False, "confirmed": False}}
                else:
                    with windows_audio.endpoint() as device:
                        before = device.read()
                        def verified_endpoint(state):
                            return not state.get("endpoint") or state.get("default_endpoint", state["endpoint"]) == state["endpoint"]
                        if not verified_endpoint(before): raise ValueError("Устройство вывода Windows изменилось до команды. Повторите команду для нового устройства.")
                        expected = None
                        if command.action == "set_volume":
                            expected = command.value
                            device.set_volume(command.value)
                        elif command.action == "change_volume":
                            expected = max(0, min(100, before["volume"] + command.value))
                            device.set_volume(expected)
                        elif command.action in {"mute", "unmute"}:
                            device.set_mute(command.action == "mute")
                        state = device.read()
                        diagnostics = {"scope":"windows_master", "endpoint":before.get("endpoint"), "before":before, "after":state, "expected_volume":expected}
                        def failed(reason, message):
                            self.store.audit("device.audio.readback", target, "unconfirmed", {**diagnostics, "reason":reason, **({"request_id":request_id} if request_id else {})})
                            raise ValueError(message)
                        if not verified_endpoint(state) or before.get("endpoint") != state.get("endpoint"):
                            failed("endpoint_changed", "Устройство вывода Windows изменилось во время команды. Результат для нового устройства не подтверждён; повтор не отправлялся.")
                        if expected is not None and abs(state["volume"] - expected) > 1:
                            failed("volume_mismatch", f"Windows не подтвердила изменение громкости. Прочитано: {state['volume']}%.")
                        if expected is not None and ((expected > before["volume"] and state["volume"] <= before["volume"]) or (expected < before["volume"] and state["volume"] >= before["volume"])):
                            failed("volume_unchanged", f"Громкость Windows не изменилась: {state['volume']}%. Команда повторно не отправлялась.")
                        if command.action in {"mute", "unmute"} and state["muted"] != (command.action == "mute"):
                            failed("mute_mismatch", "Windows не подтвердила изменение состояния звука.")
                    suffix = " Уровень 0%: звук не слышен." if state["volume"] == 0 else " Звук выключен (mute)." if state["muted"] else " Mute выключен."
                    if state["volume"] == 0 and state["muted"]: suffix += " Mute включён."
                    result = {"text": f"Громкость Windows: {state['volume']}%." + suffix, **state, "before":before, "confirmed":True,
                              "scope":"windows_master", "diagnostics":{**diagnostics, "reason":"readback_confirmed"}}
        except Exception as error:
            self.store.audit("device.audio", target, "error", {"text": str(error), **({"request_id": request_id} if request_id else {})})
            raise
        self.store.audit("device.audio", target, "preview" if dry_run else "confirmed" if result.get("media", {}).get("confirmed") else "unconfirmed" if command.action in {"play", "pause"} else "ok", {**result, **({"request_id": request_id} if request_id else {})})
        return result


async def run_action(tools, command, progress, outcomes=None, request_id=None):
    """A dispatched Windows operation finishes before another chat is admitted."""
    operation = asyncio.create_task(asyncio.to_thread(tools.execute, command, **({"request_id": request_id} if request_id else {})))
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
    if outcomes is not None:
        outcomes.append({"action": command.action, "result": result})
    return result["text"]
