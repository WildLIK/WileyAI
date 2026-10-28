"""WileyAI local runtime."""

# Optional libraries live in immutable, versioned directories in user data.
# They are added only at startup; no DLLs in a running process are replaced.
import json
import os
from pathlib import Path
import re
import site

_data = Path(os.environ.get("WILEYAI_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
for _key in ("whisper", "piper", "silero", "gigaam"):
    try:
        _base = _data / "components" / _key
        _directory = json.loads((_base / "ready.json").read_text(encoding="utf-8"))["directory"]
        if re.fullmatch(r"[a-f0-9]{16}", _directory) and (_base / _directory / "lib").is_dir():
            site.addsitedir(str(_base / _directory / "lib"))
    except (OSError, ValueError, KeyError, TypeError):
        pass
