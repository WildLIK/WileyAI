"""Whole-utterance music commands. Song names are data, never executable code."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .device_audio import percentage, resolve as audio_command, music_help, request_form, ASR_FORMS


MUSIC_OBJECT = r"(?:песню|песня|трек|композицию|композиция)"


class SongSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^\d{1,30}$")
    title: str = Field(min_length=1, max_length=300)
    artists: str = Field(max_length=300)
    search_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    retrieval_query: str = Field(default="", max_length=200)


class MusicAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["status", "play", "pause", "play_pause", "next", "previous", "like", "unlike", "toggle_like", "volume", "change_volume", "wave", "search", "select", "search_play"]
    query: str = Field(default="", max_length=200)
    value: int | None = Field(default=None, ge=-100, le=100)
    selection: SongSelection | None = None

    @model_validator(mode="after")
    def arguments(self):
        if self.action in {"search", "select", "search_play"}:
            if len(self.query.strip()) < 2 or self.value is not None:
                raise ValueError("Назовите исполнителя и песню")
        elif self.query:
            raise ValueError("Это действие не принимает поисковый запрос")
        if (self.action == "select") != (self.selection is not None):
            raise ValueError("Выберите песню из актуальных результатов поиска")
        if self.action in {"volume", "change_volume"}:
            if self.value is None or (self.action == "volume" and self.value < 0):
                raise ValueError("Укажите громкость от 0 до 100")
        elif self.value is not None:
            raise ValueError("Это действие не принимает громкость")
        return self


def request(text, name="Уайли", *, normalize_asr=True, player_context=False):
    """Extract a player qualifier at the edges, preserving song names as data."""
    if len(text) > 300 or any(ord(c) < 32 for c in text):
        return None, False
    value = request_form(text, name, normalize_asr=normalize_asr, player_context=player_context)
    # "Да" alone belongs to Pending. With a complete musical command it is
    # only an agreement prefix; downstream whole-utterance guards still apply.
    value = re.sub(r"^да[, ]+(?=(?:не\s+)?(?:включи|включай|включим|продолжи|поставь|следующую|следующая|следующий|переключи|перезапусти|подключи|переподключи)\b)", "", value, count=1, flags=re.I)
    player = r"(?:яндекс[. ]*музык(?:а|е|у|и|ой|ы)?|yandex\s*music)"
    value, prefix = re.subn(r"^(?:(?:в|на) )?" + player + r"[, ]+", "", value, count=1, flags=re.I)
    # A qualifier immediately after the command verb is metadata. Do not
    # remove the same words from the middle of an artist/track title.
    verbs = r"(?:включи|поставь|запусти|воспроизведи|найди|найти|поищи|включим|поставим|запустим)"
    value, middle = re.subn(r"^(" + verbs + r")\s+(?:в|на)\s+" + player + r"[, ]+", r"\1 ", value, count=1, flags=re.I)
    prefix = prefix or middle
    value = request_form(value, name, normalize_asr=normalize_asr, player_context=player_context or bool(prefix))
    # A song called "Яндекс Музыка" is a query, not a player qualifier. Only
    # a preposition or comma at the end explicitly selects the application.
    value, suffix = re.subn(r"(?:\s+(?:в|на)\s+|,\s*)" + player + r"$", "", value, count=1, flags=re.I)
    return request_form(value, name, normalize_asr=normalize_asr, player_context=player_context or bool(prefix or suffix)), bool(prefix or suffix)


def simple_transport(value):
    """Bounded whole requests, including common ASR case/infinitive variants."""
    value = re.sub(r"^(?:ты )?можешь[, ]+(?:пожалуйста[, ]+)?(?=(?:запустить|открыть)\s)", "", value, flags=re.I).rstrip("? ")
    if re.fullmatch(r"(?:запусти|запустить|включи|включить|открой|открыть|воспроизведи|воспроизвести)\s+(?:мою волну|моя волна)", value, re.I):
        return "wave"
    if re.fullmatch(r"(?:запусти|запустить|включи|включить|воспроизведи|воспроизвести)\s+(?:(?:мою|моя)\s+)?музык[ау]", value, re.I):
        return "play"
    return None


def colloquial_transport(value):
    """Small direction/status grammars, requiring music context at the caller."""
    if re.fullmatch(r"(?:что\s+(?:там\s+)?(?:сейчас\s+)?играет(?:-то)?|какая\s+песня)\??", value, re.I): return "status"
    if re.fullmatch(r"(?:крутани\s+)?дальше", value, re.I): return "next"
    direction = re.fullmatch(r"(?:(?:включи|включим|поставь|поставим|верни|переключи|переключим)(?:\s+на)?\s+)?(следующ(?:ую|ая|ий)|предыдущ(?:ую|ая|ий)|предшествующ(?:ую|ая|ий)|прошл(?:ую|ая|ый))(?:\s+" + MUSIC_OBJECT + r")?", value, re.I)
    if direction: return "next" if direction[1].casefold().startswith("следующ") else "previous"
    return None


def free_query(value, *, music_context=False, explicit=False, application_names=()):
    """Extract opaque search data only in music context, with catalog vetoes.

    This does not rank results or choose a track. Existing adapter policy does.
    """
    if not (music_context or explicit) or "?" in value: return None
    match = re.fullmatch(r"(включи|поставь|запусти|воспроизведи|найди|найти|поищи)\s+(.+)", value, re.I)
    if not match: return None
    verb, query = match[1].casefold(), match[2].strip()
    if verb in {"найди", "найти", "поищи"} and not (explicit or music_context): return None
    # Request slots only, before quote removal. Quoted words and words inside
    # the actual title remain data; there is no global filler-word replacement.
    query = re.sub(r"^мне\s+", "", query, count=1, flags=re.I)
    if verb in {"найди", "найти", "поищи"}:
        query = re.sub(r"^у\s+меня\s+", "", query, count=1, flags=re.I)
    quoted = bool(re.fullmatch(r'"[^"\n]+"|«[^»\n]+»|“[^”\n]+”', query))
    query = query.strip(' "«»“”')
    if len(query) < 2 or len(query) > 200: return None
    key = query.casefold().replace("ё", "е")
    # "Включи/запусти X" with a single unknown name also names apps/devices.
    # A player qualifier or an explicitly musical verb resolves that ambiguity.
    if verb in {"включи", "запусти"} and len(query.split()) == 1 and not explicit: return None
    if re.match(r"(?:ее|его|это|эту|этот|найденн\w*|перв\w*|втор\w*|треть\w*|следующ\w*|предыдущ\w*|песню|трек|композицию|музыку|что-нибудь|что-то)\b", key): return None
    if re.match(r"(?:и|ту|тот|та|те|такую|такой|быстрее|побыстрее|медленнее|помедленнее)\b", key): return None
    if not quoted and re.search(r"\b(?:видео|ролик\w*|стать\w*|информаци\w*|картинк\w*|рисун(?:ок|к\w*)|изображени\w*|фотограф\w*)\b", key): return None
    # Device/system/app nouns are not inferred to be artists, even with a
    # preferred player. Known installed/user names veto the complete query.
    if not quoted and re.search(r"\b(?:bluetooth|блютуз|wi[- ]?fi|вай[- ]?фай|свет\w*|ламп\w*|телевизор\w*|экран\w*|монитор\w*|микрофон\w*|камер\w*|интернет|звук|громкость|режим\w*|приложени\w*|программ\w*|редактор\w*|браузер\w*|файл\w*|папк\w*|документ\w*|сайт\w*)\b", key): return None
    if re.search(r"(?:https?://|www\.|[a-z]:[\\/]|\.exe\b|\b(?:на компьютере|на пк|на телефоне|на смартфоне)\b)", key): return None
    from .app_catalog import canonical_name, name_key
    if canonical_name(query) or any(name_key(query) == name_key(name) for name in application_names): return None
    if key in {"на паузу", "паузу", "мою волну", "моя волна", "погромче", "потише", "дальше"}: return None
    return MusicAction(action="search" if verb in {"найди", "найти", "поищи"} else "search_play", query=query)


def connection_request(text, name="Уайли", *, contextual=False):
    """Only explicit Yandex management or a fresh, unambiguous topic."""
    value, explicit = request(text, name, normalize_asr=False)
    if value is None or any(c in value for c in '"«»“”\n\r'): return None
    player = r"(?:яндекс[. ]*музык(?:а|е|у|и|ой|ы)?|yandex\s*music)"
    if re.fullmatch(r"перезапусти\s+" + player, value, re.I): return "restart"
    if re.fullmatch(r"(?:подключи|переподключи)\s+" + player, value, re.I): return "connect"
    if re.fullmatch(r"проверь\s+(?:(?:подключение|соединение)\s+(?:(?:к|с)\s+)?)?" + player, value, re.I): return "check"
    if re.fullmatch(r"(?:проверь\s+(?:подключение|соединение)|что\s+случилось\s+с\s+(?:подключением|соединением)\??)", value, re.I):
        return "check" if contextual or explicit else "clarify"
    return None


def clarification(text, name="Уайли", *, music_context=False, application_names=()):
    """Non-executable ambiguity, shared by chat and command preview."""
    value, explicit = request(text, name)
    if value is None: return None
    if re.fullmatch(r"(?:уйми\s+музыку|тишину|музыку\s+(?:совсем\s+)?убери)", value, re.I):
        return "Поставить музыку на паузу или выключить звук? Скажите «поставь музыку на паузу» или «выключи звук». Пока ничего не менялось."
    if re.fullmatch(r"сделай\s+(?:нормальную|обычную|среднюю)\s+громкость", value, re.I):
        return "Какую громкость установить? Назовите уровень от 0 до 100 и источник: Windows или плеер. Пока ничего не менялось."
    if colloquial_transport(value) and not (music_context or explicit or re.search(r"\b" + MUSIC_OBJECT + r"\b", value, re.I)):
        return "Укажите музыкальный источник: выберите плеер или назовите его в команде. Пока ничего не менялось."
    bare = re.fullmatch(r"(?:включи|запусти)\s+(\S+)", value, re.I)
    if bare and not explicit and music_context and free_query(value, explicit=True, application_names=application_names):
        return "Это исполнитель, песня или приложение? Для музыки скажите «поставь песню …» или укажите Яндекс Музыку. Пока ничего не запускалось."
    return None


def compound_request(text, name="Уайли"):
    """Reject independent action tails before any song/player extraction.

    Like the opening-command guards, use a closed verb list, not every "и".
    Quoted titles are data; "найди и включи [песню] X" is one existing operation.
    This detects ambiguity only and never splits or executes a sequence.
    """
    value, _ = request(text, name, normalize_asr=False)
    if value is None: return False
    value = re.sub(r'"[^"\n]*"|«[^»\n]*»|“[^”\n]*”', " ", value)
    if re.match(r"(?:как|почему|когда|зачем|расскажи|объясни|если|он|она|например)\b", value, re.I): return False
    first = r"(?:не\s+(?:надо\s+)?)?(?:включи|включай|включить|запусти|запустить|поставь|поставить|найди|найти|поищи|воспроизведи|воспроизвести|продолжи|продолжить|возобнови|возобновить|останови|остановить|приостанови|приостановить|переключи|сними|пауза|сделай|убавь|прибавь|уменьши|увеличь|громкость)\b"
    asr_verbs = "(?:" + "|".join(ASR_FORMS) + ")"
    colloquial_first = r"(?:не\s+)?(?:подкрути|крутани|верни|сделаем|уйми|тишину|музыку|погромче|потише|громче|тише|дальше|следующую|предыдущую|перезапусти|подключи|переподключи)\b"
    mixed_open = re.match(r"(?:открой|открыть)\b", value, re.I) and re.search(r"\b(?:музык\w*|песн\w*|трек\w*|композиц\w*|плеер\w*|звук\w*|громк\w*|аудио|колонк\w*)\b", value, re.I)
    if not re.match(first, value, re.I) and not re.match(colloquial_first, value, re.I) and not re.match(r"(?:не\s+)?" + asr_verbs + r"\b", value, re.I) and not re.match(r"подбери\b", value, re.I) and not mixed_open and not re.match(r"(?:открой|открыть)\s+(?:мою волну|моя волна)\b", value, re.I): return False
    verbs = r"(?:открой|открывай|открыть|запусти|запустить|включи|включить|выключи|выключить|удали|удалить|закрой|закрыть|сделай|сделать|отправь|отправить|поставь|поставить|найди|найти|поищи|останови|остановить|приостанови|приостановить|переключи|переключить|продолжи|продолжить|возобнови|возобновить|убавь|прибавь|уменьши|увеличь|сними|воспроизведи|воспроизвести)"
    # Future forms here only reject a secondary action; they never normalize
    # or authorize new send/delete/close operations.
    rejected_future_tail = r"(?:отправим|удалим|закроем|выключим|перезапусти|подключи|переподключи)"
    tail = r"(?:\b(?:и|а|но|затем|потом|после)\b|[,;.!?])\s*(?:(?:а|но|затем|потом|теперь|давай|ещ[её])\s+){0,3}(?:не\s+)?(?:" + verbs + "|" + asr_verbs + "|" + rejected_future_tail + r"|подбери|приглуши|подкрути|крутани|верни|уйми|сделаем|дальше|следующую|предыдущую|громкость|погромче|потише|тишину)\b"
    for match in re.finditer(tail, value, re.I):
        # A single ASR separator after a volume verb is not a second action.
        if re.fullmatch(r"(?:убавь|прибавь|увеличь|уменьши|установи|сделай|поставь|убавим|прибавим|поставим)", value[:match.start()], re.I) and re.match(r"[,.:]\s*громкость\b", match[0], re.I):
            continue
        if re.fullmatch(r"(?:найди|найти|поищи)\s*", value[:match.start()], re.I) and re.match(r"и\s+(?:включи|включить|поставь|поставить)\b", match[0], re.I):
            continue
        return True
    # An omitted verb still names a distinct transport action, not a song title.
    return bool(re.search(r"\b(?:потом|затем)\s+(?:следующую|следующий|предыдущую|предыдущий)\b", value, re.I))


def resolve(text, *, preferred=False, name="Уайли", application_names=(), allow_free=True):
    value, explicit = request(text, name, player_context=preferred)
    if value is None:
        return None
    if compound_request(text, name): return None
    if re.match(r"^(?:не |как |если |например |напиши |расскажи )", value, re.I) or value.startswith(('"', '«', '“')):
        return None
    transport = simple_transport(value)
    if transport and (preferred or explicit): return MusicAction(action=transport)
    if not explicit and not re.search(r"музык|плеер|проигрывател", value, re.I):
        direct = audio_command(value, name)
        if direct and direct.action in {"status", "set_volume", "change_volume", "mute", "unmute"}:
            return None  # A preferred player never captures Windows master volume.
    search = re.fullmatch(r"(?:найди(?: и (?:включи|поставь))?|найти(?: и (?:включить|поставить))?|поищи|включи|поставь|воспроизведи)\s+(?:мне\s+)?(?:песню|трек|композицию)\s+(.+)", value, re.I)
    if search and (preferred or explicit):
        return MusicAction(action="search_play", query=search[1].strip(' "«»'))
    if not (preferred or explicit):
        return None
    key = value.casefold().replace("ё", "е")
    if key in {"что сейчас играет?", "какая песня играет?"}:
        return MusicAction(action="status")
    fixed = {
        "включи мою волну": "wave", "запусти мою волну": "wave",
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
    audio = audio_command(re.sub(r"\bгромкость (?:музыки|плеера)\b", "громкость", value, flags=re.I), name)
    if audio and audio.action in {"play", "pause", "stop", "play_pause", "next", "previous", "media_status", "set_volume", "change_volume"}:
        return MusicAction(action={"media_status": "status", "set_volume": "volume", "stop": "pause"}.get(audio.action, audio.action), value=audio.value)
    if music_help(value, name) is not None:
        return MusicAction(action="play")
    direction = colloquial_transport(value)
    if direction: return MusicAction(action=direction)
    return free_query(value, music_context=preferred, explicit=explicit, application_names=application_names) if allow_free or explicit else None


def followup(text, history, *, preferred=False, name="Уайли", application_names=()):
    """A pronoun can only reuse the immediately preceding user's song query."""
    value, explicit = request(text, name)
    if value is None or not re.fullmatch(r"(?:так[, ]+)?(?:включи|запусти|поставь) (?:ее|её|эту песню|этот трек)", value, re.I):
        return None
    if len(history) != 2 or history[0]["role"] != "user" or history[1]["role"] != "assistant":
        return None
    previous = resolve(history[0]["content"], preferred=preferred or explicit, name=name, application_names=application_names)
    # Model-produced titles or claims never supply the query or select a player.
    return previous if previous and previous.action == "search_play" else None


def search_query(value):
    """Only a small spoken-name dictionary; ordinary queries stay intact."""
    value = re.sub(r"\bлинкин\s*парк\b", "Linkin Park", value, flags=re.I)
    value = re.sub(r"\s+группы\s+", " ", value, flags=re.I)
    return re.sub(r"\bвиз\s+ю\b", "With You", value, flags=re.I)
