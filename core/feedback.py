"""Local support archives. Only explicitly selected fields cross the ZIP boundary."""

import io
import json
import platform
import time
import hashlib
import psutil
from zipfile import ZIP_DEFLATED, ZipFile

from .config import CATALOG
from .version import VERSION, build_identity

PUBLIC_MODELS = {item["id"] for item in CATALOG} | {"gpt-5.6-luna", "fish-audio/s2.1-pro-free:free"}


def model_id(model):
    if not model:
        return None
    if model in PUBLIC_MODELS:
        return model
    # Custom names can include account identifiers or URLs. Do not export them verbatim.
    return "custom-" + hashlib.sha256(model.encode("utf-8")).hexdigest()[:16]


def engine_settings(settings):
    tts_model = {"silero": "silero-v5-ru", "silero_v5_6": "silero-v5.6-ru"}.get(settings.tts_engine)
    if settings.tts_engine == "cloud":
        tts_model = model_id(settings.tts_model)
    return {
        "llm": {"provider": settings.provider, "model": model_id(settings.model),
                "fast_model": model_id(settings.fast_model), "profile": settings.profile,
                "context_tokens": settings.context_tokens, "response_tokens": settings.response_tokens,
                "temperature": settings.temperature},
        "stt": {"engine": "gigaam" if settings.stt_model == "gigaam-v3" else "whisper",
                "model": settings.stt_model, "quality": settings.stt_quality,
                "environment": settings.stt_environment, "vad": settings.conversation_vad,
                "endpoint": settings.conversation_endpoint_mode, "smart_turn": settings.conversation_smart_turn},
        "tts": {"engine": settings.tts_engine, "model": tts_model,
                "voice": model_id(settings.tts_cloud_voice if settings.tts_engine == "cloud" else settings.tts_voice),
                "device": settings.tts_device, "enabled": settings.speak_answers,
                "service": settings.tts_service if settings.tts_engine == "cloud" else None},
    }


def faults(path, days):
    if path is None:
        return []
    try:
        with path.open(encoding="utf-8") as file:
            rows = json.loads(file.read(32768))
    except (OSError, ValueError):
        return []
    now = int(time.time())
    if not isinstance(rows, list):
        return []
    return [{"at": row["at"], "component": row["component"], "reason": row["reason"], "code": row.get("code")}
            for row in rows[-100:] if isinstance(row, dict) and type(row.get("at")) is int
            and now - days * 86400 <= row["at"] <= now + 60
            and row.get("component") in ("core", "renderer", "gpu", "electron-child")
            and row.get("reason") in ("crashed", "oom", "launch-failed", "abnormal-exit")
            and (row.get("code") is None or type(row["code"]) is int)]


def entries(settings, update_state, description, fault_file=None):
    return {
        "system.json": json.dumps({
            "wileyai": VERSION, "os": platform.system(), "os_version": platform.release(),
            "architecture": platform.machine(), **build_identity(),
            "cpu_threads": psutil.cpu_count(), "ram_mib": psutil.virtual_memory().total // 1048576,
            "engines": engine_settings(settings), "automatic_updates": update_state["automatic"],
        }, ensure_ascii=False, indent=2),
        "diagnostics.json": json.dumps({
            "last_update_check_unix": update_state["checked_at"],
            "last_update_check_failed": bool(update_state["error"]),
            "trusted_updates_configured": update_state["signed"],
            "retention_days": update_state["retention_days"],
            "update_events": update_state["history"],
            "process_faults": faults(fault_file, update_state["retention_days"]),
        }, indent=2),
        "description.txt": description,
    }


def archive(contents):
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as zipped:
        for name, content in contents.items():
            zipped.writestr(name, content.encode("utf-8"))
    return output.getvalue()
