"""Explicit read-only Gmail commands, without passing letters to a model."""
import re

from .mail import InboxQuery


LETTER_PREFIX = "Письмо Gmail — данные из почты."
HELP = "Можно сказать «прочитай последнее письмо из Gmail» или «прочитай последнее непрочитанное письмо». Для поиска и выбора других писем откройте раздел «Почта»."
MAIL = r"gmail|g-mail|джим[еэ]йл|джи\s*м[еэ]йл|почт\w*|письм\w*"
READ = r"прочитай|прочти|прочесть|прочитать|зачитай|зачесть|зачитать|читай|покажи|посмотри|проверь"
FOLLOWUP = r"(?:да[, ]+)?(?:прочитай|прочти|зачитай|последнее сообщение|последнее письмо|давай|читай)(?: его| его вслух| вслух)?"


def request(text, history=(), name="Уайли"):
    value = text.strip()
    if len(value) > 600 or value.startswith(('"', '«', "'", "`")):
        return None
    value = re.sub(r"^" + re.escape(name) + r"\s*[,!:]\s*", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip(" .!?,")
    if re.search(r"\b(?:не|нельзя|не надо|не нужно)\s+(?:" + READ + r")\b", value):
        return None
    if re.match(r"(?:как|почему|зачем|объясни|научи|напиши|переведи|он сказал)\b", value):
        return None
    domain = bool(re.search(r"\b(?:" + MAIL + r")\b", value))
    reading = bool(re.search(r"\b(?:" + READ + r")\b", value))
    # A short follow-up may refer only to a recent user request, never to an
    # instruction or an apparent tool promise found inside an email/model reply.
    if re.fullmatch(FOLLOWUP, value):
        for row in reversed(history):
            if row["role"] != "user":
                continue
            previous = request(row["content"], name=name)
            if previous:
                return previous
            if not re.fullmatch(FOLLOWUP, row["content"].lower().strip(" .!?,")):
                break
    if not domain:
        return None
    if not reading:
        return None
    if re.search(r"\b(?:отправ\w*|перешли|удали|удалить|ответь|все|всю|найди|от\s+\S+@)", value):
        return {"kind": "help"}
    if re.search(r"\b(?:первые|последние)\s+\d|\b(?:два|три|четыре|пять)\b", value):
        return {"kind": "help"}
    if re.search(r"\b(?:отправлен\w*|вчера|сегодня|позавчера|позапрошл\w*|предпоследн\w*|от\s+(?!gmail\b|гугл\b)\S+|за\s+\S+|с\s+темой)\b", value):
        return {"kind": "help"}
    return {"kind": "latest", "folder": "unread" if "непрочитан" in value else "inbox"}


async def handle(mail, store, command):
    if command["kind"] == "help":
        return HELP
    async with mail.lock:
        inbox = await mail.inbox(store, InboxQuery(folder=command["folder"]))
        if not inbox["messages"]:
            return "Gmail проверен: непрочитанных писем во входящих нет." if command["folder"] == "unread" else "Gmail проверен: папка «Входящие» пуста."
        letter = await mail.open(store, inbox["messages"][0]["ticket"])
    text = letter["text"].strip()
    limit = 12000
    result = f"{LETTER_PREFIX}\nОт: {letter['sender']}\nТема: {letter['subject']}\nДата: {letter['date']}\n\n"
    result += text[:limit] or "В письме нет доступного текста. Откройте его в разделе «Почта», чтобы проверить вложения."
    if letter["truncated"] or len(text) > limit:
        result += "\n\nПисьмо показано частично. Полный доступный текст можно открыть в разделе «Почта»."
    if letter["attachments"]:
        result += f"\n\nВложений: {len(letter['attachments'])}. Их содержимое здесь не зачитывается."
    return result


def model_history(content):
    # The local chat retains what was read, but an ordinary later model call
    # must not silently upload private mail or treat it as assistant instructions.
    if content.startswith(LETTER_PREFIX):
        return "По просьбе пользователя было прочитано письмо Gmail. Текст письма не передаётся модели; для работы с выбранным письмом используется раздел «Почта»."
    return content
