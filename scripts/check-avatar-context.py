"""Read-only live Windows smoke: isolated loopback core, native audio levels, no playback."""
import json
import os
import secrets
import socket
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.api import create_app


def main():
    if os.name != 'nt':
        raise SystemExit('Requires Windows Core Audio')
    with tempfile.TemporaryDirectory() as temp, socket.socket() as sock:
        secret = secrets.token_urlsafe(32)
        app = create_app(Path(temp), token=secret)
        meter = app.state.music_meter
        sock.bind(('127.0.0.1', 0))
        url = 'http://127.0.0.1:%s/avatar/music' % sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            with httpx.Client(timeout=5, trust_env=False) as client:
                unauthorized = client.get(url).status_code
                frames, samples, revisions = [], [], set()
                t0 = time.perf_counter()
                with client.stream('GET', url, headers={'Authorization':'Bearer '+secret}) as res:
                    res.raise_for_status()
                    for line in res.iter_lines():
                        if not line.startswith('data: '): continue
                        data = json.loads(line[6:]); now = time.perf_counter(); frames.append(now)
                        if data['observation'] == 'sample' and data['fresh_ms'] > 0:
                            samples.append(now); revisions.add(data['revision'])
                        if len(frames) >= 40: break
            deadline = time.monotonic() + 4
            while (meter.clients or meter.thread is not None) and time.monotonic() < deadline:
                time.sleep(.02)
            print(json.dumps(dict(no_auth=unauthorized, frames=len(frames), samples=len(samples),
                distinct_samples=len(revisions), first_sample_ms=round(1000*(samples[0]-t0)) if samples else None,
                median_frame_gap_ms=round(1000*statistics.median(b-a for a,b in zip(frames,frames[1:])),1),
                clients_after=meter.clients, worker_stopped=meter.thread is None)))
            if unauthorized != 401 or len(revisions)<2 or meter.clients or meter.thread is not None:
                raise SystemExit('Native SSE smoke did not pass')
        finally:
            server.should_exit = True; thread.join(4); meter.close()

if __name__ == '__main__':
    main()
