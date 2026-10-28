import asyncio
import json
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from core import information, providers, webfetch, websearch
from core.api import create_app
from core.config import Settings
from core.backups import Backups
from core.storage import Store


def transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(handler)))
    async def dns(*args):
        return ["93.184.216.34"]
    monkeypatch.setattr(webfetch, "addresses", dns)


@pytest.mark.parametrize("text,kind", [("Прочитай страницу https://example.com/article", "page"),
    ("Перескажи https://example.com/article что сказано о сроке?", "page"),
    ("Какая погода в Екатеринбурге?", "weather"), ("Погода завтра", "weather"),
    ("Курс доллара", "currency"), ("Курсы валют", "currency"),
    ("Он сказал прочитай страницу https://example.com", None), ("Не узнавай погоду", None),
    ("Объясни, как узнавать погоду", None)])
def test_explicit_requests(text, kind):
    item = information.request(text)
    assert (item["kind"] if item else None) == kind


@pytest.mark.parametrize("url", ["https://127.0.0.1/", "https://192.168.1.3/", "file:///secret", "https://user:pass@example.org", "http://foo.local/a"])
def test_no_network_for_private_url(monkeypatch, url):
    transport(monkeypatch, lambda _: pytest.fail("network"))
    with pytest.raises(websearch.SearchError):
        asyncio.run(webfetch.page(url))


@pytest.mark.parametrize("values", [["127.0.0.1"], ["93.184.216.34", "192.168.1.1"], ["::ffff:127.0.0.1"], ["2002:7f00:1::"], ["169.254.169.254"]])
def test_dns_rebinding_and_mixed_answers(monkeypatch, values):
    async def scenario():
        async def resolve(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443)) for value in values]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        with pytest.raises(websearch.SearchError):
            await webfetch.addresses("public.example.org", 443)
    asyncio.run(scenario())


def test_fetch_pins_ip_retains_host_tls_and_never_follows_private_redirect(monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        assert req.url.host == "93.184.216.34"
        assert req.headers["host"] == "example.org"
        assert req.extensions["sni_hostname"] == "example.org"
        assert "authorization" not in req.headers and "cookie" not in req.headers
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private", "set-cookie": "secret=yes"})
    transport(monkeypatch, handler)
    with pytest.raises(websearch.SearchError):
        asyncio.run(webfetch.page("https://example.org"))
    assert len(calls) == 1


@pytest.mark.parametrize("values", [["93.184.216.34"], ["198.18.0.7"], ["93.184.216.34", "127.0.0.1"]])
def test_public_dns_does_not_weaken_public_address_checks(monkeypatch, values):
    calls = []
    def handler(req):
        calls.append(req)
        assert req.url.host == "1.1.1.1" and req.headers["host"] == "cloudflare-dns.com"
        assert req.extensions["sni_hostname"] == "cloudflare-dns.com"
        assert req.url.params["name"] == "example.org"
        return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "data": value} for value in values]})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(handler)))
    if len(values) == 1 and values[0] == "93.184.216.34":
        assert asyncio.run(webfetch.addresses("example.org", 443, "cloudflare")) == values
    else:
        with pytest.raises(websearch.SearchError):
            asyncio.run(webfetch.addresses("example.org", 443, "cloudflare"))
    assert len(calls) == 1


@pytest.mark.parametrize("response,expected", [
    (lambda: httpx.Response(200, content=b"binary", headers={"content-type": "application/pdf"}), "тип"),
    (lambda: httpx.Response(200, content=b"x" * (webfetch.MAX_BYTES + 1), headers={"content-type": "text/plain"}), "размер"),
    (lambda: httpx.Response(200, text="x" * 120001, headers={"content-type": "text/plain"}), "120 000"),
    (lambda: httpx.Response(200, text="<script>render()</script>", headers={"content-type": "text/html"}), "недостаточно"),
    (lambda: httpx.Response(403), "закрыл"),
    (lambda: httpx.Response(302, headers={"location": "https://example.org/loop"}), "перенаправлений"),
])
def test_page_limits_and_errors(monkeypatch, response, expected):
    transport(monkeypatch, lambda _: response())
    with pytest.raises(websearch.SearchError, match=expected):
        asyncio.run(webfetch.page("https://example.org"))


def test_html_is_inert_and_old_encoding_supported(monkeypatch):
    html = '<title>Заголовок</title><nav>menu</nav><main><h1>Начало</h1><p>Проверенный срок: КЕДР-84. ' + "Данные. " * 10 + '</p><script>launch()</script><form>password</form><p>Конец</p></main>'
    transport(monkeypatch, lambda _: httpx.Response(200, content=html.encode("cp1251"), headers={"content-type": "text/html; charset=windows-1251"}))
    row = asyncio.run(webfetch.page("https://example.org/article#section"))
    assert row["title"] == "Заголовок" and row["url"] == "https://example.org/article"
    assert "КЕДР-84" in row["snippet"] and row["snippet"].endswith("Конец")
    assert all(word not in row["snippet"] for word in ("password", "launch", "menu"))


