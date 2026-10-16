from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import os

from pydantic import BaseModel, Field, field_validator


DATA_DIR = Path(os.environ.get("WILEYAI_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


class Settings(BaseModel):
    name: str = Field(default="Уайли", min_length=1, max_length=60)
    personality: str = Field(default="Ты Уайли, личный ассистент. Общайся на русском, тепло и по существу. Учитывай предпочтения владельца. Не выдумывай выполненные действия и воспоминания.", max_length=8000)
    provider: Literal["ollama", "compatible"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = Field(default="qwen3.5:4b", max_length=200)
    profile: Literal["eco", "balanced", "quality"] = "balanced"
    context_tokens: int = Field(default=4096, ge=1024, le=32768)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stt_model: Literal["tiny", "base", "small"] = "small"
    tts_engine: Literal["silero", "sapi"] = "silero"
    tts_voice: str = Field(default="", max_length=300)
    speak_answers: bool = False
    memory_suggestions: bool = True
    allow_file_open: bool = True
    allow_app_open: bool = True
    allow_web_open: bool = True
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


class SettingsUpdate(Settings):
    api_key: str | None = Field(default=None, max_length=4096)
    search_api_key: str | None = Field(default=None, max_length=4096)


CATALOG = [
    {"id": "qwen3.5:4b", "name": "Qwen 3.5 · 4B", "kind": "llm", "engine": "ollama", "description": "Начальный сбалансированный вариант для общения и изображений.", "size": "≈ 3–4 ГБ", "languages": "Русский и другие", "source": "https://ollama.com/library/qwen3.5", "license": "Apache-2.0"},
    {"id": "huihui_ai/qwen3.5-abliterated:4b", "name": "Huihui Qwen 3.5 · 4B", "kind": "llm", "engine": "ollama", "description": "Вариант с уменьшенными ограничениями ответов. Качество сравнивается отдельно.", "size": "≈ 3–4 ГБ", "languages": "Мультиязычная", "source": "https://huggingface.co/huihui-ai/Huihui-Qwen3.5-4B-abliterated", "license": "Apache-2.0"},
    *[{"id": size, "name": f"Whisper · {size}", "kind": "stt", "engine": "faster-whisper", "description": "Локальное распознавание речи на CPU. Для установки нужен модуль voice.", "size": amount, "languages": "Русский и другие", "source": "https://github.com/SYSTRAN/faster-whisper", "license": "MIT"} for size, amount in [("tiny", "≈ 75 МБ"), ("base", "≈ 145 МБ"), ("small", "≈ 485 МБ")]],
    {"id": "windows-sapi", "name": "Системные голоса Windows", "kind": "tts", "engine": "sapi", "description": "Стартовый локальный адаптер без скачивания весов. Доступные языки зависят от установленных голосов Windows.", "size": "Уже в системе", "languages": "По установленным голосам", "source": "https://learn.microsoft.com/dotnet/api/system.speech.synthesis.speechsynthesizer", "license": "Компонент Windows"},
    {"id": "silero-v5-ru", "name": "Silero · русский голос", "kind": "tts", "engine": "silero", "description": "Локальная озвучка на CPU. Голоса: Ксения, Айдар, Бая. Нужен модуль tts.", "size": "≈ 140 МБ + движок", "languages": "Русский", "source": "https://github.com/snakers4/silero-models", "license": "CC BY-NC 4.0; см. лицензию модели"},
]
