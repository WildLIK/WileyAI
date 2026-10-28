from collections.abc import AsyncIterator
from contextlib import aclosing
import json

import httpx
import keyring

from .config import Settings
from .repetition import RepetitionGuard
from . import chatgpt


class IncompleteResponse(ValueError):
    """A partial answer can be retained and explicitly continued by its owner."""


class ResponseLimitReached(IncompleteResponse):
    """The provider returned usable text but stopped at its output limit."""


class RepetitionStopped(IncompleteResponse):
    """A degenerate generation was stopped; automatic continuation is unsafe."""


def response_limit(settings):
    return min(settings.response_tokens, max(256, settings.context_tokens // 2))


def key_id(settings: Settings) -> str:
    return settings.base_url


def get_key(settings: Settings) -> str:
    if settings.provider == "chatgpt":
        return ""  # OAuth credentials never enter the API-key interface.
    return keyring.get_password("WileyAI", key_id(settings)) or ""


def set_key(settings: Settings, value: str):
    if settings.provider == "chatgpt":
        if value:
            raise ValueError("Для ChatGPT используется вход через аккаунт, API-ключ не нужен.")
        return
    if value:
        keyring.set_password("WileyAI", key_id(settings), value)
    else:
        try:
            keyring.delete_password("WileyAI", key_id(settings))
        except keyring.errors.PasswordDeleteError:
            pass


def client(settings: Settings) -> httpx.AsyncClient:
    secret = get_key(settings)
    return httpx.AsyncClient(base_url=settings.base_url + "/", headers={"Authorization": f"Bearer {secret}"} if secret else {}, timeout=httpx.Timeout(180, connect=5), trust_env=False)


def compatible_path(settings: Settings, endpoint: str) -> str:
    return endpoint if settings.base_url.endswith("/v1") else "v1/" + endpoint


async def list_models(settings: Settings) -> list[dict]:
    if settings.provider == "chatgpt":
        return await chatgpt.connection(settings.chatgpt_connection).models()
    async with client(settings) as http:
        response = await http.get("api/tags" if settings.provider == "ollama" else compatible_path(settings, "models"))
        response.raise_for_status()
    data = response.json()
    if settings.provider == "ollama":
        return [{"id": item["name"], "size": item.get("size", 0)} for item in data.get("models", [])]
    return [{"id": item["id"], "size": 0} for item in data.get("data", [])]


async def chat(settings: Settings, messages: list[dict], output_schema: dict | None = None) -> AsyncIterator[str]:
    if settings.provider == "chatgpt":
        output = chatgpt.connection(settings.chatgpt_connection).reply(settings.model, messages, output_schema)
        repetition = RepetitionGuard()
        async with aclosing(output):
            try:
                async for delta in output:
                    for start in range(0, len(delta), 64):
                        piece = delta[start:start + 64]
                        if output_schema is None and repetition.repetitive(piece):
                            raise RepetitionStopped("Остановила ответ: модель начала повторяться. Попробуйте уточнить вопрос.")
                        yield piece
            except chatgpt.ChatGPTError as error:
                if output_schema is not None and error.format_unsupported:
                    raise
                raise IncompleteResponse(str(error)) from error
        return
    if settings.provider == "ollama":
        endpoint = "api/chat"
        body = {"model": settings.model, "messages": messages, "stream": True, "options": {"num_ctx": settings.context_tokens, "num_predict": response_limit(settings), "temperature": settings.temperature}, "keep_alive": {"eco": "1m", "balanced": "5m", "quality": "15m"}[settings.profile]}
        if "qwen3" in settings.model.casefold():
            body["think"] = False
        if output_schema is not None:
            body["format"] = output_schema
    else:
        endpoint = compatible_path(settings, "chat/completions")
        body = {"model": settings.model, "messages": messages, "stream": True, "temperature": settings.temperature, "max_tokens": response_limit(settings)}
        if output_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "document_reading_mode", "strict": True, "schema": output_schema}}
    async with client(settings) as http:
        async with http.stream("POST", endpoint, json=body) as response:
            response.raise_for_status()
            finished = False
            repetition = RepetitionGuard()
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if settings.provider == "compatible":
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].strip()
                    if line == "[DONE]":
                        finished = True
                        break
                item = json.loads(line)
                if item.get("error"):
                    raise ValueError("Сервер модели сообщил об ошибке генерации")
                delta = item.get("message", {}).get("content", "") if settings.provider == "ollama" else (item.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                if isinstance(delta, str) and delta:
                    # Check inside large provider chunks too. Closing this async
                    # generator also closes the HTTP response and stops decoding.
                    for start in range(0, len(delta), 64):
                        piece = delta[start:start + 64]
                        if output_schema is None and repetition.repetitive(piece):
                            raise RepetitionStopped("Остановила ответ: модель начала повторяться. Попробуйте задать вопрос короче или сменить модель.")
                        yield piece
                reason = item.get("done_reason") if settings.provider == "ollama" else (item.get("choices") or [{}])[0].get("finish_reason")
                if reason in {"length", "max_tokens"}:
                    raise ResponseLimitReached("Ответ достиг лимита длины. Можно продолжить его кнопкой «Продолжить ответ».")
                if item.get("done") is True or reason:
                    finished = True
            if not finished:
                raise IncompleteResponse("Поток ответа оборвался без подтверждения завершения. Можно продолжить сохранённый текст.")


async def structured(settings: Settings, messages: list[dict], schema: dict, *, max_chars: int = 2048) -> str:
    """A bounded internal decision, separate from user-visible answer streaming."""
    async def collect(output_schema):
        result = ""
        payload = messages
        if output_schema is None:
            instruction = "\nВерни только JSON по этой схеме: " + json.dumps(schema, ensure_ascii=False)
            payload = ([{**messages[0], "content": messages[0]["content"] + instruction}, *messages[1:]]
                       if messages and messages[0]["role"] == "system" else [{"role": "system", "content": instruction}, *messages])
        async with aclosing(chat(settings, payload, output_schema=output_schema)) as output:
            async for delta in output:
                result += delta
                if len(result) > max_chars:
                    raise ValueError("Слишком длинный служебный ответ модели")
        return result
    try:
        return await collect(schema)
    except chatgpt.ChatGPTError as error:
        if not error.format_unsupported:
            raise
        return await collect(None)
    except httpx.HTTPStatusError as error:
        # Some compatible services do not support response_format. Retry only
        # a rejected format, never auth, quota, server or interrupted responses.
        if settings.provider != "compatible" or error.response.status_code not in {400, 422} or not any(word in error.response.text.casefold() for word in ("response_format", "json_schema", "structured output")):
            raise
        return await collect(None)


async def unload(settings: Settings):
    if settings.provider != "ollama":
        raise ValueError("Выгрузкой этой модели управляет внешний провайдер")
    async with client(settings) as http:
        response = await http.post("api/generate", json={"model": settings.model, "keep_alive": 0})
        response.raise_for_status()


async def prepare(settings: Settings):
    if settings.provider != "ollama":
        return  # Cloud model loading is controlled by its provider; no paid warm-up query.
    async with client(settings) as http:
        response = await http.post("api/generate", json={"model": settings.model, "prompt": "", "stream": False, "keep_alive": {"eco": "1m", "balanced": "5m", "quality": "15m"}[settings.profile], "options": {"num_ctx": settings.context_tokens}})
        response.raise_for_status()


def describe_error(error: Exception) -> str:
    if "redirect target not allowed" in str(error):
        return "Ollama не может скачать модель через текущую DNS/VPN-конфигурацию. Скачайте GGUF из доверенного источника и используйте импорт локального файла."
    if isinstance(error, httpx.ConnectError):
        return "Не удалось подключиться к серверу модели. Запустите Ollama или проверьте адрес в настройках."
    if isinstance(error, httpx.TimeoutException):
        return "Модель не ответила вовремя. Проверьте её состояние и доступную память."
    if isinstance(error, httpx.HTTPStatusError):
        return f"Сервер вернул HTTP {error.response.status_code}. Проверьте модель, адрес и ключ подключения."
    return str(error)[:300] or "Не удалось выполнить операцию"
