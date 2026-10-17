"""Independent cloud TTS connection. Keys never enter settings or backups."""
import asyncio
import base64
import io
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import wave

import httpx
import keyring

from .speech_text import plain_speech


SERVICES = {
    "openrouter": "https://openrouter.ai/api/v1",
    "routerai": "https://routerai.ru/api/v1",
}
MAX_REFERENCE = 5 * 1024**2
MAX_AUDIO = 40 * 1024**2


def fish_voice_id(value):
    text = value.strip()
    if not re.match(r"https?://", text, re.I):
        return text
    try:
        url = urlparse(text)
        match = re.fullmatch(r"/(?:[a-z]{2}(?:-[a-z]{2})?/|app/)?m/([a-f\d]{32})/?", url.path, re.I)
        if url.scheme.lower() == "https" and url.hostname in {"fish.audio", "www.fish.audio"} and not url.username and not url.password and url.port is None and match:
            return match[1].lower()
    except ValueError:
        pass
    raise ValueError("Вставьте ссылку на страницу голоса fish.audio/m/ID/ или сам ID голоса")


def client(timeout=180):
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10), trust_env=False,
                             limits=httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=60))


def get_key(url):
    return keyring.get_password("WileyAI.Speech", url) or ""


def set_key(url, value):
    try:
        if value:
            keyring.set_password("WileyAI.Speech", url, value)
        else:
            try:
                keyring.delete_password("WileyAI.Speech", url)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as error:
        raise ValueError("Не удалось сохранить ключ озвучки в системном хранилище Windows") from error


class CloudAudio(bytes):
    def __new__(cls, data, media_type):
        result = super().__new__(cls, data)
        result.media_type = media_type
        return result


def pcm_wave(data):
    if not data or len(data) % 2:
        raise ValueError("Облачная озвучка вернула повреждённый PCM")
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(data)
    return CloudAudio(result.getvalue(), "audio/wav")


