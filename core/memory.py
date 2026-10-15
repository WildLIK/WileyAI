"""Local suggestions and lexical retrieval. These functions never call an LLM."""
import re
import unicodedata
import hashlib


CATEGORIES = {"fact", "preference", "profile"}
STOP_WORDS = set("какой какая какие как что где когда почему зачем это этот эта эти меня мне мой моя мои твой твоя ваши ваш для про или есть буду будет было были чтобы можно нужно надо хочу скажи расскажи помоги пожалуйста ответ ответь ответы вопрос вопросы the and what how this that with from have about".split())


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")).strip(" .!\n\t")


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalized(text).encode("utf-8")).hexdigest()


def search_expression(text: str) -> str:
    tokens = re.findall(r"[^\W_]+", normalized(text), re.UNICODE)
    terms = []
    for token in tokens:
        if len(token) < 3 or token in STOP_WORDS or token.isdigit():
            continue
        # Prefixes provide a small amount of Russian inflection tolerance.
        prefix = token[:6] if re.fullmatch(r"[а-я]+", token) else token
        if prefix not in terms:
            terms.append(prefix)
    return " OR ".join('"' + token + '"*' for token in terms[:12])


def infer_category(text: str) -> str:
    value = normalized(text)
    if re.match(r"(?:я )?(?:предпочитаю|люблю|не люблю)|мне (?:удобнее|нравится|не нравится)", value):
        return "preference"
    if re.match(r"я (?:работаю|учусь|занимаюсь)|мой проект", value):
        return "profile"
    return "fact"


def suggestions(text: str) -> list[dict]:
    # Only direct first-person statements. Documents, assistant output, examples and
    # quoted statements are never mined. Credentials are not useful suggestions.
    if any(mark in text for mark in ('"', '«', '»', '“', '”', '`')):
        return []
    if re.search(r"\b(?:парол\w*|токен|секрет|api[ _-]?(?:key|ключ)|password|token)\b|sk-[a-z0-9]|https?://\S+@", text, re.I):
        return []
    result = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        content = sentence.strip(" .!\t")
        if "?" in content or not 8 <= len(content) <= 500:
            continue
        value = normalized(content)
        if re.search(r"\b(?:если|бы|например|допустим|цитата|представь|представим|история|персонаж)\b", value):
            continue
        if re.match(r"(?:я (?:предпочитаю|люблю|не люблю|обычно|работаю|учусь|занимаюсь)|мне (?:удобнее|нравится|не нравится)|мой проект называется)\s+\S", value):
            result.append({"content": content, "category": infer_category(content)})
    return result[:3]
