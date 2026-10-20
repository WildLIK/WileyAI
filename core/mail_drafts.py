"""Local unsent correspondence. This module contains no transport or send action."""
from datetime import datetime, timedelta, timezone
from email.headerregistry import Address
from email.message import EmailMessage
from email import policy
import json
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .mail_files import Attachment, MAX_TOTAL, decode as attachment_bytes, add_to_message


def address(value):
    value = value.strip()
    if not value or len(value) > 254 or any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("Укажите адрес почты без имени и пробелов: name@example.com")
    try:
        local, domain = value.rsplit("@", 1)
        domain = domain.encode("idna").decode("ascii").lower()
        result = local + "@" + domain
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
            raise ValueError()
        if "." not in domain or len(domain) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split(".")):
            raise ValueError()
        if Address(addr_spec=result).addr_spec != result:
            raise ValueError()
        return result
    except (ValueError, UnicodeError) as error:
        raise ValueError("Укажите корректный адрес почты без имени: name@example.com") from error


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_addresses: list[str] = Field(default_factory=list, max_length=20)
    cc_addresses: list[str] = Field(default_factory=list, max_length=20)
    bcc_addresses: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=100000)
    attachments: list[Attachment] = Field(default_factory=list,max_length=10)

    @field_validator("to_addresses", "cc_addresses", "bcc_addresses")
    @classmethod
    def addresses(cls, values):
        result = [address(value) for value in values]
        if len({value.casefold() for value in result}) != len(result):
            raise ValueError("Один адрес повторяется в списке получателей")
        return result

    @field_validator("subject")
    @classmethod
    def header(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Тема письма должна быть одной строкой")
        return value.strip()

    @field_validator("body")
    @classmethod
    def content(cls, value):
        if "\0" in value:
            raise ValueError("Текст письма содержит нулевой символ")
        return value.replace("\r\n", "\n").replace("\r", "\n")

    @model_validator(mode="after")
    def all_addresses(self):
        if sum(len(attachment_bytes(item.data)) for item in self.attachments)>MAX_TOTAL:
            raise ValueError("Общий размер вложений не должен превышать 10 МБ")
        recipients = self.to_addresses + self.cc_addresses + self.bcc_addresses
        if len({value.casefold() for value in recipients}) != len(recipients):
            raise ValueError("Адрес повторяется в разных полях получателей")
        return self


class DraftSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_account: str | None = Field(default=None, max_length=254)
    source_message_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    in_reply_to: str | None = Field(default=None, max_length=998)

    @model_validator(mode="after")
    def source(self):
        if bool(self.source_account) != bool(self.source_message_id):
            raise ValueError("Неполная ссылка на исходное письмо")
        if self.source_account:
            self.source_account = address(self.source_account)
        if self.in_reply_to and (not self.source_account or not re.fullmatch(r"<[^<>\s\x00-\x1f\x7f]{1,900}@[^<>\s\x00-\x1f\x7f]{1,90}>", self.in_reply_to)):
            raise ValueError("Некорректный Message-ID исходного письма")
        return self


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS mail_deliveries (
        id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, draft_id TEXT NOT NULL,
        revision TEXT NOT NULL, account TEXT NOT NULL, state TEXT NOT NULL,
        google_id TEXT NOT NULL, rfc_id TEXT NOT NULL, created TEXT NOT NULL,
        UNIQUE(scope_id,draft_id,revision,account))""")
    db.execute("CREATE TABLE IF NOT EXISTS mail_drafts(id TEXT PRIMARY KEY,to_addresses TEXT NOT NULL,cc_addresses TEXT NOT NULL,bcc_addresses TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,source_account TEXT,source_message_id TEXT,in_reply_to TEXT,scope_id TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS mail_drafts_scope ON mail_drafts(scope_id,updated)")
    db.execute("CREATE TABLE IF NOT EXISTS mail_bindings(scope_id TEXT PRIMARY KEY,id TEXT NOT NULL,account TEXT NOT NULL,epoch TEXT NOT NULL)")
    if "attachments" not in {row["name"] for row in db.execute("PRAGMA table_info(mail_drafts)")}:
        db.execute("ALTER TABLE mail_drafts ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'")


def check_scope(db, store):
    chat = db.execute("SELECT project_id FROM conversations WHERE id=?", (store.conversation_id,)).fetchone()
    if chat is None or (chat[0] or "") != store.scope_id:
        raise ValueError("Чат удалён или перемещён. Выберите его заново")


def decode(row):
    result = dict(row)
    for name in ("to_addresses", "cc_addresses", "bcc_addresses", "attachments"):
        if name not in result: continue
        result[name] = json.loads(result[name])
    return result


class Drafts:
    def __init__(self, store):
        self.store = store

    def list(self):
        with self.store.db() as db:
            check_scope(db, self.store)
            rows = db.execute("SELECT id,to_addresses,cc_addresses,bcc_addresses,subject,source_account,source_message_id,in_reply_to,scope_id,created,updated,substr(body,1,160) AS preview FROM mail_drafts WHERE scope_id=? ORDER BY updated DESC,id LIMIT 200", (self.store.scope_id,)).fetchall()
        return [decode(row) for row in rows]

    def get(self, item_id):
        with self.store.db() as db:
            check_scope(db, self.store)
            item = db.execute("SELECT * FROM mail_drafts WHERE id=? AND scope_id=?", (item_id, self.store.scope_id)).fetchone()
        if not item:
            raise ValueError("Черновик не найден в этом пространстве")
        return decode(item)

    def save(self, body, item_id=None, expected_updated=None, source=None):
        stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        item = {**body.model_dump(), **(source or DraftSource()).model_dump(), "id": item_id or uuid.uuid4().hex, "scope_id": self.store.scope_id, "created": stamp, "updated": stamp}
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db, self.store)
            if item_id:
                old = db.execute("SELECT * FROM mail_drafts WHERE id=? AND scope_id=?", (item_id,self.store.scope_id)).fetchone()
                if not old or not expected_updated or old["updated"] != expected_updated:
                    raise ValueError("Черновик удалён или изменён в другом окне. Откройте его заново")
                item.update({key:old[key] for key in DraftSource.model_fields})
                item["created"] = old["created"]
                item["updated"] = max(datetime.fromisoformat(stamp),datetime.fromisoformat(old["updated"]) + timedelta(microseconds=1)).isoformat(timespec="microseconds")
            elif db.execute("SELECT COUNT(*) FROM mail_drafts WHERE scope_id=?", (self.store.scope_id,)).fetchone()[0] >= 200:
                raise ValueError("В пространстве уже 200 черновиков. Удалите ненужные")
            sql_item = {key:json.dumps(value,ensure_ascii=False) if isinstance(value,list) else value for key,value in item.items()}
            if item_id:
                columns = [key for key in item if key not in {"id","scope_id","created"}]
                db.execute("UPDATE mail_drafts SET " + ",".join(f"{key}=:{key}" for key in columns) + " WHERE id=:id",sql_item)
            else:
                db.execute(f"INSERT INTO mail_drafts ({','.join(item)}) VALUES ({','.join(':'+key for key in item)})",sql_item)
        return item

    def remove(self,item_id,expected_updated):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db,self.store)
            if not expected_updated or not db.execute("DELETE FROM mail_drafts WHERE id=? AND scope_id=? AND updated=?",(item_id,self.store.scope_id,expected_updated)).rowcount:
                raise ValueError("Черновик удалён или изменён в другом окне. Откройте его заново")

    def eml(self,item_id,expected_updated,*,require_recipient=True):
        item = self.get(item_id)
        if item["updated"] != expected_updated:
            raise ValueError("Черновик изменился. Откройте его заново перед сохранением файла")
        if require_recipient and not (item["to_addresses"] or item["cc_addresses"] or item["bcc_addresses"]):
            raise ValueError("Укажите хотя бы одного получателя перед сохранением EML")
        mail = EmailMessage(policy=policy.SMTP)
        for field,key in (("To","to_addresses"),("Cc","cc_addresses"),("Bcc","bcc_addresses")):
            if item[key]: mail[field] = ", ".join(item[key])
        mail["Subject"] = item["subject"]
        mail["X-Unsent"] = "1"
        if item["source_account"]: mail["From"] = item["source_account"]
        if item["in_reply_to"]:
            mail["In-Reply-To"] = item["in_reply_to"]
            mail["References"] = item["in_reply_to"]
        mail.set_content(item["body"],charset="utf-8")
        add_to_message(mail,item["attachments"])
        return mail.as_bytes()
