"""One policy for media targeting; Windows master volume is a separate scope."""
from dataclasses import dataclass, asdict
import os
from pathlib import Path
import re
import threading
import time
import asyncio
from anyio import CancelScope

from . import audio_sessions, windows_media, commands
from .device_audio import resolve as audio_command, request_form, music_help
from .music_intents import MUSIC_OBJECT, MusicAction, request as yandex_request, simple_transport, compound_request, colloquial_transport, free_query, connection_request, resolve as resolve_music
from .app_catalog import canonical_name


@dataclass(frozen=True)
class MediaRequest:
    action: str
    scope: str = "player"
    target: str = ""
    value: int | None = None
    query: str = ""
    selection: dict | None = None


def parse(text, name="Уайли", *, music_context=False, application_names=(), prefer_yandex=False, connection_context=False):
    if len(text) > 300 or any(ord(c) < 32 for c in text):
        return None
    if compound_request(text, name): return None
    connection = connection_request(text, name, contextual=connection_context)
    if connection: return MediaRequest(connection, "connection", "" if connection == "clarify" else "Яндекс Музыка")
    value = request_form(text, name)
    if re.match(r"(?:не|как|если|расскажи|объясни|он|она)\b", value, re.I) or value.startswith(('"', '«', '“')): return None
    value = re.sub(r"\s+на (?:компьютере|пк)$", "", value, flags=re.I)
    value, named_yandex = yandex_request(value, name)
    target = "Яндекс Музыка" if named_yandex else ""
    if re.match(r"(?:найди|найти|поищи)\s+и\s+(?:включи|включить|поставь|поставить)\b", value, re.I):
        atomic = resolve_music(value, preferred=True, name=name, application_names=application_names)
        if atomic and atomic.action == "search_play": return MediaRequest("search_play", "song", target, query=atomic.query)
    transport = simple_transport(value)
    if transport: return MediaRequest(transport, "song" if transport == "wave" else "player", target)
    direction = colloquial_transport(value)
    if direction and (music_context or named_yandex or re.search(r"\b" + MUSIC_OBJECT + r"\b", value, re.I)):
        # Preserve the existing special status route when that integration is
        # the chosen source. A specifically selected SMTC player stays here.
        if direction == "status" and (prefer_yandex or named_yandex): return None
        return MediaRequest("read" if direction == "status" else direction, target=target)
    search = re.fullmatch(r"(?:найди|найти|поищи)\s+(?:мне\s+)?(?:песню|трек|композицию|музыку группы)\s+(.+)", value, re.I)
    if search: return MediaRequest("search", "song", target, query=search[1].strip(' "«»'))
    search = re.fullmatch(r"(?:найди|найти|поищи)\s+(.+\s+группы\s+.+)", value, re.I)
    if search: return MediaRequest("search", "song", target, query=search[1].strip(' "«»'))
    if re.fullmatch(r"(?:включи|запусти)\s+(?:мою\s+волну|найденную(?: песню| композицию)?)", value, re.I):
        return MediaRequest("wave" if "волну" in value.casefold() else "found", "song", target)
    if re.fullmatch(r"сделай\s+(?:ее|её|его)\s+(?:потише|тише)", value, re.I):
        return MediaRequest("change_volume", "player", target, -10)
    # Parse complete numeric/transport forms before interpreting "на" as a
    # player qualifier ("на десять", "на паузу" are not player names).
    if not re.match(r"(?:запусти|включи|поставь|воспроизведи)\s+(?:песню|трек|композицию)\b", value, re.I):
        try: direct = audio_command(re.sub(r"\bгромкость (?:музыки|плеера|проигрывателя)\b", "громкость", value, flags=re.I), name)
        except ValueError: direct = None
        if direct:
            if direct.action in {"status", "set_volume", "change_volume", "mute", "unmute"}:
                return MediaRequest(direct.action, "player" if target or re.search(r"музык|плеер|проигрывател", value, re.I) else "system", target, direct.value)
            if direct.action in {"play", "pause", "play_pause", "next", "previous", "stop", "media_status"}:
                return MediaRequest("read" if direct.action == "media_status" else direct.action, target=target)
    if music_help(value, name) is not None: return MediaRequest("play", target=target)
    suffix = re.fullmatch(r"(.+)\s+(?:в|на)\s+(.+?)\??", value, re.I)
    if suffix and (not music_context or canonical_name(suffix[2]) or suffix[2].casefold() in {name.casefold() for name in application_names}):
        value, target = suffix[1], suffix[2]
        if music_help(value, name) is not None: return MediaRequest("play", target=canonical_name(target) or target)
    possessive = re.fullmatch(r"((?:убавь|прибавь|уменьши|увеличь)\s+(?:звук|громкость))\s+(.+)", value, re.I)
    if possessive and possessive[2].casefold() not in {"музыки", "плеера", "проигрывателя"} and not re.match(r"на\s", possessive[2], re.I):
        value, target = possessive[1], possessive[2]
    target = re.sub(r"^яндекс[. ]*музык[аеиуы]$", "Яндекс Музыка", target, flags=re.I)
    target = canonical_name(target) or target
    direction = colloquial_transport(value)
    if direction and target:
        return MediaRequest("read" if direction == "status" else direction, target=target)
    song = re.fullmatch(r"(?:запусти|включи|поставь|воспроизведи)\s+(?:песню|трек|композицию)(?:\s+(.+))?", value, re.I)
    if song: return MediaRequest("search_play", "song", target, query=(song[1] or "").strip(' "«»'))
    audio = audio_command(re.sub(r"\bгромкость (?:музыки|плеера|проигрывателя)\b", "громкость", value, flags=re.I), name)
    musical_volume = bool(re.search(r"музык|плеер|проигрывател", value, re.I))
    if audio and audio.action in {"status", "set_volume", "change_volume", "mute", "unmute"}:
        return MediaRequest(audio.action, "player" if target or musical_volume else "system", target, audio.value)
    if audio and audio.action in {"play", "pause", "play_pause", "next", "previous", "stop", "media_status"}:
        return MediaRequest("read" if audio.action == "media_status" else audio.action, target=target)
    query = free_query(value, music_context=music_context, explicit=bool(target), application_names=application_names)
    if query: return MediaRequest(query.action, "song", target, query=query.query)
    return None


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


