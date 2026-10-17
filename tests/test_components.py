import asyncio
import hashlib
import io
import json
from pathlib import Path
import zipfile

import httpx
import pytest

from core import components


@pytest.fixture(autouse=True)
def no_legacy_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(components, "PROJECT", tmp_path)


def archive(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as result:
        for name, content in files.items():
            result.writestr(name, content)
    return data.getvalue()


def manager(tmp_path, data, checksum=None):
    digest = checksum or hashlib.sha256(data).hexdigest()
    def handler(request):
        if request.url.path.endswith("sha256sum.txt"):
            return httpx.Response(200, text=digest + "  ollama-windows-amd64.zip\n")
        return httpx.Response(200, content=data, headers={"Content-Length": str(len(data))})
    return components.Components(tmp_path, transport=httpx.MockTransport(handler))


def test_install_verified_ollama_atomically(tmp_path):
    install = manager(tmp_path, archive({"ollama.exe": b"engine", "lib/a.dll": b"library"}))
    async def run():
        install.start("ollama")
        await install.task
    asyncio.run(run())
    assert install.job["state"] == "done"
    directory = components.component_directory(tmp_path, "ollama")
    assert (directory / "ollama.exe").read_bytes() == b"engine"
    assert next(item for item in install.status()["items"] if item["id"] == "ollama")["installed"]
    assert not list((tmp_path / "components/ollama").glob("*.partial"))


@pytest.mark.parametrize("files,checksum", [({"../escaped.exe": b"oops", "ollama.exe": b"x"}, None), ({"ollama.exe": b"x"}, "0" * 64), ({"no-engine.txt": b"x"}, None)])
def test_bad_archives_never_become_installed(tmp_path, files, checksum):
    install = manager(tmp_path, archive(files), checksum)
    async def run():
        install.start("ollama")
        await install.task
    asyncio.run(run())
    assert install.job["state"] == "error"
    assert components.component_directory(tmp_path, "ollama") is None
    assert not (tmp_path / "escaped.exe").exists()
    assert not list((tmp_path / "components/ollama").glob("*.partial"))


def test_concurrent_install_and_cancel_cleanup(tmp_path, monkeypatch):
    install = components.Components(tmp_path)
    async def pending(staging):
        (staging / "download.part").write_bytes(b"partial")
        await asyncio.sleep(60)
    monkeypatch.setattr(install, "ollama", pending)
    async def run():
        install.start("ollama")
        await asyncio.sleep(0)
        with pytest.raises(ValueError, match="Дождитесь"):
            install.start("piper")
        await install.cancel()
    asyncio.run(run())
    assert install.job["state"] == "cancelled"
    assert not list((tmp_path / "components/ollama").iterdir())


def test_marker_cannot_escape_component_directory(tmp_path):
    base = tmp_path / "components/piper"
    base.mkdir(parents=True)
    (base / "ready.json").write_text(json.dumps({"directory": "../../../../"}))
    assert components.component_directory(tmp_path, "piper") is None


def test_failed_package_install_does_not_publish_partial_libraries(tmp_path, monkeypatch):
    install = components.Components(tmp_path)
    monkeypatch.setenv("WILEYAI_UV", "uv.exe")
    monkeypatch.setattr(components.importlib.util, "find_spec", lambda module: None)
    requirements = tmp_path / "requirements/piper.txt"
    requirements.parent.mkdir()
    requirements.write_text("piper-tts==1.8.0")
    monkeypatch.setattr(components, "PROJECT", tmp_path)
    async def fail(*args):
        raise ValueError("no internet")
    monkeypatch.setattr(install, "command", fail)
    async def run():
        install.start("piper")
        await install.task
    asyncio.run(run())
    assert install.job["state"] == "error"
    assert components.component_directory(tmp_path, "piper") is None
