"""Local, process-bound Electron adapter; it never reads account credentials."""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse, unquote
import asyncio
import json
import math
import os
import re
import socket
import subprocess
import threading
import time
import uuid

import httpx
import psutil
from anyio import CancelScope
from .app_catalog import canonical_name
from .app_discovery import local_file, shortcut_targets
from .music_intents import MusicAction, search_query
from .launch_verification import shell_launch
from .music_entity import rank as entity_rank, confident as entity_confident, alternatives as entity_alternatives

PAGE_SCRIPT = Path(__file__).with_name("yandex_music_page.js").read_text(encoding="utf-8")
EXES = {"яндекс музыка.exe", "яндексмузыка.exe", "yandexmusic.exe"}


class MusicError(ValueError):
    def __init__(self, reason, message, phase="connection"):
        super().__init__(message)
        self.reason, self.phase = reason, phase
        self.dispatch_attempted = self.dispatched = False
        self.verification = None


def failure(error):
    """Only owned, bounded adapter messages are exposed; no arbitrary page data."""
    known = isinstance(error, MusicError)
    sent = getattr(error, "dispatched", False)
    return {"confirmed": False, "status": "unconfirmed" if sent else "failed", "text": ("Команда передана плееру, но проверка результата не завершена. Повтор автоматически не отправлялся. " if sent else "") + (str(error) if known else "Связь с Яндекс Музыкой потеряна. Проверьте специальное подключение."),
            "diagnostics": {"reason": error.reason if known else "cdp_unavailable", "phase": error.phase if known else "connection",
                            "dispatch_attempted": getattr(error, "dispatch_attempted", False), "dispatched": getattr(error, "dispatched", False)},
            **({"verification":error.verification} if known and error.verification else {})}


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
    return entity_rank(query, rows)


