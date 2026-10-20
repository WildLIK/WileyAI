"""Public HTTP reads with DNS pinning, bounded redirects and decoded response size."""
import asyncio
import ipaddress
import re
import socket
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from .websearch import SearchError, public_url

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 120000


def global_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
    return True


async def public_dns(host):
    # Optional, visible DNS choice. Bootstrap a fixed public resolver by IP so
    # fake-IP VPN DNS cannot turn the resolver itself into a private endpoint.
    async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
        async with client.stream("GET", "https://1.1.1.1/dns-query", params={"name": host, "type": "A"},
                headers={"Host": "cloudflare-dns.com", "Accept": "application/dns-json", "Accept-Encoding": "identity"},
                extensions={"sni_hostname": "cloudflare-dns.com"}) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise SearchError("DNS-сервис вернул неподдерживаемый ответ")
            data = bytearray()
            async for part in response.aiter_bytes(chunk_size=4096):
                data.extend(part)
                if len(data) > 65536:
                    raise SearchError("Слишком большой ответ DNS-сервиса")
    try:
        value = json.loads(data)
        if value.get("Status") != 0 or value.get("TC"):
            raise ValueError()
        rows = value.get("Answer", [])
        values = list(dict.fromkeys(row["data"] for row in rows if row.get("type") == 1))
        return values
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise SearchError("DNS-сервис не вернул публичный IPv4-адрес сайта") from error


async def addresses(host, port, dns_mode="system"):
    try:
        try:
            literal = str(ipaddress.ip_address(host))
        except ValueError:
            literal = None
        if literal:
            values = [literal]
        elif dns_mode == "cloudflare":
            values = await public_dns(host)
        else:
            rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            values = list(dict.fromkeys(row[4][0] for row in rows))
        if not values or not all(global_address(value) for value in values):
            raise SearchError("DNS вернул локальный, служебный или смешанный адрес. Доступ запрещён; при VPN с fake-IP выберите публичный DNS в настройках поиска")
        return values
    except (OSError, ValueError) as error:
        if isinstance(error, SearchError):
            raise
        raise SearchError("Не удалось проверить публичный адрес сайта") from error


async def _read(url, accept, limit, dns_mode):
    for hop in range(4):
        url = public_url(url)
        if not url:
            raise SearchError("Нужен публичный адрес HTTP/HTTPS без пароля и нестандартного порта")
        original = httpx.URL(url)
        host = original.raw_host.decode("ascii")
        values = await addresses(host, original.port or (443 if original.scheme == "https" else 80), dns_mode)
        # Never resolve the hostname again between validation and connect. TLS
        # still validates the original hostname; no proxy, cookies or credentials.
        pinned = original.copy_with(host=values[0])
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=4), trust_env=False,
                                     follow_redirects=False) as client:
            async with client.stream("GET", pinned, headers={"Host": original.netloc.decode("ascii"),
                    "Accept": accept, "Accept-Encoding": "identity", "User-Agent": "WileyAI/0.11 public-reader"},
                    extensions={"sni_hostname": host}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if hop == 3 or not location:
                        raise SearchError("Слишком много перенаправлений или отсутствует конечный адрес")
                    target = urljoin(url, location)
                    if original.scheme == "https" and urlsplit(target).scheme == "http":
                        raise SearchError("Сайт перенаправляет с HTTPS на незащищённый HTTP")
                    url = target
                    continue
                if response.status_code in {401, 403}:
                    raise SearchError("Сайт закрыл доступ: требуется вход или он запрещает автоматическое чтение")
                if response.status_code == 429:
                    raise SearchError("Сервис ограничил частоту запросов. Повторите позже")
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                    raise SearchError("Сайт прислал сжатый ответ вопреки запросу. Ограничение размера не позволяет безопасно прочитать его")
                kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                allowed = {value.strip() for value in accept.split(",")}
                if kind not in allowed:
                    raise SearchError("Неподдерживаемый тип содержимого: " + (kind[:80] or "не указан"))
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > limit:
                    raise SearchError("Ответ сайта превышает разрешённый размер")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=32768):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise SearchError("Ответ сайта превышает разрешённый размер")
                return url, kind, response.headers.get("content-type", ""), bytes(data)


async def read(url, accept="text/html,application/xhtml+xml,text/plain", limit=MAX_BYTES, dns_mode="system"):
    try:
        return await asyncio.wait_for(_read(url, accept, limit, dns_mode), 20)
    except SearchError:
        raise
    except (TimeoutError, httpx.TimeoutException) as error:
        raise SearchError("Сайт не ответил вовремя") from error
    except httpx.HTTPError as error:
        raise SearchError("Не удалось загрузить данные сайта. Проверьте доступность и подключение") from error


class PageText(HTMLParser):
    """Extract inert text. Never execute JS, follow embeds or submit forms."""
    hidden_tags = {"script", "style", "template", "noscript", "svg", "nav", "footer", "form"}
    blocks = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article", "main"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.main_depth = 0
        self.in_title = False
        self.title = []
        self.body = []
        self.main = []

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden_tags:
            self.hidden.append(tag)
        if tag == "title":
            self.in_title = True
        if tag in {"main", "article"}:
            self.main_depth += 1
        if tag in self.blocks:
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if tag in self.hidden:
            self.hidden = self.hidden[:self.hidden.index(tag)]
        if tag == "title":
            self.in_title = False
        if tag in self.blocks:
            self.handle_data("\n")
        if tag in {"main", "article"} and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.body.append(data)
            if self.main_depth:
                self.main.append(data)


def clean(text):
    return "\n".join(line for raw in text.splitlines()
                     if (line := re.sub(r"\s+", " ", "".join(c for c in raw if c.isprintable() or c.isspace())).strip()))


async def page(url, dns_mode="system"):
    final, kind, content_type, data = await read(url, dns_mode=dns_mode)
    encoding = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, re.I)
    if not encoding and kind != "text/plain":
        encoding = re.search(rb"<meta\b[^>]{0,300}?charset\s*=\s*[\"']?([\w-]+)", data[:4096], re.I)
    charset = encoding[1] if encoding else "utf-8-sig"
    if isinstance(charset, bytes):
        charset = charset.decode("ascii")
    try:
        decoded = data.decode(charset, errors="replace")
    except (LookupError, UnicodeError) as error:
        raise SearchError("Не поддерживается кодировка страницы") from error
    title = urlsplit(final).hostname
    if kind == "text/plain":
        text = clean(decoded)
    else:
        parser = PageText()
        parser.feed(decoded)
        text = clean("".join(parser.main))
        if len(text) < 100:
            text = clean("".join(parser.body))
        title = clean("".join(parser.title)) or title
    if len(text) > MAX_TEXT:
        raise SearchError("На странице больше 120 000 символов. Выберите отдельную статью или загрузите документ")
    if len(text) < 40:
        raise SearchError("На странице недостаточно доступного текста. Возможно, она требует JavaScript или входа")
    return {"title": title[:180], "url": final, "snippet": text}
