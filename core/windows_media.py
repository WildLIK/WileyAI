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
    rows = sessions()
    playing = [row for row in rows if row.get("state") in {"Playing", "Воспроизведение"}]
    choices = playing or rows
    if not choices: return {"available": False}
    if len(choices) != 1: raise ValueError("Несколько проигрывателей. Выберите источник в WileyAI.")
    selected = choices[0]
    return selected if action == "read" else perform_selected(selected["id"], action)


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


# Unlike the legacy current-session adapter, this path enumerates all sessions
# and dispatches only to an exact unique SourceAppUserModelId selected afresh.
SESSIONS_SCRIPT = SMTC_SCRIPT[:SMTC_SCRIPT.index('$session=$manager.GetCurrentSession()')] + r'''
$all=@($manager.GetSessions())
function Properties($s) {
 try { $p=Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]); return @{title=$p.Title;artist=$p.Artist} }
 catch { return @{title='';artist=''} }
}
function DescribeSession($s) {
 $info=$s.GetPlaybackInfo(); $controls=$info.Controls
 $caps=@(); foreach($entry in @(@('play','IsPlayEnabled'),@('pause','IsPauseEnabled'),@('play_pause','IsPlayPauseToggleEnabled'),@('stop','IsStopEnabled'),@('next','IsNextEnabled'),@('previous','IsPreviousEnabled'))) {
  if($controls.($entry[1])) {$caps+= $entry[0]}
 }
 $track=Properties $s
 return @{id=('smtc:'+$s.SourceAppUserModelId);app_id=$s.SourceAppUserModelId;player=$s.SourceAppUserModelId;state=$info.PlaybackStatus.ToString();commands=@($caps);track=$track;backend='smtc';available=$true;current=($s -eq $manager.GetCurrentSession())}
}
if($command.action -eq 'sessions') {
 $rows=@($all | Select-Object -First 24 | ForEach-Object { DescribeSession $_ })
 @{sessions=$rows} | ConvertTo-Json -Depth 6 -Compress
 exit
}
$matches=@($all | Where-Object { ('smtc:'+$_.SourceAppUserModelId) -ceq $command.session_id })
if($matches.Count -ne 1) {throw 'Медиасессия исчезла или стала неоднозначной'}
$session=$matches[0]; $before=DescribeSession $session
if($before.commands -notcontains $command.action) {throw 'Плеер не разрешил эту команду'}
$desired=@{play='Playing';pause='Paused';stop='Stopped'}[$command.action]
if($command.action -eq 'play_pause') {$desired=if($before.state -eq 'Playing') {'Paused'} else {'Playing'}}
$accepted=$false
if($desired -and $before.state -eq $desired) {$accepted=$true} else {
 switch($command.action) {
  'play' {$accepted=Await ($session.TryPlayAsync()) ([bool])}
  'pause' {$accepted=Await ($session.TryPauseAsync()) ([bool])}
  'play_pause' {$accepted=Await ($session.TryTogglePlayPauseAsync()) ([bool])}
  'stop' {$accepted=Await ($session.TryStopAsync()) ([bool])}
  'next' {$accepted=Await ($session.TrySkipNextAsync()) ([bool])}
  'previous' {$accepted=Await ($session.TrySkipPreviousAsync()) ([bool])}
  default {throw 'Неизвестная команда'}
 }
}
$after=DescribeSession $session
for($i=0;$accepted -and $desired -and $after.state -ne $desired -and $i -lt 5;$i++) {Start-Sleep -Milliseconds 100;$after=DescribeSession $session}
$confirmed=($accepted -and $desired -and $after.state -eq $desired)
if($command.action -in @('next','previous')) {$confirmed=$accepted -and ($before.track.title -or $before.track.artist) -and (($after.track.title -ne $before.track.title) -or ($after.track.artist -ne $before.track.artist))}
$after.accepted=[bool]$accepted; $after.confirmed=[bool]$confirmed; $after.action=$command.action
$after | ConvertTo-Json -Depth 6 -Compress
} catch { exit 3 }
'''


