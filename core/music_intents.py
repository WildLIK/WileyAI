"""Whole-utterance music commands. Song names are data, never executable code."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .device_audio import percentage, resolve as audio_command, music_help


class MusicAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["status", "play", "pause", "play_pause", "next", "previous", "like", "unlike", "toggle_like", "volume", "change_volume", "search_play"]
    query: str = Field(default="", max_length=200)
    value: int | None = Field(default=None, ge=-100, le=100)

    @model_validator(mode="after")
    def arguments(self):
        if self.action == "search_play":
            if len(self.query.strip()) < 2 or self.value is not None:
                raise ValueError("Назовите исполнителя и песню")
        elif self.query:
            raise ValueError("Это действие не принимает поисковый запрос")
        if self.action in {"volume", "change_volume"}:
            if self.value is None or (self.action == "volume" and self.value < 0):
                raise ValueError("Укажите громкость от 0 до 100")
        elif self.value is not None:
            raise ValueError("Это действие не принимает громкость")
        return self


def resolve(text, *, preferred=False, name="Уайли"):
    if len(text) > 300 or any(ord(c) < 32 for c in text):
        return None
    value = re.sub(r"^" + re.escape(name) + r"[,!]?\s+", "", text.strip(), flags=re.I)
    value = re.sub(r"^пожалуйста[, ]+|,? пожалуйста[.! ]*$", "", value, flags=re.I).strip().rstrip(".! ")
    if re.match(r"^(?:не |как |если |например |напиши |расскажи )", value, re.I) or value.startswith(('"', '«', '“')):
        return None
    explicit = bool(re.search(r"\b(?:яндекс[. ]*музык\w*|yandex\s*music)\b", value, re.I))
    value = re.sub(r"\s+(?:в |на )?яндекс[. ]*музык\w*", "", value, flags=re.I).strip()
    search = re.fullmatch(r"(?:найди(?: и (?:включи|поставь))?|включи|поставь|воспроизведи)\s+(?:мне\s+)?(?:песню|трек|композицию)\s+(.+)", value, re.I)
    if search and (preferred or explicit):
        return MusicAction(action="search_play", query=search[1].strip(' "«»'))
    if not (preferred or explicit):
        return None
    key = value.casefold().replace("ё", "е")
    if key in {"что сейчас играет?", "какая песня играет?"}:
        return MusicAction(action="status")
    fixed = {
        "плей": "play", "play": "play", "пауза": "pause", "pause": "pause",
        "следующая песня": "next", "следующий трек": "next", "предыдущая песня": "previous", "предыдущий трек": "previous",
        "добавь в любимые": "like", "добавь песню в любимые": "like", "добавь в избранное": "like", "лайкни песню": "like",
        "убери из любимых": "unlike", "удали из любимых": "unlike", "убери из избранного": "unlike", "убери лайк": "unlike", "сними лайк": "unlike",
        "лайк": "toggle_like", "нравится": "like", "проверь плеер": "status", "что сейчас играет": "status", "какая песня играет": "status",
    }
    if key in fixed:
        return MusicAction(action=fixed[key])
    volume = re.fullmatch(r"(?:установи |сделай )?громкость(?: плеера| музыки)?(?: на)?\s+(.+)", key)
    if volume:
        try: return MusicAction(action="volume", value=percentage(volume[1]))
        except ValueError: return None
    audio = audio_command(value, name)
    if audio and audio.action in {"play", "pause", "play_pause", "next", "previous", "media_status", "set_volume", "change_volume"}:
        return MusicAction(action={"media_status": "status", "set_volume": "volume"}.get(audio.action, audio.action), value=audio.value)
    if music_help(value, name) is not None:
        return MusicAction(action="play")
    return None


def search_query(value):
    """Only a small spoken-name dictionary; ordinary queries stay intact."""
    value = re.sub(r"\bлинкин\s*парк\b", "Linkin Park", value, flags=re.I)
    return re.sub(r"\bвиз\s+ю\b", "With You", value, flags=re.I)
