"""Per-worker dispatch notification; not a command or user-controlled callback."""
from contextlib import contextmanager
from contextvars import ContextVar

_callback = ContextVar("wiley_dispatch_callback", default=None)


@contextmanager
def notify_with(callback):
    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)


def started():
    callback = _callback.get()
    if callback is not None:
        callback()
