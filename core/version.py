import json
from functools import cache
from pathlib import Path
import re
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "release-version.json").read_text(encoding="utf-8"))["version"]


@cache
def build_identity():
    try:
        metadata = json.loads((ROOT.parent / "build-info.json").read_text(encoding="utf-8"))
        if (metadata["version"] == VERSION and metadata["platform"] == "win32-x64"
                and re.fullmatch(r"windows-x64-[0-9a-f-]{36}", metadata["build_id"])
                and re.fullmatch(r"[0-9a-f]{40}", metadata["git_commit"])
                and type(metadata["git_dirty"]) is bool):
            return {key: metadata[key] for key in ("build_id", "git_commit", "git_dirty")}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    # Source launches have no frozen build identity. Do not invoke Git while exporting.
    return {"build_id": "development-" + str(uuid4()), "git_commit": None, "git_dirty": None}
