"""Optional administrator-configured API, with live model discovery and no endpoint selected by a message."""
import asyncio
import json
import time

import httpx

from ..protocol import Capability, GatewayError, Model, OfficialAPIAdapter, ProviderEvent
from ..sse import bounded_lines


def upstream_error(status):
    code, message = {
        401: ("session_expired", "Авторизация провайдера истекла или отклонена."),
        402: ("quota_exceeded", "Провайдер сообщил об исчерпании квоты или баланса."),
        403: ("access_denied", "Провайдер запретил доступ. Проверьте регион и разрешения аккаунта."),
        404: ("model_unavailable", "Модель или операция больше недоступна."),
        429: ("rate_limited", "Достигнут лимит провайдера. Автоматического переключения аккаунта нет."),
    }.get(status, ("provider_unavailable", "Провайдер временно недоступен."))
    return GatewayError(code, message, 502, status >= 500 or status == 429)


class CompatibleAdapter(OfficialAPIAdapter):
    def __init__(self, endpoint, transport=None):
        if not endpoint.startswith("https://") and transport is None:
            raise ValueError("Upstream API endpoint must use HTTPS")
        self.endpoint = endpoint.rstrip("/")
        self.transport = transport

    def client(self, account):
        credential = account.get("credential", "")
        return httpx.AsyncClient(base_url=self.endpoint + "/", headers={"Authorization": "Bearer " + credential} if credential else {},
                                 timeout=httpx.Timeout(60, connect=10), follow_redirects=False, trust_env=False, transport=self.transport)

    async def status(self, account):
        try:
            await self.models(account)
            return {"status": "connected"}
        except GatewayError as error:
            return {"status": error.code}

    async def models(self, account):
        try:
            async with self.client(account) as client:
                response = await client.get("models")
                if response.status_code != 200:
                    raise upstream_error(response.status_code)
                if len(response.content) > 2 * 1024 * 1024:
                    raise GatewayError("provider_changed", "Каталог провайдера слишком большой.", 502)
                data = response.json().get("data", [])
                if not isinstance(data, list):
                    raise ValueError()
                result = []
                for item in data[:500]:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not 0 < len(item["id"]) <= 200:
                        continue
                    features = {feature: Capability(state="advertised", evidence="chat_completions_protocol", observed_at=time.time()) for feature in ("text", "streaming")}
                    # /models IDs alone establish neither vision nor media/tool support.
                    result.append(Model(id=item["id"], name=str(item.get("name", item["id"]))[:200], capabilities=features))
                return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise GatewayError("provider_unavailable", "Не удалось обновить каталог провайдера.", 502, True) from None

    async def stream(self, account, model, messages, options):
        payload = {"model": model.id, "messages": messages, "stream": True}
        finished = False
        try:
            async with asyncio.timeout(300):
                async with self.client(account) as client:
                    async with client.stream("POST", "chat/completions", json=payload) as response:
                        if response.status_code != 200:
                            raise upstream_error(response.status_code)
                        async for line in bounded_lines(response):
                            if len(line) > 256 * 1024:
                                raise GatewayError("provider_changed", "Слишком большое событие провайдера.", 502)
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if raw == "[DONE]":
                                finished = True
                                break
                            event = json.loads(raw)
                            if "error" in event:
                                raise GatewayError("stream_interrupted", "Провайдер прервал ответ.", 502, True)
                            for choice in event.get("choices", []):
                                delta = choice.get("delta", {})
                                if delta.get("tool_calls"):
                                    raise GatewayError("capability_unavailable", "Этот API-адаптер ещё не поддерживает выполнение инструментов.", 422)
                                text = delta.get("content")
                                if isinstance(text, str) and text:
                                    yield ProviderEvent("message.delta", {"text": text})
                                reason = choice.get("finish_reason")
                                if reason in {"length", "content_filter", "tool_calls", "function_call"}:
                                    raise GatewayError("stream_interrupted", "Провайдер остановил ответ по ограничению. Частичный текст сохранён.", 502)
                                if reason == "stop":
                                    finished = True
                        if not finished:
                            raise GatewayError("stream_interrupted", "Поток провайдера оборвался. Частичный ответ сохранён.", 502, True)
        except (httpx.HTTPError, TimeoutError):
            raise GatewayError("upstream_timeout", "Связь с провайдером прервалась. Частичный ответ сохранён.", 502, True) from None
        except (ValueError, TypeError, AttributeError):
            raise GatewayError("provider_changed", "Изменился формат ответа провайдера.", 502) from None
