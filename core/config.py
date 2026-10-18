from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import os

from pydantic import BaseModel, Field, field_validator
from .piper import catalog as piper_catalog


DATA_DIR = Path(os.environ.get("WILEYAI_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


class CloudSpeechProfile(BaseModel):
    """Per-service preferences, without credentials or reference audio."""
    model_config = {"extra": "forbid"}
    tts_base_url: str = "https://openrouter.ai/api/v1"
    tts_model: str = Field(default="fish-audio/s2.1-pro-free:free", max_length=200)
    tts_cloud_voice: str = Field(default="", max_length=300)
    tts_format: Literal["auto", "mp3", "pcm", "wav"] = "auto"
    tts_style: str = Field(default="", max_length=1000)
    tts_use_reference: bool = False

    @field_validator("tts_base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        return Settings.valid_search_endpoint(value)


class SavedSpeechVoice(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    voice: str = Field(min_length=1, max_length=300)
    service: Literal["openrouter", "routerai", "compatible"]
    base_url: str
    model: str = Field(min_length=1, max_length=200)

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value):
        return Settings.valid_search_endpoint(value)


class Settings(BaseModel):
    ui_theme: Literal["aurora", "ice", "ember", "nebula"] = "aurora"
    ui_motion: Literal["full", "reduced"] = "full"
    ui_glass: bool = True
    name: str = Field(default="Уайли", min_length=1, max_length=60)
    grammatical_gender: Literal["feminine", "masculine", "neutral"] = "feminine"
    personality: str = Field(default="Ты Уайли, личный ассистент. Общайся на русском, тепло и по существу. Учитывай предпочтения владельца. Не выдумывай выполненные действия и воспоминания.", max_length=8000)
    provider: Literal["ollama", "compatible"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = Field(default="qwen3.5:4b", max_length=200)
    profile: Literal["eco", "balanced", "quality"] = "balanced"
    voice_idle_timeout: Literal["profile", "never", "1m", "5m", "15m"] = "profile"
    context_tokens: int = Field(default=4096, ge=1024, le=32768)
    response_tokens: int = Field(default=2048, ge=256, le=8192)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stt_model: Literal["tiny", "base", "small"] = "small"
    stt_quality: Literal["fast", "balanced", "accurate"] = "accurate"
    stt_environment: Literal["normal", "music"] = "normal"
    conversation_listen_while_thinking: bool = True
    tts_engine: Literal["silero", "silero_v5_6", "piper", "sapi", "qwen3", "cloud"] = "silero"
    tts_service: Literal["openrouter", "routerai", "compatible"] = "openrouter"
    tts_base_url: str = "https://openrouter.ai/api/v1"
    tts_model: str = Field(default="fish-audio/s2.1-pro-free:free", max_length=200)
    tts_cloud_voice: str = Field(default="", max_length=300)
    tts_format: Literal["auto", "mp3", "pcm", "wav"] = "auto"
    tts_style: str = Field(default="", max_length=1000)
    tts_use_reference: bool = False
    tts_connections: dict[Literal["openrouter", "routerai", "compatible"], CloudSpeechProfile] = Field(default_factory=dict, max_length=3)
    tts_saved_voices: list[SavedSpeechVoice] = Field(default_factory=list, max_length=100)
    openvoice_enabled: bool = False
    openvoice_voice: Literal["mita", "kind-mita", "serena", "custom"] = "mita"
    tts_voice: str = Field(default="", max_length=300)
    tts_device: Literal["auto", "cpu", "cuda"] = "auto"
    speak_answers: bool = False
    memory_suggestions: bool = True
    allow_file_open: bool = True
    allow_app_open: bool = True
    allow_web_open: bool = True
    allow_audio_control: bool = True
    music_player: Literal["auto", "yandex"] = "auto"
    command_understanding: bool = False
    search_enabled: bool = False
    search_provider: Literal["searxng", "brave"] = "searxng"
    search_base_url: str = "http://127.0.0.1:8080"
    search_filter: Literal["off", "moderate", "strict"] = "off"
    audio_input_device_id: str = Field(default="", max_length=512)
    audio_output_device_id: str = Field(default="", max_length=512)
    conversation_silence_ms: int = Field(default=1000, ge=500, le=2500)
    conversation_threshold: float = Field(default=0.015, ge=0.003, le=0.1)
    avatar_path: str = Field(default="", max_length=4096)

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Укажите адрес сервера без ключей, параметров и пароля")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Для удалённого сервера нужен HTTPS; HTTP разрешён для localhost")
        return value.rstrip("/")

    @field_validator("search_base_url")
    @classmethod
    def valid_search_endpoint(cls, value: str) -> str:
        if len(value) > 2048 or "\\" in value or any(ord(char) < 33 for char in value):
            raise ValueError("Укажите корректный адрес SearXNG")
        parsed = urlparse(value)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Укажите корректный порт SearXNG")
        return cls.valid_endpoint(value)

    @field_validator("tts_base_url")
    @classmethod
    def valid_speech_endpoint(cls, value: str) -> str:
        return cls.valid_search_endpoint(value)


class SettingsUpdate(Settings):
    api_key: str | None = Field(default=None, max_length=4096)
    search_api_key: str | None = Field(default=None, max_length=4096)


class AppearanceSettings(BaseModel):
    model_config = {"extra": "forbid"}
    ui_theme: Literal["aurora", "ice", "ember", "nebula"] | None = None
    ui_motion: Literal["full", "reduced"] | None = None
    ui_glass: bool | None = None


class CloudSettings(BaseModel):
    model_config = {"extra": "forbid"}
    tts_service: Literal["openrouter", "routerai", "compatible"] | None = None
    tts_base_url: str | None = Field(default=None, max_length=2048)
    tts_model: str | None = Field(default=None, max_length=200)
    tts_cloud_voice: str | None = Field(default=None, max_length=300)
    tts_format: Literal["auto", "mp3", "pcm", "wav"] | None = None
    tts_style: str | None = Field(default=None, max_length=1000)
    tts_use_reference: bool | None = None


class VoiceSettings(CloudSettings):
    """An immediate voice selection must not replace unrelated settings drafts."""
    tts_engine: Literal["silero", "silero_v5_6", "piper", "sapi", "qwen3", "cloud"] | None = None
    tts_voice: str | None = Field(default=None, max_length=300)
    tts_device: Literal["auto", "cpu", "cuda"] | None = None
    speak_answers: bool | None = None
    openvoice_enabled: bool | None = None
    openvoice_voice: Literal["mita", "kind-mita", "serena", "custom"] | None = None


CATALOG = [
    {"id": "qwen3.5:4b", "name": "Qwen 3.5 · 4B", "kind": "llm", "engine": "ollama", "description": "Начальный сбалансированный вариант для общения и изображений.", "size": "≈ 3–4 ГБ", "languages": "Русский и другие", "source": "https://ollama.com/library/qwen3.5", "license": "Apache-2.0"},
    {"id": "huihui_ai/qwen3.5-abliterated:4b", "name": "Huihui Qwen 3.5 · 4B", "kind": "llm", "engine": "ollama", "description": "Вариант с уменьшенными ограничениями ответов. Качество сравнивается отдельно.", "size": "≈ 3–4 ГБ", "languages": "Мультиязычная", "source": "https://huggingface.co/huihui-ai/Huihui-Qwen3.5-4B-abliterated", "license": "Apache-2.0"},
    *[{"id": size, "name": f"Whisper · {size}", "kind": "stt", "engine": "faster-whisper", "description": "Локальное распознавание речи на CPU. Сначала установите компонент Whisper.", "size": amount, "languages": "Русский и другие", "source": "https://github.com/SYSTRAN/faster-whisper", "license": "MIT"} for size, amount in [("tiny", "≈ 75 МБ"), ("base", "≈ 145 МБ"), ("small", "≈ 485 МБ")]],
    {"id": "windows-sapi", "name": "Системные голоса Windows", "kind": "tts", "engine": "sapi", "description": "Стартовый локальный адаптер без скачивания весов. Доступные языки зависят от установленных голосов Windows.", "size": "Уже в системе", "languages": "По установленным голосам", "source": "https://learn.microsoft.com/dotnet/api/system.speech.synthesis.speechsynthesizer", "license": "Компонент Windows"},
    {"id": "silero-v5-ru", "name": "Silero · русский голос", "kind": "tts", "engine": "silero", "description": "Локальная озвучка на CPU. Голоса: Ксения, Айдар, Бая. Сначала установите компонент Silero / Torch CPU.", "size": "≈ 140 МБ + движок", "languages": "Русский", "source": "https://github.com/snakers4/silero-models", "license": "CC BY-NC 4.0; см. лицензию модели"},
]
CATALOG.extend([
    {"id": "qwen3-tts-0.6b", "name": "Qwen3-TTS 0.6B · голоса персонажа", "kind": "tts", "engine": "qwen3", "description": "9 тембров, русский язык. Сначала установите компонент Qwen3-TTS CPU. Читает готовые фразы, модель загружается один раз на ответ; CPU заметно медленнее GPU.", "size": "≈ 2,5 ГБ весов + отдельный движок", "languages": "Русский и другие", "source": "https://github.com/QwenLM/Qwen3-TTS", "license": "Apache-2.0"},
    {"id": "silero-v5.6-ru", "name": "Silero 5.6 · выразительный русский", "kind": "tts", "engine": "silero_v5_6", "description": "Обновлённая интонация вопросов и восклицаний. Ксения, Бая, Айдар и Евгений. Сначала установите компонент Silero / Torch CPU.", "size": "≈ 148 МБ + движок", "languages": "Русский", "source": "https://github.com/snakers4/silero-models#v5", "license": "CC BY-NC 4.0"},
    *piper_catalog(),
])
