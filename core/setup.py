"""First-run progress contains preferences only, never secrets or form drafts."""
import json
import os
from pathlib import Path
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool = False
    completed: bool = False
    step: int = Field(default=0, ge=0, le=3)
    mode: Literal["local", "cloud"] = "local"
    voice_mode: Literal["text", "piper", "sapi", "keep"] = "text"
    microphone: bool = False


class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool | None = None
    completed: bool | None = None
    step: int | None = Field(default=None, ge=0, le=3)
    mode: Literal["local", "cloud"] | None = None
    voice_mode: Literal["text", "piper", "sapi", "keep"] | None = None
    microphone: bool | None = None


class SetupSettings(BaseModel):
    """Sparse edits, merged with current settings at the time of saving."""
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ollama", "compatible"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    stt_model: Literal["tiny", "base", "small"] | None = None
    tts_engine: Literal["piper", "sapi"] | None = None
    tts_voice: str | None = Field(default=None, max_length=300)
    speak_answers: bool | None = None
    openvoice_enabled: Literal[False] | None = None
    audio_input_device_id: str | None = Field(default=None, max_length=512)
    audio_output_device_id: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)

    def merge(self, current):
        return Settings.model_validate({**current.model_dump(), **self.model_dump(exclude_none=True, exclude={"api_key"})})


class Setup:
    def __init__(self, root, fresh):
        self.path = Path(root) / "setup.json"
        self.lock = threading.RLock()
        self.progress = Progress(active=fresh and os.environ.get("WILEYAI_PACKAGED") == "1")
        try:
            self.progress = Progress.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Existing installations never become first-run installations after an update.
            self.save()

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".part")
            temporary.write_text(self.progress.model_dump_json(), encoding="utf-8")
            temporary.replace(self.path)

    def state(self):
        with self.lock:
            return self.progress.model_dump()

    def update(self, body):
        with self.lock:
            self.progress = Progress.model_validate({**self.state(), **body.model_dump(exclude_none=True)})
            self.save()
            return self.state()


def model_present(config, models):
    def identity(value):
        return value + ":latest" if config.provider == "ollama" and ":" not in value.rsplit("/", 1)[-1] else value
    return any(identity(item["id"]) == identity(config.model) for item in models)


def speech_readiness(config, voice, system_voices):
    result = {"recognition": voice.available() and (voice.root / "models/whisper" / config.stt_model / "model.bin").is_file(),
              "synthesis": False, "error": ""}
    try:
        if config.tts_engine == "piper":
            result["synthesis"] = voice.piper.available() and voice.piper.installed(config.tts_voice or "irina")
        elif config.tts_engine in {"silero", "silero_v5_6"}:
            result["synthesis"] = voice.tts_available() and voice.tts_installed("v5_6_ru" if config.tts_engine == "silero_v5_6" else "v5_ru")
        elif config.tts_engine == "sapi":
            result["synthesis"] = bool(system_voices) and (not config.tts_voice or any(item["name"] == config.tts_voice for item in system_voices))
        elif config.tts_engine == "qwen3":
            result["synthesis"] = voice.qwen.available() and voice.qwen.installed()
        elif config.tts_engine == "cloud":
            voice.cloud.validate(config)
            result["synthesis"] = True  # Configuration only: no paid generation is triggered.
        if config.openvoice_enabled and config.tts_engine in {"piper", "silero", "silero_v5_6"}:
            voice.openvoice.validate(config.openvoice_voice)
    except ValueError as error:
        result.update(synthesis=False, error=str(error))
    return result
