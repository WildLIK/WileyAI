"""Bound upstream lines before decoding/parsing; a missing newline cannot grow memory forever."""
from .protocol import GatewayError


async def bounded_lines(response, limit=256 * 1024):
    pending = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=8192):
        for index, part in enumerate(chunk.split(b"\n")):
            if index:
                try:
                    yield bytes(pending).rstrip(b"\r").decode("utf-8")
                except UnicodeDecodeError:
                    raise GatewayError("provider_changed", "Некорректный UTF-8 в потоке провайдера.", 502) from None
                pending.clear()
            if len(pending) + len(part) > limit:
                raise GatewayError("provider_changed", "Событие провайдера слишком большое.", 502)
            pending.extend(part)
    if pending:
        # An incomplete last line is not an acknowledged SSE event.
        raise GatewayError("stream_interrupted", "Поток завершился внутри события. Частичный текст сохранён.", 502, True)