def session_request(action, session_id=""):
    if os.name != "nt": raise Unavailable("Медиасессии доступны в Windows")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", SESSIONS_SCRIPT], input=json.dumps({"action": action, "session_id": session_id}), capture_output=True, encoding="utf-8", errors="replace", timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        raise ValueError("Медиасессия не ответила. Повторная команда автоматически не отправляется.") from error
    if result.returncode:
        error = Unavailable if action == "sessions" else ValueError
        raise error("Медиасессия недоступна, изменилась или не поддерживает команду. Автоматический повтор не выполнялся.")
    data = json.loads(result.stdout.lstrip("\ufeff"))
    if not isinstance(data, dict): raise ValueError("Некорректный ответ медиасессий")
    return data


def sessions():
    if os.name != "nt": return []
    rows = []
    try:
        player = Aimp(); row = player.read()
        rows.append({**row, "id": "aimp:" + str(row["pid"]), "app_id": "AIMP", "commands": ["play", "pause", "play_pause", "stop", "next", "previous"], "current": False})
    except (LookupError, ValueError, OSError): pass
    try:
        data = session_request("sessions")
        native = data.get("sessions", [])
        if not isinstance(native, list): raise ValueError("Некорректный список сессий")
        for row in native[:24]:
            if not isinstance(row, dict) or not isinstance(row.get("app_id"), str) or not row["app_id"] or row.get("id") != "smtc:" + row["app_id"]: continue
            if rows and row["app_id"].casefold() in {"aimp", "aimp.exe", rows[0].get("executable", "").casefold()}: continue
            rows.append(row)
    except (ValueError, OSError, json.JSONDecodeError):
        if not rows: raise
    return rows


def perform_selected(session_id, action):
    if action not in {"play", "pause", "play_pause", "stop", "next", "previous"}: raise ValueError("Неизвестная медиакоманда")
    if session_id.startswith("aimp:"):
        player = Aimp()
        if session_id != "aimp:" + str(player.pid): raise Unavailable("Сессия AIMP изменилась")
        return player.perform(action)
    if not session_id.startswith("smtc:"): raise ValueError("Неизвестная медиасессия")
    return session_request(action, session_id)


def track_changed(before, after):
    """Missing/cleared metadata is not evidence of a new composition."""
    first, second = before.get("track") or {}, after.get("track") or {}
    if first.get("id") and second.get("id"):
        return first["id"] != second["id"]
    key = lambda row: tuple(str(row.get(field) or "").strip() for field in ("title", "artist"))
    old, new = key(first), key(second)
    return any(old) and any(new) and old != new


def verify_selected(before, action, check=lambda: None, timeout=2.0):
    """One dispatch, then bounded read-only polling of this exact session.

    Never retry transport commands or switch to another player after dispatch.
    AIMP without track metadata can confirm Play/Pause but cannot confirm Next.
    """
    check()
    began = time.monotonic()
    result = perform_selected(before["id"], action)
    sent_at = time.monotonic()
    accepted = result.get("accepted") is True
    normalize = lambda value: {"Воспроизведение": "Playing", "Пауза": "Paused", "Остановлено": "Stopped"}.get(value, value)
    desired = {"play": "Playing", "pause": "Paused", "stop": "Stopped"}.get(action)
    if action == "play_pause": desired = "Paused" if normalize(before.get("state")) == "Playing" else "Playing"
    def verified(row):
        if not accepted or row.get("available") is False or row.get("id", before["id"]) != before["id"]: return False
        return track_changed(before, row) if action in {"next", "previous"} else bool(desired and normalize(row.get("state")) == desired)
    after = result
    reason = "state_unchanged"
    deadline = time.monotonic() + max(0, timeout)
    while accepted and not verified(after):
        check()
        if action in {"next", "previous"} and not any((before.get("track") or {}).values()):
            reason = "metadata_unavailable"; break
        if time.monotonic() >= deadline: break
        time.sleep(min(.15, max(0, deadline - time.monotonic())))
        check()
        try: matches = [row for row in sessions() if row.get("id") == before["id"]]
        except (ValueError, OSError): reason = "session_unavailable"; break
        if len(matches) != 1: reason = "session_disappeared"; break
        after = matches[0]
    confirmed = bool(verified(after))
    return {**result, **after, "accepted": accepted, "confirmed": confirmed, "action": action,
            "sent": True, "verification": "track_changed" if confirmed and action in {"next", "previous"} else "state_confirmed" if confirmed else reason if accepted else "rejected",
            "before": {key: before.get(key) for key in ("id", "state", "track")},
            "timings": {"dispatch_ms": round((sent_at-began)*1000, 2), "verification_ms": round((time.monotonic()-sent_at)*1000, 2)}}
