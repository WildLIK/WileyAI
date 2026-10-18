"""Real local CDP transport against an isolated Electron fixture, never a personal player."""
import os
from pathlib import Path
import socket
import subprocess
import time
from unittest.mock import patch

import psutil
import pytest
from core.music_intents import MusicAction
from core.storage import Store
from core.yandex_music import YandexMusic


@pytest.mark.skipif(os.name != "nt", reason="Windows Electron fixture")
def test_real_electron_transport_and_player_readback(tmp_path):
    executable = Path(__file__).resolve().parents[1] / "node_modules/electron/dist/electron.exe"
    if not executable.is_file(): pytest.skip("Install npm dependencies for the Electron transport test")
    resources = tmp_path / "resources"; resources.mkdir()
    html = resources / "index.html"
    html.write_text('''<!doctype html><section data-test-id="PLAYERBAR_DESKTOP">
      <a href="/track/1" data-test-id="TRACK_TITLE">Old song</a><a href="/artist/1">Other Artist</a>
      <button data-test-id="PLAY_BUTTON">Play</button><button data-test-id="NEXT_TRACK_BUTTON">Next</button><button data-test-id="PREVIOUS_TRACK_BUTTON">Previous</button>
      <button data-test-id="LIKE_BUTTON" aria-pressed="false">Like</button>
      <div data-test-id="CHANGE_VOLUME_SLIDER" style="width:200px;height:20px;background:gray"><span role="slider" aria-valuenow=".4" aria-valuemin="0" aria-valuemax="1" style="display:block;width:1px;height:20px"></span></div>
      </section><a href="/search">Search</a><input data-test-id="SEARCH_PAGE_SEARCH_INPUT"><div id="results"></div>
      <script>
      const root=document.querySelector('section');
      root.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const key=b.dataset.testId;
      if(key==='PLAY_BUTTON')b.dataset.testId='PAUSE_BUTTON';if(key==='PAUSE_BUTTON')b.dataset.testId='PLAY_BUTTON';
      if(key==='LIKE_BUTTON')b.setAttribute('aria-pressed',String(b.getAttribute('aria-pressed')!=='true'));
      if(key.includes('TRACK_BUTTON'))root.querySelector('a').href='/track/'+(key.startsWith('NEXT')?'2':'1');});
      document.querySelector('[data-test-id="CHANGE_VOLUME_SLIDER"]').addEventListener('mousedown',e=>{const box=e.currentTarget.getBoundingClientRect();e.currentTarget.querySelector('span').setAttribute('aria-valuenow',Math.round((e.clientX-box.left)/box.width*100)/100);});
      document.querySelector('a[href="/search"]').onclick=e=>e.preventDefault();
      document.querySelector('input').oninput=()=>setTimeout(()=>{document.querySelector('#results').innerHTML='<div data-test-id="SEARCH_TRACK_CARD"><a href="/track/42" data-test-id="TRACK_TITLE">With You</a><a href="/artist/2">Linkin Park</a><button data-test-id="PLAY_BUTTON">Play found</button></div>';},1000);
      document.querySelector('#results').onclick=()=>{root.querySelector('a').href='/track/42';root.querySelector('a').textContent='With You';root.querySelectorAll('a')[1].textContent='Linkin Park';root.querySelector('button').dataset.testId='PAUSE_BUTTON';};
      </script>''', encoding="utf-8")
    main = tmp_path / "fixture.cjs"
    main.write_text("const {app,BrowserWindow}=require('electron');app.whenReady().then(()=>{const w=new BrowserWindow({show:false,webPreferences:{backgroundThrottling:false}});w.loadFile(require('path').join(__dirname,'resources/index.html'));});app.on('window-all-closed',()=>app.quit());", encoding="utf-8")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
    environment = {key: value for key, value in os.environ.items() if key != "ELECTRON_RUN_AS_NODE"}
    process = subprocess.Popen([str(executable), str(main), f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1", f"--user-data-dir={tmp_path / 'profile'}", "--mute-audio"], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    store = Store(tmp_path / "wiley"); store.patch_settings({"allow_audio_control": True})
    player = YandexMusic(tmp_path / "wiley", store, None)
    # The fixture runs electron.exe, not an installed music app. Only its descriptor
    # is injected; ownership, loopback, page scope, WebSocket and all actions are real.
    descriptor = {"pid": process.pid, "port": port, "exe": str(tmp_path / "Яндекс Музыка.exe")}
    try:
        with patch.object(player, "descriptor", return_value=descriptor):
            for _ in range(60):
                if player.status()["connected"]: break
                time.sleep(.1)
            assert player.status()["connected"]
            for command in [MusicAction(action="play"), MusicAction(action="pause"), MusicAction(action="next"), MusicAction(action="previous"), MusicAction(action="like"), MusicAction(action="unlike"), MusicAction(action="volume", value=80), MusicAction(action="search_play", query="линкин парк виз ю")]:
                result = player.execute(command)
                assert result["confirmed"], result
            assert result["state"]["id"] == "42" and result["state"]["playing"]
    finally:
        try:
            parent = psutil.Process(process.pid)
            assert str(main) in parent.cmdline()
            children = parent.children(recursive=True)
            for child in [*children, parent]:
                try: child.terminate()
                except psutil.NoSuchProcess: pass
            psutil.wait_procs([*children, parent], timeout=4)
        except psutil.NoSuchProcess: pass
        process.wait(timeout=5)
