"""Isolated Electron fixture: no hardware audio or user player is controlled."""
from core import windows_media

ROWS = [{"id": "smtc:" + name, "app_id": name, "player": name, "state": "Playing", "commands": ["play", "pause", "next"], "available": True, "backend": "smtc", "current": name == "VLC"} for name in ("Spotify", "VLC")]
windows_media.sessions = lambda: [dict(row) for row in ROWS]


def perform(session_id, action):
    row = next(row for row in ROWS if row["id"] == session_id)
    row["state"] = "Paused" if action == "pause" else "Playing"
    return {**row, "accepted": True, "confirmed": True, "pid": 12345}


windows_media.perform_selected = perform
