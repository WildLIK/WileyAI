"""Versioned provider contract. Unknown capabilities are never silently promoted."""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
FEATURES = ("text", "streaming", "vision", "file_upload", "image_generation", "image_editing",
            "audio_generation", "speech_recognition", "video_input", "video_generation",
            "web_search", "reasoning_summary", "native_tools", "emulated_tools", "mcp", "json_output")


class GatewayError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capability(StrictBody):
    state: Literal["verified", "advertised", "experimental", "unknown", "unavailable"] = "unknown"
    evidence: str = ""
    observed_at: float = 0

    @property
    def usable(self):
        return self.state in {"verified", "advertised"}


class Model(StrictBody):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    reasoning_modes: list[str] = Field(default_factory=list)

    def supports(self, feature):
        return self.capabilities.get(feature, Capability()).usable


class ConnectBody(StrictBody):
    provider_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(default="", max_length=80)
    credential: str = Field(default="", max_length=4096)
    consent: bool = False


class ConversationBody(StrictBody):
    connection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    model_id: str = Field(min_length=1, max_length=200)


class HistoryMessage(StrictBody):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class RunBody(StrictBody):
    request_id: str = Field(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(default="", max_length=32000)
    attachments: list[str] = Field(default_factory=list, max_length=5)
    options: dict = Field(default_factory=dict)
    context: list[HistoryMessage] = Field(default_factory=list, max_length=8)


class AuthStart(StrictBody):
    redirect_uri: str = Field(min_length=1, max_length=160)


class AuthComplete(StrictBody):
    flow_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    state: str = Field(min_length=20, max_length=150)
    code: str = Field(default="", max_length=8192)
    client_id: str = Field(default="", max_length=250)
    error: str = Field(default="", max_length=80)


@dataclass
class ProviderEvent:
    type: str
    data: dict = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Extensions are trusted server-side code, selected by the administrator, never downloaded by clients."""
    kind: str

    @abstractmethod
    async def status(self, account: dict) -> dict: ...

    @abstractmethod
    async def models(self, account: dict) -> list[Model]: ...

    @abstractmethod
    def stream(self, account: dict, model: Model, messages: list[dict], options: dict) -> AsyncIterator[ProviderEvent]: ...

    async def disconnect(self, account: dict):
        return {"revoked_upstream": False}

    async def close(self):
        pass


class WebSessionAdapter(ProviderAdapter):
    kind = "web_session"


class OAuthAdapter(ProviderAdapter):
    kind = "oauth"


class KeylessAdapter(ProviderAdapter):
    kind = "keyless"


class OfficialAPIAdapter(ProviderAdapter):
    kind = "official_api"
