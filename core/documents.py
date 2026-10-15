from io import BytesIO
import re


def extract(name: str, data: bytes) -> str:
    suffix = name.casefold().rsplit(".", 1)[-1]
    if suffix in {"txt", "md", "csv"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1251")
    elif suffix == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > 300:
            raise ValueError("В первой версии поддерживается до 300 страниц PDF")
        text = "\n\n".join(f"[Страница {i + 1}]\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages))
    elif suffix == "docx":
        from docx import Document
        document = Document(BytesIO(data))
        text = "\n".join([p.text for p in document.paragraphs] + [" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows])
    else:
        raise ValueError("Поддерживаются TXT, MD, CSV, PDF с текстом и DOCX")
    if not text.strip():
        raise ValueError("Текст не найден. OCR сканов ещё не подключён.")
    if len(text) > 1_000_000:
        raise ValueError("Документ превышает лимит первого прототипа: 1 миллион символов")
    return text


def context_for(question: str, documents: list[dict], budget: int = 6000) -> str:
    words = set(re.findall(r"[\w]{3,}", question.casefold()))
    ranked = []
    for document in documents:
        for offset in range(0, len(document["content"]), 1000):
            chunk = document["content"][offset:offset + 1200]
            score = len(words & set(re.findall(r"[\w]{3,}", chunk.casefold())))
            ranked.append((score, document["name"], offset, chunk))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    fragments = []
    for _, name, offset, chunk in ranked[:5]:
        fragment = f"Источник: {name}, фрагмент с символа {offset + 1}\n{chunk}"
        if sum(map(len, fragments)) + len(fragment) > budget:
            break
        fragments.append(fragment)
    return "\n\n".join(fragments)
