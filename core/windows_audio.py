"""Small Windows Core Audio/SendInput adapter; no extra runtime or shell scripts."""
from contextlib import contextmanager
import ctypes as c
import os
import uuid


class GUID(c.Structure):
    _fields_ = [("data1", c.c_uint32), ("data2", c.c_uint16), ("data3", c.c_uint16), ("data4", c.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def check(result):
    if result < 0:
        raise ValueError(f"Windows не предоставила доступ к звуку (0x{result & 0xffffffff:08X}). Проверьте устройство воспроизведения.")


def invoke(pointer, slot, argtypes, *args):
    # Slots/signatures follow the Windows SDK's IMMDeviceEnumerator,
    # IMMDevice and IAudioEndpointVolume interfaces (see docs/device-audio.ru.md).
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    method = c.WINFUNCTYPE(c.c_int32, c.c_void_p, *argtypes)(table[slot])
    result = method(pointer, *args)
    check(result)


def release(pointer):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    c.WINFUNCTYPE(c.c_uint32, c.c_void_p)(table[2])(pointer)


@contextmanager
def endpoint():
    if os.name != "nt":
        raise ValueError("Управление звуком доступно в Windows")
    ole = c.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [c.c_void_p, c.c_uint32]
    ole.CoInitializeEx.restype = c.c_int32
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, c.c_uint32, c.POINTER(GUID), c.POINTER(c.c_void_p)]
    ole.CoCreateInstance.restype = c.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 0)
    if initialized != -2147417850:  # RPC_E_CHANGED_MODE: reuse this thread's apartment.
        check(initialized)
    enumerator, device, volume = c.c_void_p(), c.c_void_p(), c.c_void_p()
    try:
        clsid = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
        iid = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
        check(ole.CoCreateInstance(c.byref(clsid), None, 23, c.byref(iid), c.byref(enumerator)))
        invoke(enumerator, 4, [c.c_int, c.c_int, c.POINTER(c.c_void_p)], 0, 1, c.byref(device))
        iid = GUID.parse("5CDF2C82-841E-4546-9722-0CF74078229A")
        invoke(device, 3, [c.POINTER(GUID), c.c_uint32, c.c_void_p, c.POINTER(c.c_void_p)], c.byref(iid), 23, None, c.byref(volume))
        yield Endpoint(volume)
    finally:
        # Release returns ULONG, not HRESULT. Release all acquired references even
        # when device discovery or activation failed part way through.
        for pointer in (volume, device, enumerator):
            if pointer:
                release(pointer)
        if initialized >= 0:
            ole.CoUninitialize()


class Endpoint:
    def __init__(self, pointer):
        self.pointer = pointer

    def read(self):
        level, muted = c.c_float(), c.c_int32()
        invoke(self.pointer, 9, [c.POINTER(c.c_float)], c.byref(level))
        invoke(self.pointer, 15, [c.POINTER(c.c_int32)], c.byref(muted))
        return {"volume": max(0, min(100, round(level.value * 100))), "muted": bool(muted.value)}

    def set_volume(self, value):
        invoke(self.pointer, 7, [c.c_float, c.c_void_p], value / 100, None)

    def set_mute(self, value):
        invoke(self.pointer, 14, [c.c_int32, c.c_void_p], int(value), None)


class KeyboardInput(c.Structure):
    _fields_ = [("vk", c.c_uint16), ("scan", c.c_uint16), ("flags", c.c_uint32), ("time", c.c_uint32), ("extra", c.c_size_t)]


class MouseInput(c.Structure):
    _fields_ = [("x", c.c_int32), ("y", c.c_int32), ("data", c.c_uint32), ("flags", c.c_uint32), ("time", c.c_uint32), ("extra", c.c_size_t)]


class InputData(c.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(c.Structure):
    _fields_ = [("type", c.c_uint32), ("data", InputData)]


MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def send_media(action):
    if os.name != "nt":
        raise ValueError("Медиаклавиши доступны в Windows")
    key = MEDIA_KEYS[action]
    user = c.WinDLL("user32", use_last_error=True)
    user.SendInput.argtypes = [c.c_uint32, c.POINTER(Input), c.c_int]
    user.SendInput.restype = c.c_uint32
    inputs = (Input * 2)(
        Input(type=1, data=InputData(keyboard=KeyboardInput(vk=key))),
        Input(type=1, data=InputData(keyboard=KeyboardInput(vk=key, flags=2))),
    )
    sent = user.SendInput(2, inputs, c.sizeof(Input))
    if sent != 2:
        # If key-down alone succeeded, make a best-effort key-up before reporting.
        if sent == 1:
            user.SendInput(1, c.byref(inputs[1]), c.sizeof(Input))
        raise ValueError("Windows не приняла медиаклавишу. Проверьте активный проигрыватель и его уровень доступа.")
