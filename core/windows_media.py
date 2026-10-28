"""AIMP Remote API and Windows SMTC. State comes from the player, never the LLM."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import time

import psutil


STATES = {0: "Остановлено", 1: "Пауза", 2: "Воспроизведение"}


class Unavailable(ValueError):
    """No player could be reached; no command was sent to it."""


class Aimp:
    def __init__(self):
        self.user = c.WinDLL("user32", use_last_error=True)
        self.user.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
        self.user.FindWindowW.restype = w.HWND
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        self.user.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, c.c_size_t, c.c_ssize_t, w.UINT, w.UINT, c.POINTER(c.c_size_t)]
        self.user.SendMessageTimeoutW.restype = c.c_ssize_t
        self.window = self.user.FindWindowW("AIMP2_RemoteInfo", None)
        if not self.window:
            raise LookupError("AIMP не запущен")
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(self.window, c.byref(pid))
        self.pid = pid.value
        try:
            self.executable = psutil.Process(self.pid).exe()
        except psutil.Error as error:
            raise Unavailable("Не удалось проверить процесс AIMP") from error
        if Path(self.executable).name.casefold() != "aimp.exe":
            raise Unavailable("Окно управления не принадлежит процессу AIMP.exe")

    def send(self, message, value):
        result = c.c_size_t()
        if not self.user.SendMessageTimeoutW(self.window, message, value, 0, 0x2 | 0x1, 700, c.byref(result)):
            raise ValueError("AIMP не ответил. Проверьте, что плеер не завис и запущен с тем же уровнем доступа.")
        return result.value

    def read(self):
        state = self.send(0x477, 0x40)
        if state not in STATES:
            raise ValueError("AIMP вернул неизвестное состояние")
        return {"available": True, "player": "AIMP", "state": STATES[state], "code": state, "pid": self.pid, "executable": self.executable, "backend": "aimp"}

    def perform(self, action):
        try:
            before = self.read()
        except ValueError as error:
            raise Unavailable(str(error)) from error
        desired = {"play": 2, "pause": 1, "stop": 0, "play_pause": 1 if before["code"] == 2 else 2}.get(action)
        if desired is None or before["code"] != desired:
            # AIMP SDK apiRemote.h: pause is a toggle, so never send it if paused/stopped.
            if action != "pause" or before["code"] == 2:
                command = {"play": 13, "play_pause": 14, "pause": 15, "stop": 16, "next": 17, "previous": 18}[action]
                self.send(0x475, command)
        deadline = time.monotonic() + 1
        while True:
            after = self.read()
            if desired is None or after["code"] == desired or time.monotonic() >= deadline:
                break
            time.sleep(.1)
        confirmed = desired is not None and after["code"] == desired
        return {**after, "accepted": True, "confirmed": confirmed, "action": action}


SMTC_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$command=ConvertFrom-Json ([Console]::In.ReadToEnd())
try {
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0]
function Await($operation,[Type]$type) {
  $task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation))
  if(-not $task.Wait(1600)) {throw 'Медиасессия не ответила вовремя'}
  $task.GetAwaiter().GetResult()
}
$manager=Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$session=$manager.GetCurrentSession()
if($null -eq $session) { '{"available":false}';exit }
$accepted=$false
$beforeStatus=$session.GetPlaybackInfo().PlaybackStatus.ToString()
} catch { exit 3 }
switch($command.action) {
 'read' {}
 'play' {$accepted=Await ($session.TryPlayAsync()) ([bool])}
 'pause' {$accepted=Await ($session.TryPauseAsync()) ([bool])}
 'play_pause' {$accepted=Await ($session.TryTogglePlayPauseAsync()) ([bool])}
 'stop' {$accepted=Await ($session.TryStopAsync()) ([bool])}
 'next' {$accepted=Await ($session.TrySkipNextAsync()) ([bool])}
 'previous' {$accepted=Await ($session.TrySkipPreviousAsync()) ([bool])}
 default {throw 'Неизвестная команда'}
}
$status=$session.GetPlaybackInfo().PlaybackStatus.ToString()
$desired=@{play='Playing';pause='Paused';stop='Stopped'}[$command.action]
if($command.action -eq 'play_pause') { $desired=if($beforeStatus -eq 'Playing') {'Paused'} else {'Playing'} }
if($accepted -and $desired) {
 for($i=0;$i -lt 5 -and $status -ne $desired;$i++) {
  Start-Sleep -Milliseconds 100
  $status=$session.GetPlaybackInfo().PlaybackStatus.ToString()
 }
}
@{available=$true;player=$session.SourceAppUserModelId;state=$status;accepted=[bool]$accepted;confirmed=[bool]($desired -and $status -eq $desired);backend='smtc'} | ConvertTo-Json -Compress
'''


def system_session(action):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", SMTC_SCRIPT], input=json.dumps({"action": action}), capture_output=True, encoding="utf-8", errors="replace", timeout=6, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        if action == "read":
            raise Unavailable("Медиасессия Windows не ответила вовремя. Состояние плеера не прочитано.") from error
        raise ValueError("Медиасессия Windows не ответила вовремя. Команда могла дойти до плеера, но его состояние не подтверждено.") from error
    if result.returncode:
        # Exit code 3: the session could not be reached before any command was sent.
        error = Unavailable if result.returncode == 3 or action == "read" else ValueError
        raise error("Не удалось обратиться к медиасессии Windows. Плеер может не поддерживать системное управление.")
    data = json.loads(result.stdout.lstrip("\ufeff"))
    if not isinstance(data, dict) or not isinstance(data.get("available"), bool):
        raise ValueError("Неверный ответ медиасессии Windows")
    data["state"] = {"Playing": "Воспроизведение", "Paused": "Пауза", "Stopped": "Остановлено", "Closed": "Закрыто", "Opened": "Открыто", "Changing": "Переход"}.get(data.get("state"), "Неизвестно")
    if action != "read": data["action"] = action
    return data


def perform(action="read"):
    if action not in {"read", "play", "pause", "play_pause", "stop", "next", "previous"}:
        raise ValueError("Неизвестная медиакоманда")
    if os.name != "nt":
        raise Unavailable("Управление проигрывателем доступно в Windows")
    try:
        player = Aimp()
    except LookupError:
        return system_session(action)
    return player.read() if action == "read" else player.perform(action)


def describe(result):
    if not result.get("available"):
        return "Доступный проигрыватель не найден. Откройте плеер и добавьте трек. Команда воспроизведения не отправлена."
    prefix = "Плеер подтвердил состояние" if result.get("confirmed") else "Прочитанное состояние плеера"
    text = f"{prefix}: {result['player']} — {result['state']}."
    if result.get("pid"):
        text += f" PID {result['pid']}."
    if "action" in result and not result.get("confirmed"):
        text += " Запрошенное изменение не подтверждено."
    if "action" in result and result.get("backend") == "smtc" and result.get("accepted") is False:
        text += " Плеер не принял команду."
    return text
