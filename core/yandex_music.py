"""Local, process-bound Electron adapter; it never reads account credentials."""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse, unquote
import asyncio
import difflib
import json
import math
import os
import re
import socket
import subprocess
import threading
import time

import httpx
import psutil
from anyio import CancelScope
from .app_catalog import canonical_name
from .app_discovery import local_file, shortcut_targets
from .music_intents import MusicAction, search_query
from .launch_verification import shell_launch

PAGE_SCRIPT = Path(__file__).with_name("yandex_music_page.js").read_text(encoding="utf-8")
EXES = {"яндекс музыка.exe", "яндексмузыка.exe", "yandexmusic.exe"}


def same_file(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def running(executable):
    result = []
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            if process.info["exe"] and same_file(process.info["exe"], executable) and not any(arg.startswith("--type=") for arg in process.cmdline()):
                result.append(process)
        except (psutil.Error, OSError):
            continue
    return result


def debug_port(process):
    return next((int(arg.split("=", 1)[1]) for arg in process.cmdline() if re.fullmatch(r"--remote-debugging-port=\d{1,5}", arg)), None)


@contextmanager
def exit_waiter(processes):
    """Keep SYNCHRONIZE handles before termination; psutil reopens dead PIDs on Windows."""
    if os.name != "nt":
        yield lambda: not psutil.wait_procs(processes, timeout=4)[1]
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    with ExitStack() as handles:
        opened = []
        for process in processes:
            handle = kernel.OpenProcess(0x00100000, False, process.pid)
            if not handle:
                code = ctypes.get_last_error()
                if code in {87, 1168}: continue  # Already exited before opening.
                raise ValueError("Windows не разрешила ожидать закрытия плеера. Закройте Яндекс Музыку вручную и повторите подключение.")
            opened.append(handle)
            handles.callback(kernel.CloseHandle, handle)
        def wait():
            deadline = time.monotonic() + 4
            return all(kernel.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000))) == 0 for handle in opened)
        yield wait


def start_player(executable, port):
    arguments = [f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1"]
    if os.name == "nt":
        # Shell handles an application's elevation manifest through the normal UAC prompt.
        shell_launch(executable, arguments=arguments, directory=executable.parent)
    else:
        subprocess.Popen([str(executable), *arguments], cwd=executable.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def rank(query, rows):
    def words(value): return re.findall(r"[\w]+", search_query(value).casefold().replace("ё", "е"))
    wanted = words(query)
    if not wanted: return []
    results = []
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("id", "title", "artists")) or not re.fullmatch(r"\d{1,30}", row["id"]):
            continue
        actual = words(row["title"] + " " + row["artists"])
        coverage = sum(word in actual for word in wanted) / len(wanted)
        similarity = difflib.SequenceMatcher(None, " ".join(sorted(wanted)), " ".join(sorted(actual))).ratio()
        score = .65 * coverage + .35 * similarity
        if any(word in actual and word not in wanted for word in ("remix", "live", "reanimation", "acoustic", "slowed", "sped", "ремикс", "кавер")):
            score -= .15
        results.append({**row, "score": round(score, 4)})
    return sorted(results, key=lambda row: row["score"], reverse=True)


class Renderer:
    def __init__(self, socket):
        self.socket, self.sequence = socket, 0

    def call(self, method, params):
        self.sequence += 1
        self.socket.send(json.dumps({"id": self.sequence, "method": method, "params": params}, ensure_ascii=False))
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            data = json.loads(self.socket.recv(timeout=max(.1, deadline - time.monotonic())))
            if data.get("id") != self.sequence: continue
            if "error" in data: raise ValueError("Яндекс Музыка отклонила локальную команду")
            return data.get("result", {})
        raise ValueError("Яндекс Музыка не ответила вовремя")

    def action(self, action, **arguments):
        expression = "(" + PAGE_SCRIPT + ")(" + json.dumps({"action": action, **arguments}, ensure_ascii=False) + ")"
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True, "timeout": 6000})
        if result.get("exceptionDetails"):
            # Return only our adapter's bounded message, not arbitrary page data.
            description = result["exceptionDetails"].get("exception", {}).get("description", "")
            message = description.split("\n")[0].removeprefix("Error: ")[:240]
            raise ValueError(message or "Элемент управления Яндекс Музыки недоступен")
        return result.get("result", {}).get("value")

    def pointer(self, x, y):
        if not all(isinstance(value, (float, int)) and 0 <= value <= 10000 for value in (x, y)):
            raise ValueError("Ползунок громкости находится за пределами окна")
        self.hover(x, y)
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1 if kind == "mousePressed" else 0, "clickCount": 1})

    def hover(self, x, y):
        if not all(isinstance(value, (float, int)) and 0 <= value <= 10000 for value in (x, y)):
            raise ValueError("Регулятор громкости находится за пределами окна")
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})


