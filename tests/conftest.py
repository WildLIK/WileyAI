"""New media backends must never control the owner's running players in tests.

Manager tests replace these with stateful fakes. Native-adapter tests call their
captured adapter functions with mocked COM/subprocess boundaries.
"""
import pytest
from core import audio_sessions, windows_media


@pytest.fixture(autouse=True)
def isolated_media_backends(monkeypatch):
    monkeypatch.setattr(windows_media, "sessions", lambda: [])
    monkeypatch.setattr(audio_sessions, "snapshot", lambda: [])
    def unexpected(*args, **kwargs):
        pytest.fail("A native media mutation was not explicitly mocked")
    monkeypatch.setattr(windows_media, "perform_selected", unexpected)
    monkeypatch.setattr(audio_sessions, "set_volume", unexpected)
