import asyncio
import copy
from datetime import date, timedelta
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from core import information, weather, webfetch, websearch
from core.api import create_app
from core.config import Settings
from core.storage import Store


@pytest.mark.parametrize("text,city,day,days", [
    ("Какая сейчас погода?", "", 0, 1),
    ("Уайли, скажи какая погода будет завтра в Сургуте?", "Сургуте", 1, 1),
    ("Погода в Сургуте на завтра", "Сургуте", 1, 1),
    ("Какая погода послезавтра в Нижнесортымском, ХМАО?", "Нижнесортымском, ХМАО", 2, 1),
    ("Покажи прогноз на неделю в Сургуте", "Сургуте", 0, 7),
    ("Прогноз погоды в Нижнесортымском на семь дней", "Нижнесортымском", 0, 7),
    ("Как там с погодой в Сургуте?", "Сургуте", 0, 1),
    ("Погода через 3 дня в Сургуте", "Сургуте", 3, 1),
])
def test_natural_weather_requests(text, city, day, days):
    item = information.request(text)
    assert item and item["kind"] == "weather" and item["city"] == city and item["day"] == day and item.get("days", 1) == days


@pytest.mark.parametrize("text", ['«Погода завтра»', "Объясни, как узнавать погоду", "Не узнавай погоду", "Он сказал покажи погоду", "Если завтра погода", "В документе: погода завтра"])
def test_non_requests_do_not_fetch(text): assert weather.request(text) is None


@pytest.mark.parametrize("text", ["Погода вчера", "Погода через 20 дней", "Погода на месяц", "Погода завтра послезавтра", "Прогноз на неделю завтра", "Погода вечером", "Погода через неделю"])
def test_unsupported_dates_never_become_today(text): assert weather.request(text).get("error")


@pytest.fixture
def remote(monkeypatch):
    rows = [
        {"name": "Сургут", "admin1": "Ханты-Мансийский АО", "country": "Россия", "country_code": "RU", "latitude": 61.25757, "longitude": 73.41775},
        {"name": "Сургут", "admin1": "Самарская область", "country": "Россия", "country_code": "RU", "latitude": 53.92, "longitude": 51.2},
        {"name": "Нижнесортымский", "admin1": "Ханты-Мансийский АО", "country": "Россия", "country_code": "RU", "latitude": 62.43965, "longitude": 71.76029},
    ]
    days = [(date(2026, 10, 20) + timedelta(days=index)).isoformat() for index in range(7)]
    forecast = {"timezone": "Asia/Yekaterinburg", "current": {"time": "2026-10-20T19:00", "temperature_2m": -3.5, "apparent_temperature": -7, "wind_speed_10m": 4, "weather_code": 71}, "current_units": {"temperature_2m": "°C", "apparent_temperature": "°C", "wind_speed_10m": "m/s"}, "daily_units": {"temperature_2m_min": "°C", "temperature_2m_max": "°C", "precipitation_probability_max": "%"}, "daily": {"time": days, "temperature_2m_min": [-7] * 7, "temperature_2m_max": [-1] * 7, "weather_code": [71] * 7, "precipitation_probability_max": [70] * 7}}
    calls = []
    real = httpx.AsyncClient
    def handle(request):
        calls.append(request)
        if request.headers["host"] == "geocoding-api.open-meteo.com":
            # Deliberately return broad results to prove qualifiers are checked
            # locally, rather than trusting only the geocoder's ranking.
            return httpx.Response(200, json={"results": rows})
        assert request.headers["host"] == "api.open-meteo.com"
        return httpx.Response(200, json=forecast)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**kw, transport=httpx.MockTransport(handle)))
    async def addresses(*args): return ["93.184.216.34"]
    monkeypatch.setattr(webfetch, "addresses", addresses)
    return rows, forecast, calls


def test_region_and_inflection_select_correct_surgut_and_preserve_default(remote):
    _, _, calls = remote
    config = Settings(weather_enabled=True, weather_city="Сургут, ХМАО")
    data = asyncio.run(weather.forecast(config, config.weather_city, 0, 7))
    assert "Ханты-Мансийский" in data["place"] and len(data["days"]) == 7
    assert data["current"]["temperature"] == -3.5 and data["timezone"] == "Asia/Yekaterinburg"
    assert calls[0].url.params["name"] == "Сургут, Ханты-Мансийский АО"
    assert float(calls[1].url.params["latitude"]) == 61.25757 and calls[1].url.params["forecast_days"] == "7"
    text, source = asyncio.run(information.fetch(config, information.request("Погода послезавтра в Нижнесортымском в ХМАО")))
    assert "Нижнесортымский" in text and "22.10.2026" in text and "Сейчас:" not in text
    assert source["provider"] == "open-meteo" and config.weather_city == "Сургут, ХМАО"
    assert float(calls[-1].url.params["latitude"]) == 62.43965