class YandexMusic:
    def __init__(self, root, store, scanner):
        self.path = Path(root) / "yandex-music-connection.json"
        self.store, self.scanner = store, scanner
        self.lock = threading.Lock()
        self.scan = (None, 0.0, [])

    def executable(self):
        aliases = self.store.list("aliases", 1000)
        item = next((row for row in aliases if row["kind"] == "app" and canonical_name(row["name"]) == "Яндекс Музыка"), None)
        item = item or self.scanner.find("Яндекс Музыка")
        if not item: raise ValueError("Яндекс Музыка не найдена. Добавьте её путь в разделе «Команды»")
        value = item["target"]
        if Path(value).suffix.casefold() == ".lnk": value = shortcut_targets([value]).get(value)
        result = local_file(value)
        if result is None or result.name.casefold() not in EXES:
            raise ValueError("Не удалось проверить EXE Яндекс Музыки")
        return result

    def descriptor(self):
        try:
            if self.path.stat().st_size > 8192: return None
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if type(data.get("pid")) is not int or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535 or not isinstance(data.get("exe"), str): return None
            process = psutil.Process(data["pid"])
            if Path(data["exe"]).name.casefold() not in EXES or not same_file(process.exe(), data["exe"]) or abs(process.create_time() - data["created"]) > .01 or debug_port(process) != data["port"]:
                return None
            return data
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            return None

    def listeners(self, port):
        # A full TCP table scan is slow on Windows; connect() polls status() every 0.2 s, so reuse it briefly.
        cached, at, rows = self.scan
        if cached != port or time.monotonic() - at > 1:
            rows = [item for item in psutil.net_connections(kind="tcp") if item.status == psutil.CONN_LISTEN and item.laddr.port == port]
            self.scan = (port, time.monotonic(), rows)
        return rows

    @contextmanager
    def renderer(self):
        from websockets.sync.client import connect
        data = self.descriptor()
        if not data: raise ValueError("Яндекс Музыка не подключена. Нажмите «Подключить» в разделе «Команды → Яндекс Музыка»")
        family = {data["pid"], *(p.pid for p in psutil.Process(data["pid"]).children(recursive=True))}
        listeners = self.listeners(data["port"])
        if not listeners or any(item.pid not in family or item.laddr.ip not in {"127.0.0.1", "::1"} for item in listeners):
            raise ValueError("Локальный канал не принадлежит проверенному процессу Яндекс Музыки")
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=3) as client:
            response = client.get(f"http://127.0.0.1:{data['port']}/json/list")
            response.raise_for_status()
            if len(response.content) > 256000: raise ValueError("Некорректный ответ Яндекс Музыки")
            pages = response.json()
        resource = str(Path(data["exe"]).parent / "resources").replace("\\", "/").casefold().rstrip("/") + "/"
        def allowed(page):
            url = urlparse(page.get("url", ""))
            file = unquote(url.path).lstrip("/").replace("\\", "/").casefold()
            return page.get("type") == "page" and ((url.scheme == "file" and not url.netloc and file.startswith(resource) and file.endswith(".html")) or (url.scheme == "https" and url.hostname in {"music.yandex.ru", "music.yandex.com"}) or (url.scheme == "music-application" and url.netloc == "desktop"))
        matches = [page for page in pages if isinstance(page, dict) and allowed(page)] if isinstance(pages, list) else []
        if len(matches) != 1: raise ValueError("Не найдено единственное окно плеера Яндекс Музыки")
        websocket = matches[0].get("webSocketDebuggerUrl", "")
        parsed = urlparse(websocket)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != data["port"] or parsed.username or parsed.password or not re.fullmatch(r"/devtools/page/[\w-]+", parsed.path):
            raise ValueError("Некорректный адрес локального канала")
        with connect(websocket, open_timeout=3, close_timeout=1, max_size=512000, proxy=None) as connection:
            yield Renderer(connection)

    def status(self):
        selected = self.store.settings().music_player == "yandex"
        enabled = self.store.settings().allow_audio_control
        try:
            with self.renderer() as page: state = page.action("status")
            return {"connected": True, "selected": selected, "state": state, "enabled": enabled}
        except Exception as error:
            return {"connected": False, "selected": selected, "enabled": enabled, "error": str(error)[:240] if isinstance(error, ValueError) else "Связь с плеером недоступна"}

    def connect(self, restart=False):
        try:
            return self._connect(restart)
        except (psutil.Error, OSError) as error:
            text = "Windows не разрешила доступ к плееру. Закройте Яндекс Музыку вручную и подключите её из WileyAI. Подтвердите запрос Windows, если эта сборка требует прав администратора."
            self.store.audit("music.connect", "yandex", "error", {"text": text, "error": type(error).__name__})
            raise ValueError(text) from None
        except ValueError as error:
            self.store.audit("music.connect", "yandex", "error", {"text": str(error)[:300]})
            raise

    def _connect(self, restart=False):
        if not self.store.settings().allow_app_open or not self.store.settings().allow_audio_control:
            raise ValueError("Разрешите запуск приложений и управление звуком в разделе «Команды»")
        with self.lock:
            executable = self.executable()
            self.store.patch_settings({"music_player": "yandex"})
            instances = running(executable)
            process = next((p for p in instances if debug_port(p)), None)
            if instances and process is None:
                if not restart: return {"connected": False, "selected": True, "restart_required": True, "text": "Плеер уже открыт без локального управления. Подключение потребует перезапуска; музыка остановится."}
                with exit_waiter(instances) as wait:
                    for instance in instances:
                        children = instance.children(recursive=True)
                        for child in [*children, instance]:
                            try:
                                if same_file(child.exe(), executable): child.terminate()
                            except psutil.NoSuchProcess: pass
                    if not wait(): raise ValueError("Не удалось закрыть прежний плеер. Завершите его вручную и повторите подключение")
            if process is None:
                with socket.socket() as reserved:
                    reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
                start_player(executable, port)
                for _ in range(50):
                    process = next((p for p in running(executable) if debug_port(p) == port), None)
                    if process: break
                    time.sleep(.1)
                if process is None: raise ValueError("Не удалось подтвердить процесс Яндекс Музыки")
            port = debug_port(process)
            data = {"pid": process.pid, "created": process.create_time(), "exe": str(executable), "port": port}
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8"); temporary.replace(self.path)
            for _ in range(40):
                status = self.status()
                if status["connected"]:
                    self.store.patch_settings({"music_player": "yandex"})
                    self.store.audit("music.connect", str(executable), "connected", {"pid": process.pid})
                    return {**status, "selected": True, "text": "Яндекс Музыка подключена. Музыкальные команды адресованы этому плееру."}
                time.sleep(.2)
            raise ValueError("Плеер запущен, но подключение не завершено: " + status.get("error", "канал управления недоступен"))

    def disconnect(self):
        with self.lock:
            self.path.unlink(missing_ok=True)
            self.store.patch_settings({"music_player": "auto"})
        return {"connected": False, "selected": False, "text": "Управление Яндекс Музыкой отключено в WileyAI. Плеер продолжает работать."}

    def execute(self, command: MusicAction, cancel=None):
        target = "yandex:" + command.action
        def check():
            if cancel and cancel.is_set(): raise ValueError("Команда Яндекс Музыки остановлена")
            if not self.store.settings().allow_audio_control: raise ValueError("Управление звуком отключено в разделе «Команды»")
        try:
            with self.lock, self.renderer() as page:
                check()
                before = page.action("status")
                candidates, expected_id = [], None
                action = command.action
                if action == "search_play":
                    page.action("search", query=search_query(command.query))
                    for _ in range(40):
                        check()
                        found = page.action("results", query=search_query(command.query)) or {}
                        candidates = rank(command.query, found.get("rows", [])) if found.get("ready") else []
                        if candidates: break
                        time.sleep(.15)
                    if not candidates: raise ValueError("В поиске Яндекс Музыки треки не найдены. Уточните название и исполнителя")
                    if candidates[0]["score"] < .72 or (len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < .05):
                        result = {"confirmed": False, "candidates": candidates[:3], "text": "Нет достаточно точного совпадения. Уточните исполнителя и название; воспроизведение не запускалось.\n" + "\n".join(f"{row['artists']} — {row['title']}" for row in candidates[:3])}
                        self.store.audit("music.yandex", target, "ambiguous", result)
                        return result
                    selected = candidates[0]; expected_id = selected["id"]
                    # A synthetic element.click() need not activate Electron's
                    # audio context. Dispatch a native pointer after revalidating
                    # the exact fresh result and its hit target on hover.
                    current_track = page.action("status")
                    if current_track.get("id") != expected_id or current_track.get("playing") is not True:
                        selection = {key: selected[key] for key in ("id", "title", "artists")}
                        for attempt in range(5):
                            check()
                            button = page.action("select_target", query=search_query(command.query), **selection)
                            if attempt and not button.get("reveal"):
                                break
                            page.hover(button["x"], button["y"])
                            time.sleep(.1)
                        else:
                            raise ValueError("Кнопка найденной песни перекрыта или недоступна. Запуск не отправлен")
                        check(); page.pointer(button["x"], button["y"])
                elif action in {"volume", "change_volume"}:
                    def volume_target(value):
                        for _ in range(10):
                            check()
                            slider = page.action("volume_target", value=value)
                            if not slider.get("reveal"): return slider
                            page.hover(slider["x"], slider["y"])
                            time.sleep(.1)
                        raise ValueError("Не удалось открыть регулятор громкости плеера")
                    current = before.get("volume")
                    if current is None:
                        volume_target(50)
                        time.sleep(.1); before = page.action("status"); current = before.get("volume")
                    if action == "change_volume" and current is None: raise ValueError("Не удалось прочитать громкость плеера")
                    desired_volume = max(0, min(100, (current or 0) + command.value if action == "change_volume" else command.value))
                    slider = volume_target(desired_volume)
                    check(); page.pointer(slider["x"], slider["y"])
                elif action != "status":
                    check(); response = page.action(action)
                progress_start, playback_progress = None, False
                def confirmed(state):
                    nonlocal progress_start, playback_progress
                    if action == "status": return state.get("available", False)
                    if action == "play": return state.get("playing") is True and state.get("available")
                    if action == "pause": return state.get("playing") is False and state.get("available")
                    if action == "play_pause": return state.get("playing") != before.get("playing")
                    if action in {"next", "previous"}: return bool(state.get("id") and state["id"] != before.get("id"))
                    if action in {"like", "unlike", "toggle_like"}: return state.get("id") == before.get("id") and state.get("liked") is response.get("wanted")
                    if action in {"volume", "change_volume"}: return state.get("volume") is not None and abs(state["volume"] - desired_volume) <= 3
                    if not state.get("available") or state.get("id") != expected_id or state.get("playing") is not True:
                        progress_start = None
                        playback_progress = False
                        return False
                    position = state.get("position")
                    if type(position) not in {int, float} or not math.isfinite(position) or position < 0:
                        playback_progress = False
                        return False
                    if progress_start is None or position < progress_start:
                        progress_start = position
                    playback_progress = position - progress_start >= .15
                    return playback_progress
                after = page.action("status")
                for _ in range(25):
                    if confirmed(after): break
                    time.sleep(.1); after = page.action("status")
                verified = bool(confirmed(after))
                detail = " — ".join(part for part in (after.get("artists"), after.get("title")) if part)
                change = ("Воспроизведение" if after.get("playing") else "Пауза") if after.get("available") else "Нет выбранного трека"
                if action in {"like", "unlike", "toggle_like"}: change = "В любимых" if after.get("liked") else "Убрано из любимых"
                if action in {"volume", "change_volume"}: change = f"Громкость плеера: {after.get('volume')}%"
                text = ("Яндекс Музыка подтвердила: " if verified else "Изменение в Яндекс Музыке не подтверждено. Прочитанное состояние: ") + change + (". " + detail if detail else "")
                result = {"confirmed": verified, "state": after, "text": text}
                if action == "search_play":
                    result["selected"] = {key: selected[key] for key in ("id", "title", "artists")}
                    result["playback_progress"] = playback_progress
                    result["text"] = (
                        "Найдена и воспроизводится в Яндекс Музыке: " + detail + ". Плеер подтвердил трек и продвижение воспроизведения."
                        if verified else "Найдена песня: " + selected["artists"] + " — " + selected["title"] + ". Запуск этой песни не подтверждён: плеер не показал выбранный трек с продвижением воспроизведения."
                    )
                self.store.audit("music.yandex", target, "confirmed" if verified else "unconfirmed", result)
                return result
        except Exception as error:
            self.store.audit("music.yandex", target, "error", {"text": str(error)[:300]})
            if isinstance(error, ValueError): raise
            raise ValueError("Связь с Яндекс Музыкой потеряна. Проверьте подключение в разделе «Команды»") from None


async def run_action(controller, command, progress):
    cancel = threading.Event()
    operation = asyncio.create_task(asyncio.to_thread(controller.execute, command, cancel))
    try:
        result = await asyncio.shield(operation)
    except asyncio.CancelledError:
        cancel.set()
        with CancelScope(shield=True):
            try: progress.append((await operation)["text"])
            except Exception: progress.append("Команда Яндекс Музыки остановлена. Уже выполненное действие не отменяется.")
        raise
    progress.append(result["text"])
    return result