class MediaManager:
    def __init__(self, store, scanner, yandex, opener=None):
        self.store, self.scanner, self.yandex = store, scanner, yandex
        self.lock = threading.RLock()
        self.opener = opener
        self.readiness_timeout = 4.0
        self.verification_timeout = 2.0

    def check(self, cancel=None):
        if cancel and cancel.is_set(): raise ValueError("Команда остановлена; повтор не отправлялся")
        if not self.store.settings().allow_audio_control: raise ValueError("Управление звуком отключено")

    def applications(self, target):
        found = self.scanner.find_matches(target)
        aliases = [item for item in self.store.list("aliases", 1000) if item["kind"] == "app" and (canonical_name(item["name"]) or item["name"]).casefold() == (canonical_name(target) or target).casefold()]
        return list({item["target"].casefold(): item for item in [*found, *aliases]}.values())

    def ready_yandex(self, request, cancel, rows, allow_launch=True):
        """Only an explicit/short-lived Yandex target may wait or start it."""
        began = time.monotonic()
        self.check(cancel)
        if allow_launch and not self.matches("Яндекс Музыка", rows) and self.opener:
            from .launch_verification import process_ids
            candidates = self.applications("Яндекс Музыка")
            if len(candidates) == 1:
                item = candidates[0]
                # Packaged identities cannot be mapped to an EXE by guessing.
                if not item["target"].startswith("aumid:") and not process_ids(item["target"]):
                    self.check(cancel)
                    self.opener.execute(commands.Command("app", item["target"], item["name"]))
        deadline = time.monotonic() + self.readiness_timeout
        while not self.matches("Яндекс Музыка", rows) and time.monotonic() < deadline:
            self.check(cancel)
            if cancel: cancel.wait(min(.2, max(0, deadline-time.monotonic())))
            else: time.sleep(min(.2, max(0, deadline-time.monotonic())))
            self.check(cancel)
            rows = self.inventory()["sessions"]
        return rows, round((time.monotonic()-began)*1000, 2)

    def inventory(self):
        warnings = []
        try: rows = windows_media.sessions()
        except (ValueError, OSError) as error:
            rows = []; warnings.append(str(error))
        for row in rows:
            for item in self.scanner.saved().get("items", []):
                source = row.get("app_id", "").casefold()
                target = item["target"]
                identities = {target[6:].casefold()} if target.startswith("aumid:") else {target.casefold(), Path(target).stem.casefold(), Path(target).name.casefold()}
                if source in identities:
                    row["player"] = item["name"]
                    break
        return {"selected": self.store.settings().media_source, "sessions": rows, "warnings": warnings, "checked_at": time.time()}

    def matches(self, target, rows):
        # Catalog aliases are exact names. No fuzzy matching of a process/session.
        found = self.applications(target)
        identifiers = {target.casefold()}
        for item in found:
            identifiers.add(item["name"].casefold())
            if item["target"].startswith("aumid:"):
                identifiers.add(item["target"][6:].casefold())
            else:
                identifiers.update((item["target"].casefold(), Path(item["target"]).stem.casefold(), Path(item["target"]).name.casefold()))
        return [row for row in rows if row.get("id") == target or row.get("app_id", "").casefold() in identifiers or row.get("player", "").casefold() in identifiers
                or (row.get("executable") and any(same_path(row["executable"], item["target"]) for item in found if not item["target"].startswith("aumid:")))]

    def select(self, request, rows, confirmed=""):
        if request.target:
            matches = self.matches(request.target, rows)
        else:
            selected = confirmed or self.store.settings().media_source
            if selected != "auto" and selected:
                matches = [row for row in rows if row.get("id") == selected]
                if not matches: return []
            else:
                playing = [row for row in rows if row.get("state") in {"Playing", "Воспроизведение"}]
                matches = playing if playing else rows
        return matches

    @staticmethod
    def reply(text, status="unavailable", **extra):
        return {"text": text, "spoken": text, "status": status, "confirmed": status == "confirmed", **extra}

    def volume(self, request, rows, confirmed=""):
        try: mixers = audio_sessions.snapshot()
        except (ValueError, OSError) as error: return self.reply("Микшер приложений недоступен. Громкость Windows не менялась.", detail=str(error))
        verified_sessions = set()
        if request.target and not request.target.startswith(("smtc:", "aimp:")):
            apps = self.scanner.find_matches(request.target)
            paths = [item["target"] for item in apps if not item["target"].startswith("aumid:")]
            app_ids = {item["target"][6:] for item in apps if item["target"].startswith("aumid:")}
            if app_ids:
                verified_sessions = {row["id"] for row in mixers if audio_sessions.app_id(row["pid"]) in app_ids}
        else:
            selected = self.select(request, rows, confirmed)
            if len(selected) != 1:
                return self.choices(selected)
            paths = [selected[0]["executable"]] if selected[0].get("executable") else []
            # Do not infer browser/packaged mixer identity from a similar SMTC label.
            if not paths:
                source = selected[0].get("app_id", "")
                mixers = [row for row in mixers if source and (audio_sessions.app_id(row["pid"]) == source or row["executable"].casefold() == source.casefold())]
                paths = [row["executable"] for row in mixers]
        matches = [row for row in mixers if row["id"] in verified_sessions or any(same_path(row["executable"], path) for path in paths)]
        active = [row for row in matches if row.get("active")]
        matches = active or matches
        if len(matches) != 1:
            return self.reply("Не удалось однозначно выбрать аудиосессию приложения. Уточните приложение или сессию в микшере Windows. Общая громкость не менялась.", "needs_clarification" if matches else "unavailable")
        if request.action not in {"set_volume", "change_volume"}:
            return self.reply("Для микшера приложений доступны команды изменения громкости. Уточните уровень или скажите «сделай музыку потише».", "needs_clarification")
        row = matches[0]
        result = audio_sessions.set_volume(row["id"], row["executable"], row["created"], request.value, relative=request.action == "change_volume")
        text = f"Громкость приложения в микшере Windows: {result['volume']}%. Это регулятор приложения, а не внутренний регулятор плеера."
        return {"text": text, "spoken": f"Громкость приложения — {result['volume']} процентов.", "status": "confirmed", "confirmed": True, "scope": "application_mixer", "state": result}

    def choices(self, matches):
        if not matches: return self.reply("Доступная медиасессия не найдена. Откройте плеер и включите в нём композицию.")
        names = "; ".join(f"{index}. {row.get('player', row['id'])}" + (" (текущая сессия Windows)" if row.get("current") else "") for index, row in enumerate(matches[:5], 1))
        return self.reply("Нашла несколько проигрывателей. Каким управлять? " + names + ". Ответьте номером или «отмена».", "needs_clarification", spoken="Нашла несколько проигрывателей. Каким управлять? Выберите номер в списке.", candidates=[{"id": row["id"], "name": row.get("player", row["id"])} for row in matches[:5]])

    def execute(self, request, confirmed="", request_id=None, cancel=None, allow_launch=True):
        with self.lock:
            if not self.store.settings().allow_audio_control and not (request.scope == "connection" and request.action in {"check", "clarify"}): raise ValueError("Управление звуком отключено")
            try:
                if cancel and cancel.is_set(): raise ValueError("Команда остановлена до выполнения")
                result = self._execute(request, confirmed, cancel, allow_launch)
            except Exception as error:
                self.store.audit("media.session", request.target, "failed", {"request_id": request_id, "action": request.action, "error": str(error)[:300]})
                raise
            self.store.audit("media.session", request.target, result["status"], {"request_id": request_id, "action": asdict(request), "result": result})
            return result

    def prepare_yandex(self, cancel, allow_launch):
        """Recover a missing special connection, never restart without consent."""
        self.check(cancel)
        status = self.yandex.status()
        if status.get("connected"): return None
        recover = getattr(self.yandex, "recover", None)
        if recover:
            status = recover(cancel, status)
            self.check(cancel)
            if status.get("connected"): return None
            if status.get("restart_required"):
                return self.reply("Яндекс Музыка открыта без CDP. Для переподключения нужен перезапуск; воспроизведение прервётся. Разрешить? Ответьте «да» или «нет».", "needs_clarification", restart_required=True, diagnostics=status.get("diagnostics", {}))
        if not allow_launch:
            from .yandex_music import MusicError, failure
            reason = status.get("diagnostics", {}).get("reason", "no_connection")
            return failure(MusicError(reason, status.get("error") or "CDP-подключение Яндекс Музыки отсутствует. Требуется переподключение."))
        self.check(cancel)
        connect = getattr(self.yandex, "connect_with_cancel", None)
        linked = connect(False, cancel) if connect else self.yandex.connect(False)
        self.check(cancel)
        if linked.get("restart_required"):
            return self.reply("Яндекс Музыка открыта без CDP. Для переподключения нужен перезапуск; воспроизведение прервётся. Разрешить? Ответьте «да» или «нет».", "needs_clarification", restart_required=True,
                              diagnostics={"reason": "no_cdp", "phase": "connection", "dispatch_attempted": False, "dispatched": False})
        if not linked.get("connected"):
            return self.reply("CDP-подключение Яндекс Музыки не подтверждено. Повторный запуск не отправлялся.", diagnostics={"reason": "no_connection", "phase": "connection", "dispatch_attempted": False, "dispatched": False})
        return None

    def _execute(self, request, confirmed, cancel=None, allow_launch=True):
        if request.scope == "system": raise ValueError("Общая громкость обрабатывается звуковым инструментом Windows")
        if request.scope == "connection":
            if request.action == "clarify": return self.reply("Какое подключение проверить? Назовите приложение; свежего однозначного контекста Яндекс Музыки нет.", "needs_clarification")
            if request.action == "restart":
                return self.reply("Перезапуск Яндекс Музыки прервёт воспроизведение. Разрешить? Ответьте «да» или «нет».", "needs_clarification", restart_required=True, diagnostics={"reason":"restart_confirmation", "phase":"permission", "dispatched":False})
            if request.action == "connect":
                pending = self.prepare_yandex(cancel, allow_launch)
                if pending: return pending
            status = self.yandex.status()
            if not status.get("connected") and request.action == "check" and hasattr(self.yandex, "recover"):
                status = self.yandex.recover(cancel, status)
            text = "CDP-подключение Яндекс Музыки доступно и проверено." if status.get("connected") else status.get("error", "CDP-подключение Яндекс Музыки недоступно.")
            return self.reply(text, "connected" if status.get("connected") else "unavailable", diagnostics={**status.get("diagnostics", {}), "reason": "connected" if status.get("connected") else status.get("diagnostics", {}).get("reason", "no_connection")}, connection={k:status.get(k) for k in ("connected","selected","enabled")})
        if request.scope == "song":
            if request.action == "found":
                return self.reply("Нет актуального списка найденных песен. Сначала назовите песню и исполнителя для поиска.")
            if request.action != "wave" and not request.query: return self.reply("Какую песню и в каком источнике включить?", "needs_clarification")
            target = canonical_name(request.target) or request.target
            settings = self.store.settings()
            if not target and (confirmed or settings.media_source != "auto"):
                selected = self.select(request, self.inventory()["sessions"], confirmed)
                if len(selected) != 1: return self.choices(selected)
                # A selected non-search player cannot silently fall back to
                # the preferred Yandex integration.
                target = "Яндекс Музыка" if self.matches("Яндекс Музыка", selected) else selected[0]["id"]
            if not target and settings.music_player == "yandex": target = "Яндекс Музыка"
            if target != "Яндекс Музыка":
                return self.reply("Системное управление плеером не поддерживает поиск песен. Назовите Яндекс Музыку с подключённой интеграцией или выполните поиск в своём плеере.")
            self.check(cancel)
            unavailable = self.prepare_yandex(cancel, allow_launch and request.action != "select")
            if unavailable: return unavailable
            result = self.yandex.execute(MusicAction(action=request.action, query=request.query, selection=request.selection), cancel)
            return self.special_result(result, request)
        self.check(cancel)
        # A specifically selected Yandex adapter does not need an SMTC session
        # (Electron may create that session only after playback has begun).
        if (canonical_name(request.target) or request.target) == "Яндекс Музыка" and request.action in {"play", "pause", "stop", "next", "previous", "play_pause", "read"}:
            status = self.yandex.status()
            settings = self.store.settings()
            descriptor = getattr(self.yandex, "path", None)
            special_requested = settings.music_player == "yandex" or settings.yandex_auto_connect or settings.yandex_auto_play or bool(descriptor and descriptor.exists())
            if not status.get("connected") and special_requested and hasattr(self.yandex, "recover"):
                unavailable = self.prepare_yandex(cancel, allow_launch and request.action == "play" and (settings.yandex_auto_connect or settings.yandex_auto_play))
                if unavailable: return unavailable
                status = self.yandex.status()
            if not status.get("connected") and request.action == "play" and allow_launch and (settings.yandex_auto_connect or settings.yandex_auto_play):
                self.check(cancel)
                # A connection may already launch the player. Never fall back to
                # a second launch or a second backend after an uncertain result.
                status = self.yandex.connect(False)
                self.check(cancel)
                if status.get("restart_required"):
                    return self.reply("Для управления Яндекс Музыкой нужен перезапуск. Воспроизведение прервётся. Разрешить? Ответьте «да» или «нет».", "needs_clarification", restart_required=True)
                if not status.get("connected"):
                    return self.reply("Специальное подключение Яндекс Музыки не подтверждено. Повторный запуск не отправлялся.")
            if status.get("connected"):
                self.check(cancel)
                result = self.yandex.execute(MusicAction(action={"stop": "pause", "read": "status"}.get(request.action, request.action)), cancel)
                return self.special_result(result, request)
        rows = self.inventory()["sessions"]
        ready_ms = 0
        if request.action == "play" and (canonical_name(request.target) or request.target) == "Яндекс Музыка":
            rows, ready_ms = self.ready_yandex(request, cancel, rows, allow_launch)
        if request.action in {"set_volume", "change_volume", "mute", "unmute", "status"}:
            return self.volume(request, rows, confirmed)
        matches = self.select(request, rows, confirmed)
        if len(matches) != 1:
            if not matches and request.action == "play" and request.target == "Яндекс Музыка":
                self.check(cancel)
                status = self.yandex.status()
                if status.get("connected") and status.get("state", {}).get("available"):
                    self.check(cancel)
                    result = self.yandex.execute(MusicAction(action="play"), cancel)
                    verified = result.get("confirmed") is True
                    return {**result, "spoken": "Воспроизведение подтверждено." if verified else "Воспроизведение не подтверждено.", "status": "confirmed" if verified else "unconfirmed", "readiness_ms": ready_ms}
                return self.reply("Медиасессия Яндекс Музыки не появилась за ограниченное время. Воспроизведение не подтверждено. Откройте «Мою волну» в плеере; специальное управление доступно только при отдельном подключении.", readiness_ms=ready_ms)
            return self.choices(matches)
        selected = matches[0]
        if sum(row.get("id") == selected["id"] for row in rows) != 1:
            return self.reply("У приложения несколько медиасессий с одним идентификатором. Выберите композицию в самом приложении.", "needs_clarification")
        if request.action == "read":
            state = {"Playing": "воспроизведение", "Paused": "пауза", "Stopped": "остановлено"}.get(selected.get("state"), selected.get("state", "неизвестно"))
            track = selected.get("track") if isinstance(selected.get("track"), dict) else {}
            spoken = " — ".join(str(track.get(key) or "").strip() for key in ("title", "artist") if str(track.get(key) or "").strip())
            return self.reply(windows_media.describe(selected), "read", media=selected, spoken=spoken + "." if spoken else f"Состояние проигрывателя: {state}.")
        if request.action not in selected.get("commands", []): return self.reply("Этот проигрыватель сейчас не поддерживает такую команду.")
        if request.action == "play" and selected.get("available") is not False and selected.get("state") in {"Playing", "Воспроизведение"}:
            return self.reply("Яндекс Музыка уже воспроизводит музыку." if request.target == "Яндекс Музыка" else "Плеер уже воспроизводит музыку.", "confirmed", media=selected, readiness_ms=ready_ms)
        result = windows_media.verify_selected(selected, request.action, lambda: self.check(cancel), self.verification_timeout)
        if result.get("confirmed"):
            verbs = {"play": ("Продолжила музыку.", "Продолжил музыку.", "Воспроизведение подтверждено."), "pause": ("Поставила на паузу.", "Поставил на паузу.", "Пауза подтверждена."), "stop": ("Остановила воспроизведение.", "Остановил воспроизведение.", "Воспроизведение остановлено."), "next": ("Переключила трек.", "Переключил трек.", "Трек переключён."), "previous": ("Переключила на предыдущий трек.", "Переключил на предыдущий трек.", "Предыдущий трек выбран.")}
            gender = {"feminine": 0, "masculine": 1, "neutral": 2}[self.store.settings().grammatical_gender]
            spoken = verbs.get(request.action, ("Состояние плеера подтверждено.",) * 3)[gender]
        else:
            spoken = ("Отправлена команда переключения, но смена композиции не подтверждена." if request.action in {"next", "previous"} else "Запрос передан, но изменение состояния плеера не подтверждено.") if result.get("accepted") else "Плеер не принял команду."
        return {"text": windows_media.describe(result), "spoken": spoken, "status": "confirmed" if result.get("confirmed") else "unconfirmed", "confirmed": bool(result.get("confirmed")), "media": result, "readiness_ms": ready_ms}

    def special_result(self, result, request=None):
        if result.get("candidates"):
            return {**result, "status": "needs_clarification", "spoken": "Найдены песни. Скажите номер в списке или «отмена»."}
        verified = result.get("confirmed") is True
        spoken = result.get("spoken") or result.get("text") or "Изменение в Яндекс Музыке не подтверждено."
        if verified:
            action = request.action if request else ""
            spoken = {"play": "Продолжаю.", "pause": "На паузе.", "stop": "Музыка остановлена.", "next": "Переключаю.", "previous": "Переключаю.", "wave": "Включаю музыку.", "select": "Включаю.", "search_play": "Включаю."}.get(action, "Состояние Яндекс Музыки подтверждено.")
            if action == "read":
                state = result.get("state") if isinstance(result.get("state"), dict) else {}
                track = " — ".join(str(state.get(key) or "").strip() for key in ("title", "artists") if str(state.get(key) or "").strip())
                if track: spoken = track + "."
        return {**result, "status": "confirmed" if verified else result.get("status", "unconfirmed"), "spoken": spoken}


