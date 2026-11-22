"""Default-render-device mixer sessions. No matching by display-name similarity."""
from contextlib import contextmanager
import ctypes as c
import os
import hashlib

import psutil
from .windows_audio import GUID, check, invoke, release


def query(pointer, iid):
    result = c.c_void_p()
    value = GUID.parse(iid)
    invoke(pointer, 0, [c.POINTER(GUID), c.POINTER(c.c_void_p)], c.byref(value), c.byref(result))
    return result


@contextmanager
def sessions():
    if os.name != "nt":
        raise ValueError("Микшер приложений доступен в Windows")
    ole = c.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [c.c_void_p, c.c_uint32]; ole.CoInitializeEx.restype = c.c_int32
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, c.c_uint32, c.POINTER(GUID), c.POINTER(c.c_void_p)]; ole.CoCreateInstance.restype = c.c_int32
    ole.CoTaskMemFree.argtypes = [c.c_void_p]; ole.CoTaskMemFree.restype = None
    ole.CoUninitialize.argtypes = []; ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 0)
    if initialized != -2147417850: check(initialized)
    pointers = []
    def keep(pointer): pointers.append(pointer); return pointer
    def string(pointer, slot):
        value = c.c_void_p()
        invoke(pointer, slot, [c.POINTER(c.c_void_p)], c.byref(value))
        try: return c.wstring_at(value) if value else ""
        finally:
            if value: ole.CoTaskMemFree(value)
    try:
        enum = keep(c.c_void_p())
        check(ole.CoCreateInstance(c.byref(GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 23, c.byref(GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")), c.byref(enum)))
        device = keep(c.c_void_p())
        invoke(enum, 4, [c.c_int, c.c_int, c.POINTER(c.c_void_p)], 0, 1, c.byref(device))
        manager = keep(c.c_void_p())
        invoke(device, 3, [c.POINTER(GUID), c.c_uint32, c.c_void_p, c.POINTER(c.c_void_p)], c.byref(GUID.parse("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")), 23, None, c.byref(manager))
        enumerator = keep(c.c_void_p())
        invoke(manager, 5, [c.POINTER(c.c_void_p)], c.byref(enumerator))
        count = c.c_int(); invoke(enumerator, 3, [c.POINTER(c.c_int)], c.byref(count))
        rows = []
        for index in range(min(count.value, 128)):
            control = keep(c.c_void_p())
            invoke(enumerator, 4, [c.c_int, c.POINTER(c.c_void_p)], index, c.byref(control))
            try:
                control2 = keep(query(control, "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"))
                pid = c.c_uint32()
                table = c.cast(control2, c.POINTER(c.POINTER(c.c_void_p))).contents
                # AUDCLNT_S_NO_SINGLE_PROCESS is success with a nonzero code:
                # such shared sessions must never be changed by PID.
                hr = c.WINFUNCTYPE(c.c_int32, c.c_void_p, c.POINTER(c.c_uint32))(table[14])(control2, c.byref(pid))
                if hr != 0 or not pid.value: continue
                process = psutil.Process(pid.value)
                executable, created = process.exe(), process.create_time()
                instance = string(control2, 13)
                state = c.c_int(); invoke(control, 3, [c.POINTER(c.c_int)], c.byref(state))
                if state.value == 2: continue  # Expired.
                volume = keep(query(control, "87CE5498-68D6-44E5-9215-6DA47EF883D8"))
                level, mute = c.c_float(), c.c_int32()
                invoke(volume, 4, [c.POINTER(c.c_float)], c.byref(level))
                invoke(volume, 6, [c.POINTER(c.c_int32)], c.byref(mute))
                rows.append(({"id": hashlib.sha256(instance.encode()).hexdigest(), "pid": pid.value, "created": created, "executable": executable, "active": state.value == 1, "volume": round(level.value * 100), "muted": bool(mute.value)}, volume))
            except (ValueError, OSError, psutil.Error):
                continue
        yield rows
    finally:
        for pointer in reversed(pointers):
            if pointer: release(pointer)
        if initialized >= 0: ole.CoUninitialize()


def snapshot():
    with sessions() as rows:
        return [row for row, _ in rows]


def app_id(pid):
    """OS-provided application identity, not a guessed process display name."""
    if os.name != "nt": return ""
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [c.c_uint32, c.c_int32, c.c_uint32]; kernel.OpenProcess.restype = c.c_void_p
    kernel.GetApplicationUserModelId.argtypes = [c.c_void_p, c.POINTER(c.c_uint32), c.c_wchar_p]; kernel.GetApplicationUserModelId.restype = c.c_long
    kernel.CloseHandle.argtypes = [c.c_void_p]; kernel.CloseHandle.restype = c.c_int32
    handle = kernel.OpenProcess(0x1000, 0, pid)
    if not handle: return ""
    try:
        length = c.c_uint32()
        if kernel.GetApplicationUserModelId(handle, c.byref(length), None) != 122 or not 0 < length.value < 1024: return ""
        text = c.create_unicode_buffer(length.value)
        return text.value if kernel.GetApplicationUserModelId(handle, c.byref(length), text) == 0 else ""
    finally: kernel.CloseHandle(handle)


def set_volume(session_id, executable, created, value, relative=True):
    """Re-enumerate and revalidate the exact session/process before one write."""
    with sessions() as rows:
        selected = [(row, pointer) for row, pointer in rows if row["id"] == session_id and os.path.normcase(os.path.realpath(row["executable"])) == os.path.normcase(os.path.realpath(executable)) and row["created"] == created]
        if len(selected) != 1: raise ValueError("Аудиосессия изменилась. Повторите команду.")
        row, pointer = selected[0]
        try:
            process = psutil.Process(row["pid"])
            valid = process.create_time() == created and os.path.normcase(os.path.realpath(process.exe())) == os.path.normcase(os.path.realpath(executable))
        except psutil.Error as error:
            raise ValueError("Процесс аудиосессии завершился или стал недоступен") from error
        if not valid:
            raise ValueError("Процесс аудиосессии изменился")
        desired = max(0, min(100, row["volume"] + value if relative else value))
        invoke(pointer, 3, [c.c_float, c.c_void_p], desired / 100, None)
        level = c.c_float(); invoke(pointer, 4, [c.POINTER(c.c_float)], c.byref(level))
        after = round(level.value * 100)
        if abs(after - desired) > 1: raise ValueError("Микшер Windows не подтвердил изменение громкости приложения")
        return {**row, "volume": after, "confirmed": True, "scope": "application_mixer"}
