"""Real TCP HTTP/SSE with the exact Java source shipped in Android, not a mock transport."""
from pathlib import Path
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from gateway.app import create_app
from gateway.store import Store, new_id

ROOT = Path(__file__).resolve().parents[1]


def test_android_java_transport_over_real_http_sse(tmp_path):
    binaries = Path(os.environ.get("JAVA_HOME", "")) / "bin"
    javac = str(binaries / "javac.exe") if (binaries / "javac.exe").exists() else shutil.which("javac")
    java = str(binaries / "java.exe") if (binaries / "java.exe").exists() else shutil.which("java")
    if not java or not javac:
        pytest.skip("JDK 17 required for Android Gateway wire acceptance")
    classes = tmp_path / "classes"
    classes.mkdir()
    files = [ROOT / "android/app/src/main/java/ru/wildlik/wileyai/mobile/GatewayWire.java", ROOT / "tests/android/GatewayWireProbe.java"]
    compile_result = subprocess.run([javac, "-encoding", "UTF-8", "-d", str(classes), *map(str, files)], capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    key = secrets.token_bytes(32)
    store = Store(tmp_path / "server", key)
    token = store.token(new_id())
    app = create_app(store.root, key, test_mode=True, development=True, store=store)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", log_level="critical", access_log=False, ws="none"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    address = f"http://127.0.0.1:{sock.getsockname()[1]}"
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        result = subprocess.run([java, "-cp", str(classes), "GatewayWireProbe", address], env={**os.environ, "WILEY_GATEWAY_TEST_TOKEN": token}, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "NETWORK_SSE_HISTORY_REPLAY_OK" in result.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
