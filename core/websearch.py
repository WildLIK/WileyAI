"""Explicit, bounded web search. Search snippets are untrusted data."""
import asyncio
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

import httpx
import keyring

from .capabilities import IntegrationAdapter
from .config import Settings

MAX_RESPONSE = 1024 * 1024
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def get_key() -> str:
    return keyring.get_password("WileyAI.Search", "brave") or ""


def set_key(value: str):
    if value:
        keyring.set_password("WileyAI.Search", "brave", value)
    else:
        try:
            keyring.delete_password("WileyAI.Search", "brave")
        except keyring.errors.PasswordDeleteError:
            pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value[:10000])
    text = unescape("".join(parser.parts))
    return re.sub(r"\s+", " ", "".join(char for char in text if char.isprintable() or char.isspace())).strip()[:limit]


def public_url(value) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or "\\" in value or any(ord(c) < 33 for c in value):
        return None
    try:
        value.encode("utf-8")
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
        if host == "localhost" or "." not in host or host.endswith((".localhost", ".local", ".internal", ".test")) or "%" in parsed.netloc:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            # Reject ambiguous numeric hosts interpreted differently by browsers.
            if re.fullmatch(r"[0-9.xa-f]+", host) and any(char.isdigit() for char in host):
                return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, UnicodeError):
        return None


def requested_query(text: str, selected: bool = False) -> str | None:
    if selected:
        return text.strip()
    match = re.fullmatch(r"(?:пожалуйста[, ]+)?(?:найди|поищи|ищи)(?: мне)? (?:в интернете|в сети|в вебе)\s*[:—,-]?\s*(.*)", text.strip(), re.I)
    return match[1].strip() if match else None


class SearchError(ValueError):
    pass


def validate_query(value: str) -> str:
    query = value.strip()
    if not 2 <= len(query) <= 500 or any(ord(c) < 32 for c in query):
        raise SearchError("Для поиска введите запрос от 2 до 500 символов в одной строке")
    return query


async def read_json(endpoint: str, params: dict, headers: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), trust_env=False, follow_redirects=False) as http:
            async with http.stream("GET", endpoint, params=params, headers=headers) as response:
                if response.status_code in {401, 403}:
                    raise SearchError("Поисковый сервис отказал в доступе. Проверьте ключ Brave или включение JSON API у SearXNG")
                if response.status_code == 429:
                    raise SearchError("Лимит поискового сервиса исчерпан. Повторите запрос позже")
                if 300 <= response.status_code < 400:
                    raise SearchError("Поисковый сервер перенаправляет запрос. Укажите его конечный адрес в настройках")
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        raise SearchError("Ответ поискового сервиса превышает лимит 1 МБ")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
    except SearchError:
        raise
    except httpx.TimeoutException as error:
        raise SearchError("Поисковый сервис не ответил вовремя") from error
    except httpx.HTTPError as error:
        raise SearchError("Не удалось обратиться к поисковому сервису. Проверьте адрес, доступность и подключение") from error
    except (ValueError, UnicodeError, RecursionError) as error:
        raise SearchError("Поисковый сервис вернул некорректный JSON. У SearXNG должен быть включён формат json") from error


class SearXNG(IntegrationAdapter):
    id = "searxng"
    required_scopes = ("web.search",)

    def __init__(self, settings: Settings):
        self.settings = settings

    async def execute(self, operation: str, arguments: dict) -> dict:
        if operation != "search":
            raise SearchError("Неподдерживаемая операция поиска")
        data = await read_json(self.settings.search_base_url + "/search", {
            "q": arguments["query"], "format": "json", "language": "ru", "categories": "general",
            "safesearch": {"off": 0, "moderate": 1, "strict": 2}[self.settings.search_filter],
        }, {"Accept": "application/json"})
        rows = data.get("results")
        if not isinstance(rows, list):
            raise SearchError("SearXNG не вернул список результатов")
        return {"rows": rows, "partial": bool(data.get("unresponsive_engines"))}


class Brave(IntegrationAdapter):
    id = "brave"
    required_scopes = ("web.search",)

    async def execute(self, operation: str, arguments: dict) -> dict:
        if operation != "search":
            raise SearchError("Неподдерживаемая операция поиска")
        try:
            key = get_key()
        except Exception as error:
            raise SearchError("Не удалось прочитать ключ поиска из хранилища Windows") from error
        if not key:
            raise SearchError("Добавьте отдельный ключ Brave Search в настройках")
        data = await read_json(BRAVE_ENDPOINT, {
            "q": arguments["query"], "count": 5, "search_lang": "ru", "text_decorations": "false",
            "safesearch": arguments["filter"],
        }, {"Accept": "application/json", "X-Subscription-Token": key})
        web = data.get("web", {})
        rows = web.get("results", []) if isinstance(web, dict) else None
        if not isinstance(rows, list):
            raise SearchError("Brave Search не вернул список результатов")
        return {"rows": rows, "partial": False}


ADAPTERS = {"searxng": lambda settings: SearXNG(settings), "brave": lambda settings: Brave()}


async def search(settings: Settings, query: str) -> dict:
    if not settings.search_enabled:
        raise SearchError("Поиск в интернете выключен. Подключите сервис и разрешите поиск в настройках")
    query = validate_query(query)
    adapter = ADAPTERS[settings.search_provider](settings)
    # This is the first network tool. The configured scope is checked in the core,
    # rather than trusting model output or a renderer-only toggle.
    try:
        raw = await asyncio.wait_for(adapter.execute("search", {"query": query, "filter": settings.search_filter}), timeout=15)
    except TimeoutError as error:
        raise SearchError("Поисковый сервис не ответил вовремя") from error
    results, seen = [], set()
    for row in raw["rows"][:50]:
        if not isinstance(row, dict):
            continue
        url = public_url(row.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({"title": plain(row.get("title"), 180) or (urlsplit(url).hostname or "Источник")[:180],
                        "url": url, "snippet": plain(row.get("content", row.get("description", "")), 600)})
        if len(results) == 5:
            break
    return {"query": query, "provider": adapter.id, "checked_at": datetime.now(timezone.utc).isoformat(), "results": results, "partial": raw["partial"]}


def context(result: dict, budget: int) -> str:
    chosen = []
    for index, row in enumerate(result["results"], 1):
        item = {"source": index, "title": row["title"], "snippet": row["snippet"][:400]}
        if len(json.dumps([*chosen, item], ensure_ascii=False)) > budget:
            break
        chosen.append(item)
    return json.dumps(chosen, ensure_ascii=False)
