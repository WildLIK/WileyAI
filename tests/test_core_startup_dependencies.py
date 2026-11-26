"""The local core and passive Telegram status do not load optional inference and RPC clients."""
from pathlib import Path
import subprocess
import sys


def test_local_startup_leaves_optional_dependencies_unloaded(tmp_path):
    script = """
from pathlib import Path
import sys
from core.api import create_app
from fastapi.testclient import TestClient

app = create_app(Path(sys.argv[1]), token="isolated-startup-credential")
client = TestClient(app, headers={"Authorization": "Bearer isolated-startup-credential"})
assert client.get("/health").status_code == 200
assert client.get("/telegram/status").status_code == 200
assert not {"telethon", "numpy"} & sys.modules.keys(), {"telethon", "numpy"} & sys.modules.keys()

from core.semantic import scores
assert scores([[1, 0], [0, 1]], [1, 0]) == [1, 0]
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], timeout=25, check=True,
    )