class CloudSpeech:
    def __init__(self, root):
        self.reference = root / "voices" / "cloud-reference.wav"
        self.metadata = self.reference.with_suffix(".json")
        self.serena = Path(__file__).resolve().parents[1] / "local/voice-samples/qwen3-serena.wav"
        self.requests = {}
        self.http = None

    async def close(self):
        await self.stop()
        if self.http is not None:
            await self.http.aclose()
            self.http = None

    def reference_info(self):
        try:
            info = json.loads(self.metadata.read_text(encoding="utf-8")) if self.reference.is_file() else None
        except (OSError, ValueError):
            info = None
        return {"reference": info, "serena_available": self.serena.is_file()}

    def save_reference(self, name, data):
        if len(data) > MAX_REFERENCE:
            raise ValueError("Образец должен быть WAV до 5 МБ и не длиннее 30 секунд")
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                size = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                if audio.getsampwidth() != 2 or audio.getnchannels() not in {1, 2} or not 8000 <= audio.getframerate() <= 48000 or not 1 <= duration <= 30 or len(audio.readframes(audio.getnframes())) != size:
                    raise ValueError("invalid sample")
        except (wave.Error, EOFError, ValueError, ZeroDivisionError):
            raise ValueError("Нужен корректный WAV PCM16: 1–30 секунд, один или два канала, 8–48 кГц") from None
        self.reference.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.reference.with_suffix(".part")
        temporary.write_bytes(data)
        temporary.replace(self.reference)
        info = {"name": Path(name).name[:150], "seconds": round(duration, 1)}
        self.metadata.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return self.reference_info()

    def remove_reference(self):
        self.reference.unlink(missing_ok=True)
        self.metadata.unlink(missing_ok=True)

    def validate(self, config):
        if not config.tts_model.strip():
            raise ValueError("Выберите облачную модель озвучки")
        try:
            key = get_key(config.tts_base_url)
        except Exception:
            raise ValueError("Не удалось прочитать ключ облачной озвучки из хранилища Windows") from None
        if not key:
            raise ValueError("Сохраните отдельный API-ключ озвучки для выбранного сервиса")
        if config.tts_use_reference and config.tts_model.startswith("fish-audio/"):
            if config.tts_service != "openrouter":
                raise ValueError("Передача WAV-образца поддерживается через OpenRouter")
            if not self.reference.is_file():
                raise ValueError("Сначала загрузите WAV-образец голоса")
        return key

    async def catalog(self, config):
        key = self.validate(config)
        try:
            async with client(15) as http:
                response = await http.get(config.tts_base_url + "/models", params={"output_modalities": "speech"}, headers={"Authorization": "Bearer " + key})
                response.raise_for_status()
            models = response.json().get("data", [])
            return [{"id": item["id"], "name": item.get("name", item["id"]), "voices": item.get("supported_voices") or [],
                     "pricing": item.get("pricing", {})} for item in models[:1500]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                    and "speech" in (item.get("architecture", {}).get("output_modalities") or [])]
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise ValueError("Не удалось получить каталог озвучки. Проверьте адрес сервиса и ключ; ID модели можно ввести вручную") from None

    async def stop(self, request_id=None):
        tasks = [task for key, task in list(self.requests.items()) if task is not asyncio.current_task() and (request_id is None or key == request_id)]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def render(self, text, config, request_id):
        key = self.validate(config)
        text = plain_speech(text)
        if not text:
            raise ValueError("Нет текста для озвучки")
        fmt = config.tts_format
        if fmt == "auto":
            fmt = "pcm" if config.tts_model.startswith("google/") else "mp3"
        body = {"model": config.tts_model, "input": text, "response_format": fmt}
        if config.tts_cloud_voice.strip():
            body["voice"] = fish_voice_id(config.tts_cloud_voice) if config.tts_model.startswith("fish-audio/") else config.tts_cloud_voice.strip()
        if config.tts_style.strip():
            if config.tts_service == "routerai":
                if config.tts_model.startswith("google/"):
                    body["provider"] = {"options": {"google-ai-studio": {"speech_metadata": {"style": config.tts_style}}}}
            else:
                body["instructions"] = config.tts_style
        if config.tts_use_reference and config.tts_model.startswith("fish-audio/"):
            sample = self.reference.read_bytes()
            if len(sample) > MAX_REFERENCE:
                raise ValueError("Образец голоса слишком большой")
            body.pop("voice", None)
            body["input_references"] = [{"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(sample).decode("ascii")}}]
        self.requests[request_id] = asyncio.current_task()
        try:
            if self.http is None or self.http.is_closed:
                self.http = client()
            async with self.http.stream("POST", config.tts_base_url + "/audio/speech", headers={"Authorization": "Bearer " + key}, json=body) as response:
                if response.status_code != 200:
                    messages = {401: "Ключ озвучки отклонён", 403: "Нет доступа к выбранной модели озвучки", 402: "Недостаточно средств на балансе сервиса озвучки",
                                404: "Облачная модель или адрес озвучки не найдены", 429: "Лимит запросов озвучки исчерпан. Подождите и повторите"}
                    raise ValueError(messages.get(response.status_code, "Сервис озвучки отклонил запрос. Проверьте модель, голос и формат") + f" (HTTP {response.status_code})")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_AUDIO:
                        raise ValueError("Аудио превысило допустимый размер; сократите фрагмент текста")
            data = bytes(data)
            if not data or "json" in content_type or content_type.startswith("text/"):
                raise ValueError("Сервис вернул пустой ответ или сообщение вместо аудио")
            if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
                return CloudAudio(data, "audio/wav")
            if fmt == "pcm":
                return pcm_wave(data)
            if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224):
                return CloudAudio(data, "audio/mpeg")
            raise ValueError("Сервис вернул нераспознанный формат аудио. Проверьте настройки формата")
        except asyncio.CancelledError:
            raise ValueError("Облачная озвучка остановлена") from None
        except httpx.HTTPError:
            raise ValueError("Сервис озвучки недоступен или не ответил вовремя") from None
        finally:
            self.requests.pop(request_id, None)
