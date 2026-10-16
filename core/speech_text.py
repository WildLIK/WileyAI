"""Prepare conversational Markdown as plain speech, before model-specific chunking."""
import html
import re
import textwrap
import unicodedata


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
