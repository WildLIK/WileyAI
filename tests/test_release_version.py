import json
from pathlib import Path
import tomllib

from core.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_published_version_shared_by_platforms_and_lockfiles():
    release = json.loads((ROOT / "release-version.json").read_text())
    assert release["version"] == VERSION
    assert isinstance(release["androidVersionCode"], int) and release["androidVersionCode"] > 0
    for file in ("package.json", "package-lock.json"):
        assert json.loads((ROOT / file).read_text(encoding="utf-8"))["version"] == VERSION
    assert json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))["packages"][""]["version"] == VERSION
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    package = next(entry for entry in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
                   if entry["name"] == project["name"])
    assert project["version"] == package["version"] == VERSION
