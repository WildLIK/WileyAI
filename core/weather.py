"""Direct weather forecasts. Explicit place, no location inference or LLM."""
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import webfetch, websearch

GEOCODER = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ALIASES = {"москве": "Москва", "москвы": "Москва", "екатеринбурге": "Екатеринбург", "перми": "Пермь",
           "санкт-петербурге": "Санкт-Петербург", "петербурге": "Санкт-Петербург", "казани": "Казань",
           "новосибирске": "Новосибирск", "тюмени": "Тюмень", "сочи": "Сочи", "уфе": "Уфа",
           "сургуте": "Сургут", "сургута": "Сургут", "нижнесортымском": "Нижнесортымский", "нижнесортымского": "Нижнесортымский"}
PERIOD_ERROR = "Поддержана погода сейчас, сегодня, завтра, послезавтра или на неделю. Уточните период."


def request(text, name="Уайли"):
    value = text.strip().strip("?.! ")
    if value.startswith(('"', '«', '“', '`')): return None
    value = re.sub(r"^" + re.escape(name) + r"\s*[,!:]?\s+", "", value, flags=re.I)
    value = re.sub(r"^пожалуйста[, ]+", "", value, flags=re.I)
    value = re.sub(r"^(?:покажи|скажи|подскажи|узнай|посмотри|расскажи|дай)(?:\s+мне)?[, ]+", "", value, flags=re.I)
    value = re.sub(r"^(?:что|как)(?:\s+там)?\s+(?:с\s+)?погод(?:ой|а)\b", "погода", value, flags=re.I)
    found = re.search(r"\b(?:погод[ауы]|прогноз(?:\s+погоды)?)\b", value, re.I)
    if not found: return None
    prefix = value[:found.start()].strip()
    if prefix and not re.fullmatch(r"(?:(?:какая|какую|будет|сейчас|сегодня|завтра|послезавтра|на|неделю)\s*)+", prefix, re.I): return None
    detail = (prefix + " " + value[found.end():]).strip()
    if re.search(r"\b(?:вчера|выходные|выходных|месяц|утром|вечером|ночью|вечер|утро|снег|дождь)\b|\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}", detail, re.I):
        return {"kind": "weather", "error": PERIOD_ERROR}
    week = re.search(r"(?:на\s+)?(?:неделю|семь дней|7 дней)\b", detail, re.I)
    periods = [word for word in ("сегодня", "сейчас", "завтра", "послезавтра") if re.search(r"\b" + word + r"\b", detail, re.I)]
    if len(set(periods) - {"сейчас", "сегодня"}) > 1 or week and any(word in periods for word in ("завтра", "послезавтра")):
        return {"kind": "weather", "error": PERIOD_ERROR}
    day = 2 if "послезавтра" in periods else 1 if "завтра" in periods else 0
    interval = re.search(r"через\s+(\d{1,2})\s+д(?:ень|ня|ней)\b", detail, re.I)
    if interval:
        if periods or week or not 0 <= int(interval[1]) <= 6: return {"kind": "weather", "error": PERIOD_ERROR}
        day = int(interval[1]); detail = detail[:interval.start()] + detail[interval.end():]
    if re.search(r"\bчерез\b", detail, re.I) and not interval: return {"kind": "weather", "error": PERIOD_ERROR}
    detail = re.sub(r"(?:на\s+)?(?:неделю|семь дней|7 дней)\b", "", detail, flags=re.I)
    detail = re.sub(r"\b(?:на\s+)?(?:сегодня|сейчас|завтра|послезавтра)\b", "", detail, flags=re.I)
    detail = re.sub(r"\b(?:какая|какую|будет|пожалуйста)\b", "", detail, flags=re.I)
    detail = re.sub(r"\s+", " ", detail).strip(" ,.!?")
    detail = re.sub(r"^(?:на\s+)?(?:в|во|для)\s+|^на\s+", "", detail, flags=re.I).strip()
    return {"kind": "weather", "city": detail, "day": day, **({"days": 7} if week else {})}


