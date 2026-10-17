import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@pytest.mark.parametrize("stopped", ["owner", "guard", "service"])
def test_owned_grandchildren_exit_even_when_owner_or_guard_is_killed(tmp_path, stopped):
    project = Path(__file__).resolve().parents[1]
    ready, stop = tmp_path / "ready.json", tmp_path / "stop"
    service = tmp_path / "service with spaces.py"
    service.write_text('''import json,os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"])
Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))
while not Path(sys.argv[2]).exists():time.sleep(.05)
''', encoding="utf-8")
    owner = tmp_path / "owner.py"
    owner.write_text('''import subprocess,sys,os,time
from pathlib import Path
guard=subprocess.Popen([sys.executable,"-m","core.process_guard",str(os.getpid()),sys.executable,sys.argv[1],sys.argv[2],sys.argv[3]])
Path(sys.argv[4]).write_text(str(guard.pid))
time.sleep(120)
''', encoding="utf-8")
    guard_file = tmp_path / "guard.txt"
    parent = subprocess.Popen([sys.executable, str(owner), str(service), str(ready), str(stop), str(guard_file)], cwd=project,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    processes = []
    try:
        for _ in range(100):
            try:
                pids = [int(guard_file.read_text()), *json.loads(ready.read_text())]
                break
            except (FileNotFoundError, ValueError): time.sleep(.05)
        else:
            parent.terminate()
            pytest.fail(parent.communicate(timeout=5)[1].decode(errors="replace"))
        processes = [psutil.Process(pid) for pid in pids]
        assert all(p.is_running() for p in processes)
        if stopped == "owner": parent.terminate()
        elif stopped == "guard": processes[0].terminate()
        else: stop.touch()
        _, alive = psutil.wait_procs(processes, timeout=8)
        assert not alive, [(p.pid, p.name()) for p in alive]
    finally:
        if parent.poll() is None: parent.terminate()
        parent.communicate(timeout=5)
        for p in processes:
            try: p.kill()
            except psutil.NoSuchProcess: pass


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
def test_guard_preserves_core_readiness_stdout_and_diagnostics_stderr():
    command = [sys.executable, "-m", "core.process_guard", str(os.getpid()), sys.executable, "-c",
               "import sys; print('ready-url', flush=True); print('diagnostic',file=sys.stderr,flush=True)"]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    assert result.stdout.strip() == b"ready-url" and result.stderr.strip() == b"diagnostic"
