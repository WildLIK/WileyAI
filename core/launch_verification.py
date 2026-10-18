"""Windows dispatch with bounded verification of the exact application executable."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import time
import subprocess

import psutil

from .app_discovery import shortcut_targets, local_file


class ExecutionText(str):
    def __new__(cls, text, evidence):
        value = super().__new__(cls, text)
        value.evidence = {"text": text, **evidence}
        return value


def process_ids(executable):
    expected = os.path.normcase(os.path.realpath(executable))
    result = set()
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            actual = process.info.get("exe")
            if actual and os.path.normcase(os.path.realpath(actual)) == expected:
                result.add(process.info["pid"])
        except (psutil.Error, OSError):
            continue
    return result


def shell_launch(target):
    class ShellInfo(c.Structure):
        _fields_ = [("cbSize", w.DWORD), ("fMask", w.ULONG), ("hwnd", w.HWND),
                    ("lpVerb", w.LPCWSTR), ("lpFile", w.LPCWSTR), ("lpParameters", w.LPCWSTR),
                    ("lpDirectory", w.LPCWSTR), ("nShow", c.c_int), ("hInstApp", w.HINSTANCE),
                    ("lpIDList", c.c_void_p), ("lpClass", w.LPCWSTR), ("hkeyClass", w.HKEY),
                    ("dwHotKey", w.DWORD), ("hIcon", w.HANDLE), ("hProcess", w.HANDLE)]
    shell = c.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [c.POINTER(ShellInfo)]
    shell.ShellExecuteExW.restype = w.BOOL
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    # NOCLOSEPROCESS | NOASYNC | FLAG_NO_UI: no shell commands or extra parameters.
    info = ShellInfo(cbSize=c.sizeof(ShellInfo), fMask=0x40 | 0x100 | 0x400, lpFile=str(target), nShow=1)
    ole = c.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [c.c_void_p, w.DWORD]
    ole.CoInitializeEx.restype = c.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 2 | 4)
    if initialized < 0 and initialized != -2147417850:
        raise ValueError("Windows не предоставила контекст запуска приложения")
    try:
        if not shell.ShellExecuteExW(c.byref(info)):
            raise ValueError(f"Windows отклонила запуск (код {c.get_last_error()}).")
    finally:
        if info.hProcess: kernel.CloseHandle(info.hProcess)
        if initialized >= 0: ole.CoUninitialize()


def application(target, label):
    expected = local_file(target)
    if Path(target).suffix.casefold() == ".lnk":
        try:
            expected = local_file(shortcut_targets([Path(target)]).get(str(target)))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            expected = None
    before = process_ids(expected) if expected else set()
    shell_launch(target)
    found = set()
    if expected:
        deadline = time.monotonic() + 3
        while True:
            found = process_ids(expected)
            if found or time.monotonic() >= deadline:
                break
            time.sleep(.15)
    if found:
        new = found - before
        pid = min(new or found)
        status = "process_started" if new else "already_running"
        text = f"Процесс {'запущен и подтверждён' if new else 'уже работает'}: {label}. PID {pid}.\nПроверенный EXE: {expected}"
        return ExecutionText(text, {"status": status, "pid": pid, "executable": str(expected)})
    text = f"Windows приняла запрос запуска: {label}. Процесс за 3 секунды не подтверждён.\nПуть: {target}. Окно или работоспособность программы не проверены."
    return ExecutionText(text, {"status": "dispatched", "executable": str(expected) if expected else None})