def test_city_ambiguity_never_selects_largest_population_implicitly(remote):
    rows, _, calls = remote
    rows[0]["population"] = 300000
    rows[1]["population"] = 4000
    with pytest.raises(websearch.SearchError, match="несколько мест"):
        asyncio.run(weather.forecast(Settings(weather_enabled=True), "Сургут"))
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["nan", "wrong_unit", "missing_day", "wrong_timezone", "reversed", "wrong_code", "dates", "coordinates"])
def test_invalid_service_data_is_not_presented_as_forecast(remote, damage):
    rows, data, _ = remote
    if damage == "nan": data["daily"]["temperature_2m_max"][0] = None
    if damage == "wrong_unit": data["daily_units"]["temperature_2m_min"] = "°F"
    if damage == "missing_day": data["daily"]["time"] = []
    if damage == "wrong_timezone": data["timezone"] = "Wrong/Zone"
    if damage == "reversed": data["daily"]["temperature_2m_min"][0] = 20
    if damage == "wrong_code": data["current"]["weather_code"] = 1.5
    if damage == "dates": data["daily"]["time"][1] = "2026-11-01"
    if damage == "coordinates": rows[0]["latitude"] = []
    with pytest.raises(websearch.SearchError): asyncio.run(weather.forecast(Settings(weather_enabled=True), "Сургут, ХМАО", 0, 7))


def test_disabled_weather_and_invalid_horizon_do_not_use_network(remote):
    _, _, calls = remote
    with pytest.raises(websearch.SearchError, match="выключена"): asyncio.run(weather.forecast(Settings(), "Сургут"))
    with pytest.raises(ValueError): asyncio.run(weather.forecast(Settings(weather_enabled=True), "Сургут", 6, 7))
    assert not calls


def test_preview_is_authenticated_explicit_and_never_changes_saved_settings(tmp_path, remote, monkeypatch):
    token = "weather-test-local-token-123456"
    def no_model(*args, **kwargs): pytest.fail("Weather must not call a model")
    monkeypatch.setattr("core.providers.chat", no_model)
    with TestClient(create_app(tmp_path, token)) as api:
        assert api.post("/weather/preview", json={"city": "Сургут"}).status_code == 401
        api.headers["Authorization"] = "Bearer " + token
        config = api.get("/settings").json()
        response = api.post("/weather/preview", json={"city": "Нижнесортымский, ХМАО", "day": 0, "days": 7})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert "Нижнесортымский" in response.json()["place"]
        assert api.get("/settings").json() == config
        assert api.post("/weather/preview", json={"city": "Сургут", "day": True}).status_code == 422
        api.put("/settings", json={**config, "weather_enabled": True, "weather_city": "Сургут, ХМАО"})
        response = api.post("/chat", json={"text": "Какая сейчас погода?"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        message = next(row["message"] for row in events if row["type"] == "done")
        assert "Сейчас:" in message["content"] and "-3.5" in message["content"]
        assert message["web_search"]["provider"] == "open-meteo" and not api.get("/memory-candidates").json()


def test_current_weather_shares_cache_and_obeys_saved_permission(tmp_path, remote):
    _, _, calls = remote
    def weather_calls(): return [row for row in calls if row.headers.get("host", "").endswith("open-meteo.com")]
    with TestClient(create_app(tmp_path, "weather-cache-test-token-123456")) as api:
        assert api.get("/weather/current").status_code == 401
        api.headers["Authorization"] = "Bearer weather-cache-test-token-123456"
        config = api.get("/settings").json()
        assert api.get("/weather/current").status_code == 400 and not weather_calls()
        api.put("/settings", json={**config, "weather_enabled": True, "weather_city": "Сургут, ХМАО"})
        first = api.get("/weather/current")
        assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
        assert api.get("/weather/current").json() == first.json() and len(weather_calls()) == 2
        api.put("/settings", json={**config, "weather_enabled": True, "weather_city": "Нижнесортымский, ХМАО"})
        assert "Нижнесортымский" in api.get("/weather/current").json()["place"] and len(weather_calls()) == 4
        api.put("/settings", json={**config, "weather_enabled": False, "weather_city": "Нижнесортымский, ХМАО"})
        assert api.get("/weather/current").status_code == 400 and len(weather_calls()) == 4


def test_current_weather_deduplicates_windows_and_refreshes_expired_result(monkeypatch):
    async def scenario():
        now, count = [0], 0
        cache = weather.CurrentWeather(clock=lambda: now[0])
        started, release = asyncio.Event(), asyncio.Event()
        async def fetch(settings, city):
            nonlocal count
            count += 1
            started.set()
            await release.wait()
            return {"place": city, "timezone": "Europe/Moscow", "sequence": count}
        monkeypatch.setattr(weather, "forecast", fetch)
        config = Settings(weather_enabled=True, weather_city="Москва, Россия")
        first = asyncio.create_task(cache.read(config))
        await started.wait()
        second = asyncio.create_task(cache.read(config))
        release.set()
        assert (await first) == (await second) and count == 1
        now[0] = 1801
        assert (await cache.read(config))["sequence"] == 2
    asyncio.run(scenario())