async def run_action(manager, request, confirmed="", request_id=None, allow_launch=True):
    cancel = threading.Event()
    operation = asyncio.create_task(asyncio.to_thread(manager.execute, request, confirmed, request_id, cancel, allow_launch))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        cancel.set()
        with CancelScope(shield=True):
            await asyncio.gather(operation, return_exceptions=True)
        raise


def end_session(store):
    """Retire executable voice proposals and transient targeting, not user data."""
    with store.db() as db:
        db.execute("UPDATE chat_dialogue SET value=json_remove(value,'$.pending_open','$.pending_audio','$.pending_media','$.media_choice','$.music_context') WHERE conversation_id=?", (store.conversation_id,))


def yandex_context(store, cancelled=None):
    state = store.dialogue()
    for key in ("music_context", "media_choice"):
        choice = state.get(key)
        if not isinstance(choice, dict): continue
        created = choice.get("created", 0)
        if choice.get("target") == "Яндекс Музыка" and type(created) in {int,float} and 0 <= time.time()-created < 300 and choice.get("request_id") not in (cancelled or {}): return True
    return False


def remember(store, assistant_id, *, request=None, candidates=None, restart=False, semantic=False, request_id="", intent_gate=False):
    state = store.dialogue()
    state["pending_media"] = {"assistant_id": assistant_id, "created": time.time(), "request": asdict(request) if request else None, "candidates": candidates or [], "restart": restart, "semantic": semantic, "request_id": request_id, "intent_gate":intent_gate}
    store.save_dialogue(state)