def test_weather_and_currency_do_not_require_search_or_model(monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        # Host is original even though the connection uses a literal public IP.
        if req.headers["host"] == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "Екатеринбург", "country": "Россия", "latitude": 56.8, "longitude": 60.6}]})
        if req.headers["host"] == "api.open-meteo.com":
            return httpx.Response(200, json={"current": {"time": "2026-10-18T13:15", "temperature_2m": 4.5, "apparent_temperature": 2.5, "weather_code": 3, "wind_speed_10m": 2.1},
                "current_units": {"temperature_2m": "°C", "wind_speed_10m": "m/s"}, "timezone": "Asia/Yekaterinburg",
                "daily": {"time": ["2026-10-18", "2026-10-19"], "temperature_2m_min": [1, 2], "temperature_2m_max": [6, 7], "weather_code": [3, 61], "precipitation_probability_max": [40, 60]}})
        return httpx.Response(200, content=b'<ValCurs Date="17.10.2026"><Valute><CharCode>USD</CharCode><Nominal>10</Nominal><Value>790,5000</Value></Valute></ValCurs>', headers={"content-type": "application/xml"})
    transport(monkeypatch, handler)
    config = Settings(weather_enabled=True, currency_enabled=True, weather_city="Екатеринбург, Россия")
    text, source = asyncio.run(information.fetch(config, information.request("Погода завтра")))
    assert "19.10.2026" in text and "2…7" in text and "небольшой дождь" in text
    assert source["provider"] == "open-meteo" and len(calls) == 2
    assert calls[0].url.params["name"] == "Екатеринбург, Россия"
    text, source = asyncio.run(information.fetch(config, information.request("Курс доллара")))
    assert "17.10.2026" in text and "79.0500 RUB" in text and "покупки/продажи" in text
    assert source["provider"] == "cbr" and len(calls) == 3


def test_weather_ambiguity_and_disabled_sources_never_guess(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"results": [{"name": "Paris", "country": "France", "latitude": 48, "longitude": 2}, {"name": "Paris", "country": "USA", "latitude": 34, "longitude": -95}]}))
    with pytest.raises(websearch.SearchError, match="несколько мест"):
        asyncio.run(information.fetch(Settings(weather_enabled=True), information.request("Погода в Paris")))
    transport(monkeypatch, lambda _: pytest.fail("network"))
    with pytest.raises(websearch.SearchError, match="выключен"):
        asyncio.run(information.fetch(Settings(), information.request("Курс евро")))


def test_page_chat_sources_scope_and_backup(tmp_path, monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text="<main><p>Код КЕДР-84. " + "Проверенные сведения. " * 15 + "</p></main>", headers={"content-type": "text/html"}))
    prompts = []
    async def chat(settings, messages):
        prompts.append(messages)
        yield "КЕДР-84 [1]."
    monkeypatch.setattr(providers, "chat", chat)
    with TestClient(create_app(tmp_path, "information-test-0123456789abcdef"), headers={"Authorization": "Bearer information-test-0123456789abcdef"}) as api:
        current = api.get("/settings").json()
        assert api.put("/settings", json={**current, "web_read_enabled": True}).status_code == 200
        response = api.post("/chat", json={"text": "Прочитай страницу https://example.org/article"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        answer = next(row["message"] for row in events if row["type"] == "done")
        assert answer["web_search"]["provider"] == "page" and "КЕДР-84" in prompts[0][0]["content"]
        assert api.get("/messages").json()[-1] == answer
        assert api.get("/memory-candidates").json() == []
    source = Store(tmp_path)
    target = Store(tmp_path / "restore")
    backups = Backups(target)
    backups.restore(backups.preview(Backups(source).export())["ticket"], connections=True)
    assert target.messages()[-1]["web_search"] == answer["web_search"]
    assert target.settings().web_read_enabled is False


def test_full_page_processing_covers_end_and_never_passes_generated_text(monkeypatch):
    text = "А" * 4000 + " КОНЕЦ-СРОК-84"
    batches = []
    async def select(settings, records, limit, prompt):
        batches.extend(records)
        return records[-limit:]
    monkeypatch.setattr(information.document_summary, "select", select)
    async def scenario():
        updates = [item async for item in information.page_context(Settings(), {"results": [{"title": "Page", "snippet": text}]}, "Срок?", 1200)]
        assert updates[-1]["type"] == "prepared" and "КОНЕЦ-СРОК-84" in updates[-1]["text"]
    asyncio.run(scenario())
    assert any("КОНЕЦ-СРОК-84" in row["text"] for row in batches)
    assert "".join(row["text"] for row in {row["id"]: row for row in batches}.values()) == text


@pytest.mark.parametrize("text,codes", [("Какой курс лечения ангины?", None), ("Курс молодого бойца", None), ("Курс доллара к рублю", ["USD"]), ("Курсы валют", ["USD", "EUR", "CNY"])])
def test_currency_requires_a_currency_name(text, codes):
    item = information.request(text)
    assert (item["codes"] if item else None) == codes


def test_rate_against_rouble_is_not_rejected_as_a_date(monkeypatch):
    xml = b'<ValCurs Date="17.10.2026"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>79,0500</Value></Valute></ValCurs>'
    transport(monkeypatch, lambda request: httpx.Response(200, content=xml, headers={"content-type": "application/xml"}))
    text, _ = asyncio.run(information.fetch(Settings(currency_enabled=True), information.request("Курс доллара к рублю")))
    assert "79.0500 RUB" in text
    with pytest.raises(websearch.SearchError, match="Поддержан"):
        asyncio.run(information.fetch(Settings(currency_enabled=True), information.request("Курс доллара к понедельнику")))
