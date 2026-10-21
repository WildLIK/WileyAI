"""Russian spoken numbers for Silero, which expects words rather than digits."""
from datetime import datetime
import re

from num2words import num2words

NUMBER = r"[+−-]?\d{1,15}(?:[.,]\d{1,6})?"
MONTHS = ("", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def one(value): return abs(int(value)) % 10 == 1 and abs(int(value)) % 100 != 11


def words(value, case="n"):
    raw = str(value).replace("−", "-").replace(",", ".")
    sign = "минус " if raw.startswith("-") else "плюс " if raw.startswith("+") else ""
    raw = raw.lstrip("+-")
    if "." not in raw:
        return sign + num2words(int(raw), lang="ru", case=case)
    whole, fraction = raw.split(".")
    singular = one(whole)
    point = ("целой" if case == "g" else "целая") if singular else "целых"
    single_fraction = one(fraction)
    denominator = num2words(10 ** len(fraction), lang="ru", to="ordinal", gender="f",
                           case=case if single_fraction else "g", plural=not single_fraction)
    return (sign + num2words(int(whole), lang="ru", gender="f", case=case) + " " + point + " "
            + num2words(int(fraction), lang="ru", gender="f", case=case) + " " + denominator)


def noun(value, forms, case="n"):
    raw = value.lstrip("+−-").replace(",", ".")
    if "." in raw: return forms[1]
    value = int(raw)
    if case == "g": return forms[1] if one(value) else forms[2]
    if 11 <= value % 100 <= 14: return forms[2]
    return forms[0] if value % 10 == 1 else forms[1] if value % 10 in (2, 3, 4) else forms[2]


def spoken_time(raw):
    hours, minutes = raw.split(":")
    if int(hours) > 23 or int(minutes) > 59: return raw
    return (words(hours) + " " + noun(hours, ("час", "часа", "часов")) + " "
            + num2words(int(minutes), lang="ru", gender="f") + " " + noun(minutes, ("минута", "минуты", "минут")))


def spoken_date(raw):
    value = datetime.strptime(raw, "%Y-%m-%d" if "-" in raw else "%d.%m.%Y")
    return (num2words(value.day, lang="ru", to="ordinal", gender="n") + " " + MONTHS[value.month] + " "
            + num2words(value.year, lang="ru", to="ordinal", case="g") + " года")


def silero_numbers(text):
    # Source citations are interface references, not part of the spoken answer.
    text = re.sub(r"(?<=[.!?])\s*\[\d+(?:\s*[,;–-]\s*\d+)*\]", "", text)
    def date(match):
        try:
            return spoken_date(match[1]) + (" в " + spoken_time(match[2]) if match[2] else "")
        except ValueError: return match[0]
    text = re.sub(r"(?<!\w)(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?:T(\d{2}:\d{2}))?(?!\d)", date, text)
    text = re.sub(r"(?<![\w:])(\d{1,2}:\d{2})(?![\d:])", lambda m: spoken_time(m[1]), text)
    units = {
        "temperature": (("градус", "градуса", "градусов"), " Цельсия"),
        "speed": (("метр", "метра", "метров"), " в секунду"),
        "road_speed": (("километр", "километра", "километров"), " в час"),
        "percent": (("процент", "процента", "процентов"), ""),
    }
    for kind, pattern in (("temperature", r"°\s*[CС]"), ("speed", r"м\s*/\s*с\b"),
                          ("road_speed", r"км\s*/\s*ч\b"), ("percent", "%")):
        def measurement(match):
            low, high = match[1], match[2]
            forms, suffix = units[kind]
            if high:
                return "от " + words(low, "g") + " до " + words(high, "g") + " " + noun(high, forms, "g") + suffix
            return words(low) + " " + noun(low, forms) + suffix
        text = re.sub(r"(?<![\w/.])(" + NUMBER + r")(?:\s*(?:…|\.{3}|[–—]|-(?=[+−-]?\d))\s*(" + NUMBER + r"))?\s*" + pattern,
                      measurement, text)
    text = re.sub(r"(?<![\w/.])(" + NUMBER + r")\s*(?:…|\.{3}|[–—])\s*(" + NUMBER + r")(?![\w/.])",
                  lambda m: "от " + words(m[1], "g") + " до " + words(m[2], "g"), text)
    text = re.sub(r"(?<![\w/.])(" + NUMBER + r")(?![\w/]|[.,]\d)", lambda m: words(m[1]), text)
    return re.sub(r"[ \t]+", " ", text).strip()