def key(value): return re.sub(r"[^\w]", "", str(value).casefold().replace("ё", "е"))


def region(value):
    return "Ханты-Мансийский АО" if key(value) in {"хмао", "югра", "хмаоюгра", "хантымансийскийао", "хантымансийскийавтономныйокруг", "хантымансийскийавтономныйокругюгра"} else "Россия" if key(value) in {"рф", "россия"} else value


def city_name(value):
    value = re.sub(r"\s+(?:в|во)\s+(хмао(?:-югра)?|югре)\s*$", ", Ханты-Мансийский АО", value.strip(), flags=re.I)
    if not 2 <= len(value) <= 100 or not re.fullmatch(r"[\w ,.'’()\-]+", value, re.UNICODE): raise websearch.SearchError("Укажите город и при необходимости регион или страну через запятую")
    parts = [part.strip() for part in value.split(",")]
    if not 1 <= len(parts) <= 3 or any(not part for part in parts): raise websearch.SearchError("Укажите город, затем регион или страну через запятую")
    parts[0] = ALIASES.get(parts[0].casefold(), parts[0])
    return [parts[0], *[region(part) for part in parts[1:]]]


def number(value, low, high):
    if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high: raise websearch.SearchError("Сервис вернул неполные или некорректные числовые данные")
    return value


def weather_code(code):
    code = number(code, 0, 99)
    if int(code) != code: raise websearch.SearchError("Сервис вернул некорректный код погоды")
    return {0: "ясно", 1: "малооблачно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь", 51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "ледяная морось", 61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа", 80: "ливень", 81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза", 96: "гроза с градом", 97: "гроза", 99: "гроза с градом"}.get(code, "код погоды " + str(code))


async def read_json(url, dns_mode="system"):
    _, _, _, data = await webfetch.read(url, "application/json", limit=512 * 1024, dns_mode=dns_mode)
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict) or value.get("error"): raise ValueError()
        return value
    except (ValueError, RecursionError) as error: raise websearch.SearchError("Сервис вернул некорректные данные") from error


class ForecastQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str = Field(min_length=2, max_length=100)
    day: int = Field(default=0, ge=0, le=6, strict=True)
    days: int = Field(default=1, ge=1, le=7, strict=True)

    @model_validator(mode="after")
    def horizon(self):
        if self.day + self.days > 7: raise ValueError(PERIOD_ERROR)
        return self


