"""Opt-in pytest guard for fixture-only command regressions: -p scripts.semantic_test_safety.

Block the native boundaries, so tests may still replace them with explicit fakes.
No product permissions or production validators are changed.
"""
import ctypes
from contextlib import contextmanager
import pytest
from core import commands, launch_verification, windows_media


@contextmanager
def isolated_boundaries(*, local_model_url=None):
    """Standalone benchmark guard; fake executors may override these boundaries.

    Record attempted escapes even when an API catches the raised exception.
    Restore every patch on exit; never alter production permissions/validators.
    """
    import httpx
    import os
    import subprocess
    import urllib.request
    import keyring
    from urllib.parse import urlparse
    import websockets.sync.client
    from core import audio_sessions, windows_audio
    from core.yandex_music import YandexMusic
    blocked_calls = []
    def block(name):
        def blocked(*args, **kwargs):
            blocked_calls.append(name)
            raise RuntimeError("Unmocked boundary forbidden in intent benchmark: " + name)
        return blocked
    with pytest.MonkeyPatch.context() as patch:
        for obj, name in [(commands, "execute"), (commands.webbrowser, "open"), (os, "system"),
                          (launch_verification, "shell_launch"), (subprocess, "Popen"),
                          (ctypes, "WinDLL"), (windows_media, "perform"), (windows_media, "perform_selected"),
                          (audio_sessions, "set_volume"), (windows_audio, "endpoint"),
                          (YandexMusic, "renderer"), (YandexMusic, "connect"), (YandexMusic, "execute"),
                          (urllib.request, "urlopen"), (keyring, "get_password")]:
            patch.setattr(obj, name, block(name), raising=False)
        patch.setattr(os, "startfile", block("startfile"), raising=False)
        # HTTP TestClient is an in-process ASGI transport, not a network client.
        send = httpx.Client.send
        def only_test_transport(client, *args, **kwargs):
            if type(client._transport).__module__ != "starlette.testclient":
                return block("httpx.Client.send")()
            return send(client, *args, **kwargs)
        patch.setattr(httpx.Client, "send", only_test_transport)
        native_async_send = httpx.AsyncClient.send
        allowed = urlparse(local_model_url or "")
        if local_model_url and (allowed.scheme != "http" or allowed.hostname not in {"127.0.0.1", "::1", "localhost"} or not allowed.port or allowed.path not in {"", "/"}):
            raise ValueError("Only an explicit loopback Ollama endpoint is permitted")
        async def local_inference_only(client, request, *args, **kwargs):
            url = urlparse(str(request.url))
            if local_model_url and request.method == "POST" and url.scheme == allowed.scheme and url.hostname == allowed.hostname and url.port == allowed.port and url.path == "/api/chat" and not url.query:
                return await native_async_send(client, request, *args, **kwargs)
            return block("httpx.AsyncClient.send")()
        patch.setattr(httpx.AsyncClient, "send", local_inference_only)
        patch.setattr(websockets.sync.client, "connect", block("websockets.connect"))
        patch.setattr(keyring, "set_password", block("keyring.set_password"))
        patch.setattr(keyring, "delete_password", block("keyring.delete_password"))
        yield blocked_calls


@pytest.fixture(autouse=True)
def forbid_owner_actions(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("An unmocked real OS action is forbidden in semantic-command tests")
    monkeypatch.setattr(commands.webbrowser, "open", blocked)
    monkeypatch.setattr(commands.os, "startfile", blocked, raising=False)
    monkeypatch.setattr(launch_verification, "shell_launch", blocked)
    monkeypatch.setattr(launch_verification, "visible_windows", lambda pids: {})
    monkeypatch.setattr(ctypes, "WinDLL", blocked)
    monkeypatch.setattr(windows_media, "perform", lambda action="read": {"available": False} if action == "read" else blocked())
