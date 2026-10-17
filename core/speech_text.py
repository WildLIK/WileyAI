"""Prepare conversational Markdown as plain speech, before model-specific chunking."""
import html
import re
import textwrap
import unicodedata


RU_LETTERS = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["а", "бэ", "вэ", "гэ", "дэ", "е", "ё", "жэ", "зэ", "и", "и краткое", "ка", "эл", "эм", "эн", "о", "пэ", "эр", "эс", "тэ", "у", "эф", "ха", "цэ", "че", "ша", "ща", "твёрдый знак", "ы", "мягкий знак", "э", "ю", "я"]))
EN_LETTERS = dict(zip("abcdefghijklmnopqrstuvwxyz", ["эй", "би", "си", "ди", "и", "эф", "джи", "эйч", "ай", "джей", "кей", "эл", "эм", "эн", "оу", "пи", "кью", "ар", "эс", "ти", "ю", "ви", "дабл ю", "экс", "уай", "зед"]))
EXTENSIONS = {"docx": "докс", "doc": "док", "txt": "тэ икс тэ", "pdf": "пэ дэ эф", "md": "эм дэ", "csv": "си эс ви", "xlsx": "икс эл эс икс", "xls": "икс эл эс", "pptx": "пэ пэ тэ икс", "json": "джейсон", "png": "пэ эн гэ", "jpg": "джей пег", "mp3": "эм пэ три"}


def spoken_filenames(text):
    def replace(match):
        name, extension = match.group(1), match.group(2).lower()
        parts = re.findall(r"[a-zа-яё]+|\d+", name, re.IGNORECASE)
        spoken = []
        for part in parts:
            if part.isdigit():
                spoken.append({"0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре", "5": "пять", "6": "шесть", "7": "семь", "8": "восемь", "9": "девять"}.get(part, part))
            elif len(part) <= 4 and (part.isupper() or not re.search(r"[аеёиоуыэюяaeiou]", part, re.IGNORECASE)):
                spoken.append(" ".join((RU_LETTERS | EN_LETTERS).get(char.lower(), char) for char in part))
            else:
                spoken.append(part)
        return " ".join(spoken) + " точка " + EXTENSIONS[extension]
    return re.sub(r"(?<![\w])([\w][\w.-]{0,160})\s*\.(" + "|".join(EXTENSIONS) + r")\b", replace, text, flags=re.IGNORECASE)


def plain_speech(text: str) -> str:
    text = unicodedata.normalize("NFC", html.unescape(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\ufeff]", "", text)
    # Keep code and link labels, without fences, destinations or styling commands.
    text = re.sub(r"(?m)^\s*(?:`{3,}|~{3,})[^\n]*$", "", text)
    text = re.sub(r"(?m)^\s*\[[^\]\n]+\]:\s+\S+[^\n]*$", "", text)
    text = re.sub(r"!?\[([^\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)", r"\1", text)
    text = re.sub(r"\[([^\]\n]+)\]\[[^\]\n]*\]", r"\1", text)
    text = re.sub(r"<(https?://[^<>\s]+)>", r"\1", text)
    text = re.sub(r"<!--[\s\S]*?-->|</?[A-Za-z][^<>]*>", " ", text)
    text = re.sub(r"(?<=\d)[ \t]*\*[ \t]*(?=\d)", " умножить на ", text)
    # Silero interprets even one asterisk as a pronunciation instruction.
    # Never let Markdown (including an unfinished streamed span) reach that parser.
    text = text.replace("*", "").replace("`", "").replace("~~", "")
    text = spoken_filenames(text)
    text = re.sub(r"(?<!\w)_{1,3}(?=\S)|(?<=\S)_{1,3}(?!\w)", "", text)
    lines = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*[|:\-\s]+\s*", line):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*>+\s*", "", line)
        line = re.sub(r"^\s*(?:[-+•]|\d{1,3}[.)])\s+", "", line)
        if line.count("|") >= 2:
            line = "; ".join(cell.strip() for cell in line.strip().strip("|").split("|") if cell.strip())
        line = re.sub(r"[^\S\n]+", " ", line).strip()
        if line:
            lines.append(line)
    result = "\n".join(lines)
    if not any(char.isalnum() for char in result):
        raise ValueError("В сообщении нет текста для озвучки")
    return result


def speech_chunks(text: str, limit: int = 240) -> list[str]:
    """Prefer complete sentences so neighbouring phrases retain their intonation."""
    chunks = []
    current = ""
    for sentence in re.split(r"(?<=[.!?…])\s+|\n+", text):
        for part in textwrap.wrap(sentence, width=limit, break_long_words=True, break_on_hyphens=False):
            if current and len(current) + len(part) + 1 > limit:
                chunks.append(current)
                current = ""
            current = f"{current} {part}".strip()
    if current:
        chunks.append(current)
    return chunks