async def forecast(settings, city, day=0, days=1):
    if not settings.weather_enabled: raise websearch.SearchError("Погода выключена. Включите её в «Настройки → Интернет»")
    if not city: raise websearch.SearchError("Укажите город: «Погода в Сургуте, ХМАО» или сохраните его в настройках")
    query = ForecastQuery(city=city, day=day, days=days)
    parts = city_name(query.city)
    geo_url = GEOCODER + "?" + urlencode({"name": ", ".join(parts[:2]), "count": 100, "language": "ru", "format": "json"})
    geo = await read_json(geo_url, settings.web_dns)
    rows = geo.get("results", [])
    if not isinstance(rows, list) or not rows or len(rows) > 100 or any(not isinstance(row, dict) for row in rows): raise websearch.SearchError("Город не найден. Укажите название в начальной форме и регион или страну")
    exact = [row for row in rows if key(row.get("name", "")) == key(parts[0])]
    choices = exact or rows
    if len(parts) > 1:
        choices = [row for row in choices if all(key(part) in {key(region(row.get(field, ""))) for field in ("country", "country_code", "admin1", "admin2")} for part in parts[1:])]
    if not choices: raise websearch.SearchError("Не найдено место в указанном регионе. Уточните город, регион или страну")
    unique = {}
    for row in choices:
        latitude, longitude = number(row.get("latitude"), -90, 90), number(row.get("longitude"), -180, 180)
        unique[(latitude, longitude)] = row
    if len(unique) != 1:
        names = [", ".join(str(row[field])[:100] for field in ("name", "admin1", "country") if row.get(field)) for row in choices[:4]]
        raise websearch.SearchError("Найдено несколько мест: " + "; ".join(names) + ". Уточните город и регион или страну через запятую")
    place = next(iter(unique.values()))
    label = ", ".join(str(place[field])[:100] for field in ("name", "admin1", "country") if place.get(field))[:240]
    if not isinstance(place.get("name"), str) or not place["name"]: raise websearch.SearchError("Справочник вернул некорректное название места")
    url = FORECAST + "?" + urlencode({"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": max(2, day + days), "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm", "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m", "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    data = await read_json(url, settings.web_dns)
    try:
        zone = data["timezone"]
        if not isinstance(zone, str) or len(zone) > 100: raise ValueError()
        ZoneInfo(zone)
        daily = data["daily"]
        fields = ("time", "temperature_2m_min", "temperature_2m_max", "weather_code", "precipitation_probability_max")
        if any(not isinstance(daily[field], list) or len(daily[field]) < day + days for field in fields): raise ValueError()
        units = data.get("daily_units", {})
        if units and (units.get("temperature_2m_min") != "°C" or units.get("temperature_2m_max") != "°C" or units.get("precipitation_probability_max") != "%"): raise ValueError()
        selected = []
        for index in range(day, day + days):
            date = datetime.strptime(daily["time"][index], "%Y-%m-%d").date()
            if selected and date != datetime.fromisoformat(selected[-1]["date"]).date() + timedelta(days=1): raise ValueError()
            low, high = number(daily["temperature_2m_min"][index], -100, 70), number(daily["temperature_2m_max"][index], -100, 70)
            if low > high: raise ValueError()
            selected.append({"date": date.isoformat(), "low": low, "high": high, "condition": weather_code(daily["weather_code"][index]), "rain": number(daily["precipitation_probability_max"][index], 0, 100)})
        current = None
        if day == 0:
            row, units = data["current"], data["current_units"]
            if units.get("temperature_2m") != "°C" or units.get("wind_speed_10m") != "m/s" or units.get("apparent_temperature", "°C") != "°C": raise ValueError()
            observed = datetime.fromisoformat(row["time"])
            if observed.date().isoformat() != selected[0]["date"]: raise ValueError()
            current = {"time": observed.isoformat(timespec="minutes"), "temperature": number(row["temperature_2m"], -100, 70), "feels_like": number(row["apparent_temperature"], -120, 80), "condition": weather_code(row["weather_code"]), "wind": number(row["wind_speed_10m"], 0, 150)}
    except (KeyError, TypeError, ValueError, IndexError, ZoneInfoNotFoundError) as error: raise websearch.SearchError("Погодный сервис вернул неполный или некорректный прогноз") from error
    text = label + "."
    if current:
        text += f"\nСейчас: {current['temperature']:g} °C, ощущается как {current['feels_like']:g} °C, {current['condition']}, ветер {current['wind']:g} м/с."
        text += f" Расчёт на {current['time']} ({zone})."
    for row in selected:
        text += f"\nПрогноз на {datetime.fromisoformat(row['date']):%d.%m.%Y}: {row['condition']}. Температура {row['low']:g}…{row['high']:g} °C, вероятность осадков {row['rain']:g}%."
    text += "\nOpen-Meteo: модельный прогноз, не показание личного датчика. Местоположение: GeoNames."
    return {"place": label, "timezone": zone, "current": current, "days": selected, "checked_at": datetime.now(timezone.utc).isoformat(), "text": text, "sources": [{"title": "Open-Meteo · " + label[:160], "url": url, "snippet": text[:600]}, {"title": "GeoNames через Open-Meteo · найденное место", "url": geo_url, "snippet": label}]}
