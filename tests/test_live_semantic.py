"""Opt-in real embeddings evaluation; owned engine and disposable model files."""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import time
import hashlib
import json
import re
from urllib.parse import urljoin

import httpx
import psutil
import pytest

from core.config import Settings
from core.semantic import SemanticIndex
from core.storage import Store
from core.document_library import Library
from core import webfetch, websearch


async def public_model_files(folder):
    """Test-only DNS alternative; verify official OCI sizes and SHA256s.

    The owned Ollama cannot pull through fake-IP DNS. This uses the same pinned,
    certificate-checked public DNS transport as the reader, without changing OS
    DNS, the personal engine, or the application's download path.
    """
    registry = "https://registry.ollama.ai/v2/library/embeddinggemma"
    _, _, _, raw = await webfetch.read(registry + "/manifests/300m", "application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json", dns_mode="cloudflare")
    manifest = json.loads(raw)
    layers = [manifest["config"], *manifest["layers"]]
    assert sum(row["size"] for row in layers) < 800 * 1024**2
    blobs = folder / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    for row in layers:
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", row["digest"])
        url = registry + "/blobs/" + row["digest"]
        path = blobs / row["digest"].replace(":", "-")
        for hop in range(4):
            assert websearch.public_url(url)
            original = httpx.URL(url)
            assert original.scheme == "https"
            host = original.raw_host.decode()
            ips = await webfetch.addresses(host, 443, "cloudflare")
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=120) as http:
                async with http.stream("GET", original.copy_with(host=ips[0]), headers={"Host": host, "Accept-Encoding": "identity"}, extensions={"sni_hostname": host}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    assert original.scheme == "https" and response.headers.get("content-encoding", "identity") == "identity"
                    count, checksum = 0, hashlib.sha256()
                    with path.open("xb") as target:
                        async for chunk in response.aiter_bytes(chunk_size=1024**2):
                            count += len(chunk)
                            assert count <= row["size"]
                            checksum.update(chunk); target.write(chunk)
                    assert count == row["size"] and "sha256:" + checksum.hexdigest() == row["digest"]
                    print("Verified disposable model layer:", count, flush=True)
                    break
        else:
            raise AssertionError("Too many model storage redirects")
    target = folder / "manifests/registry.ollama.ai/library/embeddinggemma/300m"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_SEMANTIC") != "1", reason="Downloads a disposable 622 MB embeddings model")
def test_real_multilingual_embeddings_and_original_sources(tmp_path):
    executable = Path(__file__).resolve().parents[1] / "local/ollama/ollama.exe"
    if not executable.is_file(): pytest.skip("Portable engine unavailable")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0)); port = reserved.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([str(executable), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(tmp_path / "models"), "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        with httpx.Client(base_url=endpoint, trust_env=False, timeout=180) as http:
            for _ in range(80):
                try:
                    if http.get("/api/version").is_success: break
                except httpx.HTTPError: pass
                time.sleep(.1)
            print("Pulling disposable embeddinggemma:300m", flush=True)
            response = http.post("/api/pull", json={"model": "embeddinggemma:300m", "stream": False})
            if not response.is_success and "resolves to non-public" in response.text:
                print("Native pull blocked by fake-IP; validating official public model layers", flush=True)
                asyncio.run(public_model_files(tmp_path / "models"))
            else:
                assert response.is_success, response.text[:500]
                assert response.json().get("status") == "success", response.text
        store = Store(tmp_path / "data")
        store.save_settings(Settings(embedding_enabled=True, embedding_base_url=endpoint))
        memory = store.add_memory("Я езжу на работу на велосипеде")
        store.add_memory("Мой любимый напиток — кофе")
        doc = Library(store).add("Обслуживание машины", "Автомобиль требует замены масла каждые десять тысяч километров.")
        Library(store).add("Рецепт салата", "Для салата возьмите помидоры, огурцы и лук.")
        index = SemanticIndex(store)
        async def scenario():
            await index.rebuild(store)
            assert index.job["state"] == "done", index.job
            memories, notice = await index.search(store, "Как я добираюсь до офиса?", "memory")
            assert not notice and memories and memories[0]["id"] == memory["id"], memories
            docs, notice = await index.search(store, "Когда менять смазку в машине?", "document")
            assert not notice and docs and docs[0]["id"] == doc["id"], docs
            print("Real semantic scores:", memories[0]["score"], docs[0]["score"], flush=True)
        asyncio.run(scenario())
    finally:
        parent = psutil.Process(process.pid)
        assert Path(parent.exe()).resolve() == executable.resolve()
        owned = [*parent.children(recursive=True), parent]
        for child in owned:
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        psutil.wait_procs(owned, timeout=5)
        process.wait(timeout=5)