class Renderer:
    def __init__(self, socket):
        self.socket, self.sequence = socket, 0

    def call(self, method, params):
        from websockets.exceptions import ConnectionClosed
        self.sequence += 1
        try:
            self.socket.send(json.dumps({"id": self.sequence, "method": method, "params": params}, ensure_ascii=False))
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                data = json.loads(self.socket.recv(timeout=max(.1, deadline - time.monotonic())))
                if data.get("id") != self.sequence: continue
                if "error" in data: raise MusicError("cdp_rejected", "Яндекс Музыка отклонила локальную команду")
                return data.get("result", {})
        except TimeoutError:
            raise MusicError("cdp_timeout", "Яндекс Музыка не ответила вовремя; команда повторно не отправлялась.") from None
        except (OSError, ConnectionClosed):
            raise MusicError("cdp_unavailable", "Локальная связь с Яндекс Музыкой прервана; команда повторно не отправлялась.") from None
        raise MusicError("cdp_timeout", "Яндекс Музыка не ответила вовремя")

    def action(self, action, **arguments):
        expression = "(" + PAGE_SCRIPT + ")(" + json.dumps({"action": action, **arguments}, ensure_ascii=False) + ")"
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True, "timeout": 6000})
        if result.get("exceptionDetails"):
            # Return only our adapter's bounded message, not arbitrary page data.
            description = result["exceptionDetails"].get("exception", {}).get("description", "")
            message = description.split("\n")[0].removeprefix("Error: ")[:240]
            match = re.fullmatch(r"WILEY_MUSIC/(button_missing|click_not_dispatched|renderer_not_ready|search_session_missing|search_query_changed|search_id_changed|search_input_changed|search_expired|search_not_ready|search_results_changed)/(.+)", message)
            if match: raise MusicError(match[1], match[2], ("selection" if action == "select_target" else "search") if match[1].startswith("search_") else "target")
            raise MusicError("element_unavailable", "Элемент управления Яндекс Музыки недоступен; действие не подтверждено.", "target")
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
        self.lock = threading.RLock()
        self.connect_context = threading.local()
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
        try: return self.checked_descriptor()
        except (MusicError, OSError, ValueError, KeyError, TypeError, psutil.Error): return None

    def checked_descriptor(self):
        try:
            if not self.path.exists(): raise MusicError("no_connection", "Сохранённого CDP-подключения Яндекс Музыки нет. Подключите плеер.")
            if self.path.stat().st_size > 8192: raise ValueError("descriptor size")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if type(data.get("pid")) is not int or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535 or not isinstance(data.get("exe"), str): raise ValueError("descriptor fields")
            process = psutil.Process(data["pid"])
            if abs(process.create_time() - data["created"]) > .01:
                raise MusicError("stale_pid", "CDP-подключение устарело: PID относится к другому запуску Яндекс Музыки. Требуется переподключение.")
            if Path(data["exe"]).name.casefold() not in EXES or not same_file(process.exe(), data["exe"]):
                raise MusicError("identity_mismatch", "Не подтверждён EXE сохранённого процесса Яндекс Музыки. Подключение отклонено.")
            if debug_port(process) != data["port"]:
                raise MusicError("no_cdp", "Яндекс Музыка открыта без сохранённого CDP-канала. Требуется переподключение.")
            return data
        except MusicError: raise
        except psutil.NoSuchProcess:
            raise MusicError("stale_pid", "CDP-подключение устарело: сохранённый процесс Яндекс Музыки уже завершён. Требуется переподключение.") from None
        except psutil.AccessDenied:
            raise MusicError("access_denied", "Windows не разрешила проверить процесс CDP-подключения Яндекс Музыки.") from None
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            raise MusicError("invalid_connection", "Сохранённое CDP-подключение Яндекс Музыки повреждено или недоступно. Подключите плеер заново.") from None

    def listeners(self, port):
        # A full TCP table scan is slow on Windows; connect() polls status() every 0.2 s, so reuse it briefly.
        cached, at, rows = self.scan
        if cached != port or time.monotonic() - at > 1:
            rows = [item for item in psutil.net_connections(kind="tcp") if item.status == psutil.CONN_LISTEN and item.laddr.port == port]
            self.scan = (port, time.monotonic(), rows)
        return rows

    @contextmanager
    def renderer(self):
        data = self.descriptor()
        if not data:
            self.checked_descriptor()  # Preserve the concrete reason instead of hiding a stale PID.
            raise MusicError("no_connection", "Яндекс Музыка не подключена. Подключите плеер заново.")
        with self._renderer_for_descriptor(data) as page:
            yield page

    @contextmanager
    def _renderer_for_descriptor(self, data):
        from websockets.sync.client import connect
        process = psutil.Process(data["pid"])
        if abs(process.create_time()-data["created"]) > .01 or not same_file(process.exe(), data["exe"]) or debug_port(process) != data["port"]:
            raise MusicError("identity_mismatch", "Процесс CDP изменился перед подключением; канал отклонён.")
        family = {data["pid"], *(p.pid for p in process.children(recursive=True))}
        listeners = self.listeners(data["port"])
        if not listeners or any(item.pid not in family or item.laddr.ip not in {"127.0.0.1", "::1"} for item in listeners):
            raise MusicError("identity_mismatch", "Локальный канал не принадлежит проверенному процессу Яндекс Музыки")
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
        if len(matches) != 1: raise MusicError("renderer_not_ready", "Не найдено единственное окно плеера Яндекс Музыки")
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
            return {"connected": False, "selected": selected, "enabled": enabled, "error": str(error)[:240] if isinstance(error, ValueError) else "Связь с плеером недоступна", "diagnostics": failure(error)["diagnostics"]}

    def recover(self, cancel=None, observed=None):
        """Rebind only a verified running instance. Never launch, stop or play."""
        with self.lock:
            self._check_connect_cancel(cancel)
            status = observed if observed is not None else self.status()
            if status.get("connected"): return {**status, "reused": True}
            reason = status.get("diagnostics", {}).get("reason", "no_connection")
            try: self.path.unlink(missing_ok=True)
            except OSError:
                return {**status, "error":"Не удалось инвалидировать устаревшее подключение.", "diagnostics":{"reason":"invalid_connection", "phase":"recovery", "dispatched":False}}
            self.scan = (None, 0.0, [])
            try:
                executable = self.executable()
                instances = running(executable)
                candidates = [p for p in instances if debug_port(p)]
                if len(candidates) > 1:
                    raise MusicError("multiple_instances", "Обнаружено несколько CDP-экземпляров Яндекс Музыки. Закройте лишний плеер; подключение не выбиралось наугад.")
                if not candidates:
                    return {**status, "error":"Яндекс Музыка открыта без CDP. Для подключения нужен подтверждённый перезапуск." if instances else "Яндекс Музыка не запущена; CDP-подключение недоступно.", "restart_required": bool(instances), "diagnostics": {"reason": "no_cdp" if instances else "no_process", "previous_reason":reason, "phase": "recovery", "dispatch_attempted": False, "dispatched": False}}
                process = candidates[0]
                data = {"pid": process.pid, "created": process.create_time(), "exe": str(executable), "port": debug_port(process)}
                if type(data["port"]) is not int or not 1 <= data["port"] <= 65535: raise MusicError("invalid_connection", "Неверный CDP-порт процесса Яндекс Музыки.")
                # Recheck PID start/EXE before probing its explicitly declared port.
                current = psutil.Process(data["pid"])
                if abs(current.create_time()-data["created"]) > .01 or not same_file(current.exe(), executable):
                    raise MusicError("stale_pid", "Процесс Яндекс Музыки изменился во время восстановления.")
                self._check_connect_cancel(cancel)
                with self._renderer_for_descriptor(data) as page: state = page.action("status")
                self._check_connect_cancel(cancel)
                self._save_descriptor(data)
                return {"connected": True, "selected": self.store.settings().music_player == "yandex", "enabled": self.store.settings().allow_audio_control,
                        "state": state, "recovered": True, "diagnostics": {"reason": "recovered", "previous_reason": reason, "phase": "recovery", "dispatch_attempted": False, "dispatched": False}}
            except (ValueError, OSError, psutil.Error) as error:
                if isinstance(error, MusicError) and error.reason == "cancelled": raise
                if isinstance(error, psutil.AccessDenied): error = MusicError("access_denied", "Windows не разрешила проверить новый процесс Яндекс Музыки.")
                detail = failure(error)
                return {**status, "error": detail["text"], "diagnostics": detail["diagnostics"]}

    def _save_descriptor(self, data):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self.path)
        self.scan = (None, 0.0, [])

    @staticmethod
    def _check_connect_cancel(cancel):
        if cancel and cancel.is_set(): raise MusicError("cancelled", "Подключение Яндекс Музыки отменено.", "permission")

    def connect_with_cancel(self, restart, cancel):
        # Preserve the public connector contract (also used by existing fakes).
        self.connect_context.cancel = cancel
        try: return self.connect(restart)
        finally: self.connect_context.cancel = None

    def connect(self, restart=False):
        try:
            return self._connect(restart)
        except (psutil.Error, OSError) as error:
            text = "Windows не разрешила доступ к плееру. Закройте Яндекс Музыку вручную и подключите её из WileyAI. Подтвердите запрос Windows, если эта сборка требует прав администратора."
            self.store.audit("music.connect", "yandex", "error", {"text": text, "error": type(error).__name__})
            raise MusicError("access_denied", text) from None
        except ValueError as error:
            self.store.audit("music.connect", "yandex", "error", {"text": str(error)[:300]})
            if isinstance(error, MusicError): raise
            raise MusicError("connection_failed", str(error)[:300]) from None

    def _connect(self, restart=False):
        if not self.store.settings().allow_app_open or not self.store.settings().allow_audio_control:
            raise MusicError("denied", "Разрешите запуск приложений и управление звуком в разделе «Команды»", "permission")
        with self.lock:
            cancel = getattr(self.connect_context, "cancel", None)
            self._check_connect_cancel(cancel)
            # Reuse only a connection that passes every existing process/socket/
            # page check. An ordinary Open must not spawn a replacement process.
            status = self.status()
            if status.get("connected") and not restart:
                self.store.patch_settings({"music_player": "yandex"})
                return {**status, "selected": True, "reused": True, "text": "Использую существующее CDP-подключение Яндекс Музыки."}
            if not restart:
                recovered = self.recover(cancel, status)
                if recovered.get("connected"):
                    self.store.patch_settings({"music_player": "yandex"})
                    return {**recovered, "selected": True, "text": "CDP-подключение Яндекс Музыки восстановлено и проверено."}
                if recovered.get("diagnostics", {}).get("reason") in {"multiple_instances", "identity_mismatch", "access_denied"}:
                    raise MusicError(recovered["diagnostics"]["reason"], recovered.get("error", "Не удалось безопасно восстановить подключение."))
            executable = self.executable()
            self.store.patch_settings({"music_player": "yandex"})
            instances = running(executable)
            process = next((p for p in instances if debug_port(p)), None)
            if instances and (process is None or restart):
                if not restart: return {"connected": False, "selected": True, "restart_required": True, "text": "Плеер уже открыт без локального управления. Подключение потребует перезапуска; музыка остановится."}
                with exit_waiter(instances) as wait:
                    for instance in instances:
                        self._check_connect_cancel(cancel)
                        children = instance.children(recursive=True)
                        for child in [*children, instance]:
                            try:
                                if same_file(child.exe(), executable):
                                    verified = psutil.Process(child.pid)
                                    if abs(verified.create_time()-child.create_time()) > .01 or not same_file(verified.exe(), executable):
                                        raise MusicError("stale_pid", "Процесс изменился перед перезапуском; завершение отклонено.")
                                    self._check_connect_cancel(cancel)
                                    verified.terminate()
                            except psutil.NoSuchProcess: pass
                    if not wait(): raise ValueError("Не удалось закрыть прежний плеер. Завершите его вручную и повторите подключение")
                process = None
            if process is None:
                self._check_connect_cancel(cancel)
                with socket.socket() as reserved:
                    reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
                start_player(executable, port)
                process_deadline = time.monotonic() + 5
                for _ in range(50):
                    self._check_connect_cancel(cancel)
                    if time.monotonic() >= process_deadline: break
                    process = next((p for p in running(executable) if debug_port(p) == port), None)
                    if process: break
                    time.sleep(.1)
                if process is None: raise ValueError("Не удалось подтвердить процесс Яндекс Музыки")
            port = debug_port(process)
            data = {"pid": process.pid, "created": process.create_time(), "exe": str(executable), "port": port}
            self._save_descriptor(data)
            connection_deadline = time.monotonic() + 8
            for _ in range(40):
                self._check_connect_cancel(cancel)
                if time.monotonic() >= connection_deadline: break
                status = self.status()
                if status["connected"]:
                    self.store.patch_settings({"music_player": "yandex"})
                    self.store.audit("music.connect", str(executable), "connected", {"pid": process.pid})
                    return {**status, "selected": True, "text": "Яндекс Музыка подключена. Музыкальные команды адресованы этому плееру."}
                time.sleep(.2)
            raise MusicError("connection_timeout", "Плеер запущен, но подключение не завершено: " + status.get("error", "канал управления недоступен"))

    def disconnect(self):
        with self.lock:
            self.path.unlink(missing_ok=True)
            self.store.patch_settings({"music_player": "auto"})
        return {"connected": False, "selected": False, "text": "Управление Яндекс Музыкой отключено в WileyAI. Плеер продолжает работать."}

    def execute(self, command: MusicAction, cancel=None):
        target = "yandex:" + command.action
        dispatch_attempted = dispatched = False
        selected = None
        phase = "connection"
        def check():
            if cancel and cancel.is_set(): raise MusicError("cancelled", "Команда Яндекс Музыки остановлена", "permission")
            if not self.store.settings().allow_audio_control: raise MusicError("denied", "Управление звуком отключено в разделе «Команды»", "permission")
        try:
            with self.lock, self.renderer() as page:
                check()
                before = page.action("status")
                candidates, expected_id = [], None
                action = command.action
                if action == "play" and not before.get("available"):
                    action = "wave"
                if action in {"search", "select", "search_play"}:
                    phase = "search"
                    if action == "select":
                        selected = command.selection.model_dump()
                        search_id = selected.pop("search_id")
                        active_query = selected.pop("retrieval_query") or command.query.strip()
                    else:
                        # Start with the original text. Only settled, unsuitable
                        # results justify bounded, metadata-grounded alternatives.
                        attempts = [command.query.strip()]
                        for attempt in range(3):
                            check()
                            active_query, search_id = attempts[attempt], uuid.uuid4().hex
                            page.action("search", query=active_query, search_id=search_id)
                            candidates = []
                            for _ in range(40):
                                check()
                                found = page.action("results", query=active_query, search_id=search_id) or {}
                                if found.get("ready"):
                                    # Always score the original request, so a
                                    # fallback cannot launder a guess into proof.
                                    candidates = rank(command.query, found.get("rows", []))
                                    break
                                time.sleep(.15)
                            if candidates and candidates[0].get("match", {}).get("plausible"): break
                            if attempt == 0:
                                attempts.extend(q for q in entity_alternatives(command.query, candidates) if q not in attempts)
                            if attempt + 1 >= len(attempts): break
                        if not candidates or not candidates[0].get("match", {}).get("plausible"):
                            raise MusicError("search_no_results", "В поиске Яндекс Музыки подходящие треки не найдены. Уточните запрос; отсутствие исполнителя в каталоге не проверялось.", "search")
                        ambiguous = not entity_confident(candidates)
                        if action == "search" or ambiguous:
                            choices = [{**row, "search_id": search_id, "retrieval_query": active_query} for row in candidates[:3] if row.get("match", {}).get("plausible")]
                            text = "Найдены песни в Яндекс Музыке. Воспроизведение не запускалось.\n" + "\n".join(f"{n}. {row['artists']} — {row['title']}" for n, row in enumerate(choices, 1)) + "\nСкажите «включи первую», номер или «отмена»."
                            result = {"confirmed": False, "status": "needs_clarification", "candidates": choices, "query": command.query, "text": text}
                            self.store.audit("music.yandex", target, "results" if action == "search" else "ambiguous", result)
                            return result
                        selected = candidates[0]
                    expected_id = selected["id"]
                    # A synthetic element.click() need not activate Electron's
                    # audio context. Dispatch a native pointer after revalidating
                    # the exact fresh result and its hit target on hover.
                    current_track = page.action("status")
                    if action == "select" or current_track.get("id") != expected_id or current_track.get("playing") is not True:
                        selection = {key: selected[key] for key in ("id", "title", "artists")}
                        phase = "selection"
                        for attempt in range(5):
                            check()
                            button = page.action("select_target", query=active_query, search_id=search_id, **selection)
                            if attempt and not button.get("reveal"):
                                break
                            page.hover(button["x"], button["y"])
                            time.sleep(.1)
                        else:
                            raise ValueError("Кнопка найденной песни перекрыта или недоступна. Запуск не отправлен")
                        # Selection still has to be fresh even if this exact song
                        # is already playing. Avoid toggling it to pause.
                        if current_track.get("id") != expected_id or current_track.get("playing") is not True:
                            check(); phase = "dispatch"; dispatch_attempted = True
                            page.pointer(button["x"], button["y"]); dispatched = True
                elif action == "wave":
                    phase = "target"
                    check(); button = page.action("wave_target")
                    if not button.get("already_playing"):
                        check(); phase = "dispatch"; dispatch_attempted = True
                        page.pointer(button["x"], button["y"]); dispatched = True
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
                    check(); phase = "dispatch"; dispatch_attempted = True
                    page.pointer(slider["x"], slider["y"]); dispatched = True
                elif action != "status":
                    check(); phase = "dispatch"; dispatch_attempted = True
                    response = page.action(action); dispatched = True
                phase = "verification"
                progress_start, playback_progress = None, False
                selection_progress_start = None
                identity_matched = metadata_matched = False
                def same_metadata(actual):
                    return all(" ".join(str(actual.get(key, "")).split()).casefold() == " ".join(selected[key].split()).casefold() for key in ("title", "artists"))
                def confirmed(state):
                    nonlocal progress_start, playback_progress, selection_progress_start, identity_matched, metadata_matched
                    if action == "status": return state.get("available", False)
                    if action == "pause": return state.get("playing") is False and state.get("available")
                    if action == "play_pause": return state.get("playing") != before.get("playing")
                    if action in {"next", "previous"}:
                        if not (before.get("id") and state.get("id") and state["id"] != before["id"]): return False
                        if not before.get("playing"): return True
                    if action in {"like", "unlike", "toggle_like"}: return state.get("id") == before.get("id") and state.get("liked") is response.get("wanted")
                    if action in {"volume", "change_volume"}: return state.get("volume") is not None and abs(state["volume"] - desired_volume) <= 3
                    identity_ok = state.get("id") == expected_id if expected_id else bool(state.get("id"))
                    if action in {"select", "search_play"}:
                        identity_matched = bool(identity_ok)
                        metadata_matched = same_metadata(state)
                        identity_ok = identity_ok and metadata_matched
                    if action == "wave" and before.get("id"):
                        identity_ok = identity_ok and (state.get("id") != before["id"] or state.get("wave_playing") is True)
                    if not state.get("available") or not identity_ok or state.get("playing") is not True:
                        progress_start = None
                        playback_progress = False
                        return False
                    position = state.get("position")
                    if type(position) not in {int, float} or not math.isfinite(position) or position < 0:
                        playback_progress = False
                        return False
                    if progress_start is None or position < progress_start:
                        progress_start = position
                        if action in {"select", "search_play"}: selection_progress_start = position
                    playback_progress = position - progress_start >= .15
                    return playback_progress
                after = page.action("status")
                for _ in range(25):
                    check()
                    if confirmed(after): break
                    time.sleep(.1); after = page.action("status")
                verified = bool(confirmed(after))
                detail = " — ".join(part for part in (after.get("artists"), after.get("title")) if part)
                change = ("Воспроизведение" if after.get("playing") else "Пауза") if after.get("available") else "Нет выбранного трека"
                if action in {"like", "unlike", "toggle_like"}: change = "В любимых" if after.get("liked") else "Убрано из любимых"
                if action in {"volume", "change_volume"}: change = f"Громкость плеера: {after.get('volume')}%"
                text = ("Яндекс Музыка подтвердила: " if verified else "Изменение в Яндекс Музыке не подтверждено. Прочитанное состояние: ") + change + (". " + detail if detail else "")
                result = {"confirmed": verified, "state": after, "text": text, "diagnostics": {"reason": "confirmed" if verified else "playback_unconfirmed", "phase": phase, "dispatch_attempted": dispatch_attempted, "dispatched": dispatched}}
                if action in {"search_play", "select"}:
                    result["selected"] = {key: selected[key] for key in ("id", "title", "artists")}
                    result["playback_progress"] = playback_progress
                    reason = "confirmed" if verified else "track_id_mismatch" if not identity_matched else "track_metadata_mismatch" if not metadata_matched else "not_playing" if after.get("playing") is not True else "position_not_advancing"
                    result.update(query=command.query, search_id=search_id, verification={"reason":reason, "expected":result["selected"],
                        "actual":{key:after.get(key) for key in ("id", "title", "artists", "playing", "position")},
                        "position_start":selection_progress_start, "playback_progress":playback_progress})
                    result["diagnostics"]["reason"] = reason
                    result["text"] = (
                        "Найдена и воспроизводится в Яндекс Музыке: " + detail + ". Плеер подтвердил трек и продвижение воспроизведения."
                        if verified else "Найдена песня: " + selected["artists"] + " — " + selected["title"] + ". Запуск этой песни не подтверждён: плеер не показал выбранный трек с продвижением воспроизведения."
                    )
                if action in {"play", "wave", "next", "previous"}:
                    result["playback_progress"] = playback_progress
                if action == "wave":
                    result["text"] = ("Моя волна воспроизводится: " + detail + ". Плеер подтвердил продвижение воспроизведения." if verified else "Запуск «Моей волны» отправлен, но воспроизведение не подтверждено. Автоматический повтор не выполнялся.")
                self.store.audit("music.yandex", target, "confirmed" if verified else "unconfirmed", result)
                return result
        except Exception as error:
            transport_error = not isinstance(error, ValueError) or (isinstance(error, MusicError) and error.reason in {"cdp_unavailable", "cdp_timeout", "cdp_rejected"})
            if phase == "dispatch" and transport_error:
                error = MusicError("click_failed", "Результат отправки нажатия в Яндекс Музыку неизвестен. Воспроизведение не подтверждено; повтор не отправлялся.", phase)
            elif phase == "verification" and transport_error:
                error = MusicError("verification_unavailable", "Связь прервана при проверке результата воспроизведения.", phase)
            elif not isinstance(error, ValueError):
                error = MusicError("cdp_unavailable", "Связь с Яндекс Музыкой потеряна. Проверьте подключение в разделе «Команды»", phase)
            if isinstance(error, MusicError):
                error.dispatch_attempted, error.dispatched = dispatch_attempted, dispatched
                if command.action in {"select", "search_play"} and selected:
                    error.verification = {"reason":error.reason, "expected":{k:selected[k] for k in ("id", "title", "artists")}, "actual":None,
                                          "query":command.query, "search_id":search_id}
            self.store.audit("music.yandex", target, "error", {"text": str(error)[:300], "diagnostics": failure(error)["diagnostics"], **({"verification":error.verification} if isinstance(error, MusicError) and error.verification else {})})
            raise error from None


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
