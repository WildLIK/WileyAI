"""Read Gmail MIME as inert plain text, never as a document with active content."""
import base64
import binascii
from email.message import Message
from email.utils import getaddresses
from html.parser import HTMLParser
import re

from .mail_drafts import address


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg", "iframe", "object", "noscript"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "blockquote"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg", "iframe", "object", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "tr", "blockquote"}:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.chunks.append(data)


def headers(payload):
    rows = payload.get("headers", [])
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Слишком много заголовков письма")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("value"), str) or len(row["name"]) > 100 or len(row["value"]) > 8192:
            raise ValueError("Некорректный заголовок письма")
        result.setdefault(row["name"].lower(), []).append(row["value"])
    return result


def single(values, name, default=""):
    entries = values.get(name, [])
    return entries[0] if len(entries) == 1 else default


def metadata(data):
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Некорректная структура письма")
    values = headers(payload)
    sender, reply = single(values,"from"), single(values,"reply-to")
    recipients = []
    raw = reply if "reply-to" in values else sender
    if raw and not any(char in raw for char in "\r\n\0"):
        try:
            parsed = getaddresses([raw])
            if len(parsed) == 1:
                recipients = [address(parsed[0][1])]
        except ValueError:
            pass
    message_id = single(values,"message-id")
    if not re.fullmatch(r"<[^<>\s\x00-\x1f\x7f]{1,900}@[^<>\s\x00-\x1f\x7f]{1,90}>", message_id):
        message_id = None
    labels = data.get("labelIds", [])
    if not isinstance(labels,list) or len(labels)>100:
        raise ValueError("Некорректные метки письма")
    return {"subject": single(values,"subject","Без темы")[:1000], "sender": sender, "reply_to": reply,
            "to": single(values,"to"), "date": single(values,"date"), "unread": "UNREAD" in labels,
            "snippet": str(data.get("snippet", ""))[:1000], "reply_addresses": recipients, "in_reply_to": message_id}


def content(data, attachment_details=False):
    count, decoded = 0, 0
    notes, attachments = [], []
    def walk(part, depth=0):
        nonlocal count, decoded
        count += 1
        if depth > 16 or count > 200 or not isinstance(part,dict):
            raise ValueError("Слишком сложная MIME-структура письма")
        mime = part.get("mimeType", "")
        if not isinstance(mime,str) or len(mime)>100: raise ValueError("Некорректный MIME-тип письма")
        mime = mime.lower()
        filename = part.get("filename", "")
        if not isinstance(filename,str) or len(filename)>1000:
            raise ValueError("Некорректное имя вложения")
        body = part.get("body", {})
        if not isinstance(body,dict): raise ValueError("Некорректное тело письма")
        values = headers(part)
        disposition = single(values,"content-disposition").lower()
        if filename or disposition.startswith("attachment"):
            attachments.append({"name":filename or "Вложение", "type":mime[:100], **({"_body":body} if attachment_details else {})})
            return "",False
        children = part.get("parts", [])
        if not isinstance(children,list) or len(children)>200: raise ValueError("Некорректные части письма")
        if children:
            if mime == "multipart/alternative":
                candidates = [child for child in children if isinstance(child,dict) and child.get("mimeType", "") == "text/plain"]
                if candidates:
                    piece = walk(candidates[0],depth+1)
                    if piece[0].strip():
                        return piece
                    # A blank text/plain alternative falls back to the HTML (or other) part.
                    children = [child for child in children if child is not candidates[0]]
            pieces = [walk(child,depth+1) for child in children]
            if mime == "multipart/alternative":
                return next((piece for piece in reversed(pieces) if piece[0]),("",False))
            return "\n".join(piece[0] for piece in pieces if piece[0]),any(piece[1] for piece in pieces)
        if mime not in {"text/plain","text/html"}:
            return "",False
        if "attachmentId" in body and not body.get("data"):
            notes.append("Текст вынесен в отдельную часть и не загружен")
            return "",False
        encoded = body.get("data", "")
        if not isinstance(encoded,str) or len(encoded)>2*1024*1024:
            raise ValueError("Текстовая часть письма слишком велика")
        try:
            raw = base64.b64decode(encoded + "="*((-len(encoded))%4), altchars=b"-_", validate=True)
        except (ValueError,binascii.Error) as error:
            raise ValueError("Некорректное кодирование текста письма") from error
        decoded += len(raw)
        if decoded>1024*1024: raise ValueError("Извлечённый текст письма превышает 1 МБ")
        message = Message()
        message["Content-Type"] = single(values,"content-type",mime)
        charset = message.get_content_charset() or "utf-8"
        try:
            text = raw.decode(charset)
        except (LookupError,UnicodeError):
            text = raw.decode("utf-8",errors="replace")
            notes.append("Кодировка не распознана полностью; возможны замены символов")
        if mime == "text/html":
            parser = PlainHTML()
            parser.feed(text)
            text = "".join(parser.chunks)
        return text,mime == "text/html"
    text, was_html = walk(data.get("payload", {}))
    text = re.sub(r"\n{4,}","\n\n\n",text.replace("\r\n","\n").replace("\r","\n")).replace("\0","").strip()
    truncated = len(text)>100000
    if truncated: notes.append("Показаны первые 100 000 символов письма")
    return {"text":text[:100000],"from_html":was_html,"truncated":truncated,"notes":list(dict.fromkeys(notes)),"attachments":attachments}
