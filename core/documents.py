from io import BytesIO
import heapq
import re
from .memory import STOP_WORDS, normalized


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
        pages = [page.extract_text() or "" for page in reader.pages]
        if not any(page.strip() for page in pages):
            raise ValueError("Текст не найден. OCR сканов ещё не подключён.")
        text = "\n\n".join(f"[Страница {i + 1}]\n{page}" for i, page in enumerate(pages))
    elif suffix == "docx":
        from docx import Document
        from docx.oxml.ns import qn
        document = Document(BytesIO(data))
        def paragraphs(element):
            # Includes nested tables, hyperlinks and text boxes, in XML reading order.
            for paragraph in element.iter(qn("w:p")):
                words = []
                for node in paragraph.iter():
                    if node.tag in {qn("w:t"), qn("w:tab"), qn("w:br")} and next(node.iterancestors(qn("w:p")), None) is paragraph:
                        words.append(node.text or "" if node.tag == qn("w:t") else " ")
                if line := "".join(words).strip():
                    yield line
        parts = ["\n".join(paragraphs(document.element.body))]
        seen = set()
        for section in document.sections:
            for part in (section.header, section.first_page_header, section.even_page_header,
                         section.footer, section.first_page_footer, section.even_page_footer):
                if not part.is_linked_to_previous and part.part.partname not in seen:
                    seen.add(part.part.partname)
                    parts.append("\n".join(paragraphs(part._element)))
        text = "\n".join(part for part in parts if part)
    else:
        raise ValueError("Поддерживаются TXT, MD, CSV, PDF с текстом и DOCX")
    if not text.strip():
        raise ValueError("Текст не найден. OCR сканов ещё не подключён.")
    if len(text) > 1_000_000:
        raise ValueError("Документ превышает лимит первого прототипа: 1 миллион символов")
    return text


def context_for(question: str, documents: list[dict], budget: int = 6000) -> str:
    def terms(value):
        return {word[:6] if re.fullmatch(r"[а-я]+", word) else word for word in re.findall(r"[^\W_]{2,}", normalized(value)) if word not in STOP_WORDS}

    words = terms(question)
    primary, secondary = [], []
    for index, document in enumerate(documents[:10]):
        def chunks():
            for offset in range(0, len(document["content"]), 1000):
                chunk = document["content"][offset:offset + 1200]
                yield (len(words & terms(chunk)), -offset, offset, chunk)
        best = heapq.nlargest(2, chunks())
        for position, (score, _, offset, chunk) in enumerate(best):
            row = (score, -index, document["name"][:80], offset, chunk)
            if position == 0:
                primary.append(row)
            elif score and abs(offset - best[0][2]) >= 1200:
                secondary.append(row)
    primary.sort(key=lambda row: (row[0], row[1]), reverse=True)
    secondary.sort(key=lambda row: (row[0], row[1]), reverse=True)
    fragments, used = [], 0
    for index, (_, _, name, offset, chunk) in enumerate(primary + secondary):
        header = f"Источник: {name}, фрагмент с символа {offset + 1}\n"
        remaining = max(1, len(primary) - index)
        allowance = max(0, (budget - used) // remaining - len(header) - (2 if fragments else 0))
        if allowance < 30:
            continue
        shift = 0
        if len(chunk) > allowance and words:
            match = next((match for match in re.finditer(r"[^\W_]{2,}", chunk) if terms(match[0]) & words), None)
            if match:
                shift = max(0, min(len(chunk) - allowance, match.start() - allowance // 3))
                header = f"Источник: {name}, фрагмент с символа {offset + shift + 1}\n"
                allowance = max(0, (budget - used) // remaining - len(header) - (2 if fragments else 0))
        fragment = header + chunk[shift:shift + allowance]
        used += len(fragment) + (2 if fragments else 0)
        fragments.append(fragment)
    return "\n\n".join(fragments)