def song_choice(value):
    """Only a whole numbered selection, never words within a song title."""
    match = re.fullmatch(r"(?:(?:включи|поставь|воспроизведи|выбери)\s+)?(?:(?:песню|песня|трек|композицию|номер)\s+)?(первую|первая|первый|вторую|вторая|второй|третью|третья|третий|[1-3])(?:\s+(?:песню|песня|трек|композицию))?", value, re.I)
    if not match: return None
    word = match[1].casefold()
    return word if word.isdigit() else "1" if word.startswith("перв") else "2" if word.startswith("втор") else "3"


def consume(store, text, name, cancelled=None):
    state = store.dialogue(); pending = state.pop("pending_media", None)
    if not pending: return None
    store.save_dialogue(state)
    value = request_form(text, name).casefold().strip(".!? ")
    song = (pending.get("request") or {}).get("scope") == "song"
    if song:
        value = song_choice(value) or value
        if value in {"включи найденную", "включи найденную песню"} and len(pending["candidates"]) == 1: value = "1"
    numbers = {"один": 1, "первый": 1, "два": 2, "второй": 2, "три": 3, "третий": 3, "четыре": 4, "пять": 5}
    match = re.fullmatch(r"(?:(?:плеер|проигрыватель|вариант|номер) )?(\d|один|первый|два|второй|три|третий|четыре|пять)(?: вариант)?", value)
    if value not in {"да", "нет", "отмена", "не надо"} and not match: return None
    history = store.list("messages", 2)
    if time.time() - pending["created"] > 300 or len(history) != 2 or history[-2]["role"] != "assistant" or history[-2]["id"] != pending["assistant_id"]:
        return {"reply": "Предложение управления плеером устарело. Повторите команду."}
    if value in {"нет", "отмена", "не надо"}: return {"reply": "Управление плеером отменено. Перезапуск не выполнялся."}
    if pending.get("request_id") in (cancelled or {}) or (pending.get("semantic") and not (store.settings().intent_gate if pending.get("intent_gate") else store.settings().semantic_commands)):
        return {"reply": "Интеллектуальное предложение отключено или остановлено. Плеер не изменён."}
    if pending["restart"]:
        return {"restart": True, "request": MediaRequest(**pending["request"]) if pending.get("request") else None, "semantic":pending.get("semantic",False), "intent_gate":pending.get("intent_gate",False)} if value == "да" else {"reply": "Для перезапуска нужно явное «да»."}
    choices = pending["candidates"]
    index = (int(match[1]) if match and match[1].isdigit() else numbers.get(match[1], 0) if match else 1) - 1
    if (value == "да" and len(choices) != 1) or not 0 <= index < len(choices):
        return {"reply": "Укажите номер песни из списка. Повторите поиск для нового выбора." if song else "Укажите номер проигрывателя. Повторите команду для нового выбора."}
    if song:
        selected = choices[index]
        selection = {key: selected[key] for key in ("id", "title", "artists", "search_id")}
        if selected.get("retrieval_query"): selection["retrieval_query"] = selected["retrieval_query"]
        return {"request": MediaRequest("select", "song", "Яндекс Музыка", query=pending["request"]["query"], selection=selection), "selection_index": index + 1, "semantic": pending.get("semantic", False), "intent_gate":pending.get("intent_gate",False)}
    selected = choices[index]["id"]
    state["media_choice"] = {"id": selected, "created": time.time()}
    store.save_dialogue(state)
    return {"request": MediaRequest(**{**pending["request"], "target": selected}), "semantic": pending.get("semantic", False)}
