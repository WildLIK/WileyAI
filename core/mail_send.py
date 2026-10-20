"""Reviewed Gmail sends. No chat/model entry point and no automatic retries."""
import base64
import asyncio
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import format_datetime
import re
import secrets

from pydantic import BaseModel, ConfigDict, Field

from .google_calendar_auth import GoogleError
from .mail_drafts import Drafts, address, check_scope

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated: str = Field(min_length=1, max_length=100)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=1, max_length=100)
    confirmed: bool = Field(strict=True)


class Sender:
    def __init__(self, mail):
        self.mail = mail

    def require_access(self):
        if not {SEND_SCOPE,"https://www.googleapis.com/auth/gmail.compose"} & set(self.mail.auth.read().get("granted_scopes", [])):
            raise ValueError("Для отправки отдельно разрешите Gmail отправлять письма. Чтение остаётся доступным")

    def delivery(self, store, draft_id):
        draft = Drafts(store).get(draft_id)
        binding = self.mail.bound(store)
        with store.db() as db:
            row = db.execute("SELECT * FROM mail_deliveries WHERE scope_id=? AND draft_id=? AND revision=? AND account=?", (store.scope_id, draft_id, draft["updated"], binding["account"])).fetchone()
        if not row:
            return None
        result = dict(row)
        if result["state"] == "sending":
            result["state"] = "unknown"  # Interrupted process; never resend blindly.
        return result

    def attempt(self, store, ticket):
        with store.db() as db:
            check_scope(db, store)
            row = db.execute("SELECT * FROM mail_deliveries WHERE id=? AND scope_id=?", (ticket, store.scope_id)).fetchone()
        return dict(row) if row else None

    async def preview(self, store, draft_id, expected_updated):
        self.require_access()
        binding = self.mail.bound(store)
        draft = Drafts(store).get(draft_id)
        if draft["updated"] != expected_updated:
            raise ValueError("Черновик изменился. Сохраните и откройте предпросмотр заново")
        existing = self.delivery(store, draft_id)
        if existing and existing["state"] != "failed":
            raise ValueError("Эта версия письма уже отправлялась. Проверьте результат отправки; повторная отправка заблокирована")
        profile = await self.mail.read("/profile")
        sender = address(profile.get("emailAddress", ""))
        if sender.casefold() != binding["account"].casefold():
            raise ValueError("Аккаунт отправителя изменился. Выберите Gmail заново")
        if draft["source_account"] and draft["source_account"].casefold() != sender.casefold():
            raise ValueError("Исходное письмо принадлежит другому аккаунту")
        message = BytesParser(policy=policy.SMTP).parsebytes(Drafts(store).eml(draft_id, expected_updated))
        del message["X-Unsent"]
        if message["From"]:
            del message["From"]
        message["From"] = sender
        message["Date"] = format_datetime(datetime.now(timezone.utc))
        rfc_id = "<" + secrets.token_hex(24) + "@wileyai.local>"
        message["Message-ID"] = rfc_id
        payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if draft["source_message_id"]:
            source = await self.mail.read("/messages/" + draft["source_message_id"], format="metadata", metadataHeaders=["Message-ID"])
            thread = source.get("threadId")
            if source.get("id") != draft["source_message_id"] or not isinstance(thread, str) or not re.fullmatch(r"[a-fA-F0-9]{1,128}", thread):
                raise ValueError("Не удалось проверить цепочку исходного письма")
            payload["threadId"] = thread
        remote_id,remote_hash="",""
        link=self.mail.remote_drafts.link(store,draft_id)
        if link and link["state"]=="unknown": raise ValueError("Сначала проверьте сохранение черновика Gmail")
        if link and link["state"]=="ready":
            from .mail_remote import mime_hash
            _,raw=await self.mail.remote_drafts.read(link["remote_id"],expected_epoch=binding["epoch"])
            if mime_hash(raw)!=mime_hash(message.as_bytes()): raise ValueError("Локальная версия и Gmail различаются. Сначала сравните и сохраните черновик в Gmail")
            parsed=BytesParser(policy=policy.default).parsebytes(raw)
            remote_rfc=str(parsed.get("Message-ID",""))
            if not re.fullmatch(r"<[^<>\s]{1,200}>",remote_rfc): raise ValueError("Сохраните черновик Gmail заново для подтверждения отправки")
            rfc_id,remote_id,remote_hash=remote_rfc,link["remote_id"],mime_hash(raw)
            payload={"id":remote_id}
        self.mail.check_binding(store, binding)
        if Drafts(store).get(draft_id)["updated"] != expected_updated:
            raise ValueError("Черновик изменился. Откройте предпросмотр заново")
        ticket = self.mail.ticket(store, binding, "send", draft_id=draft_id, revision=expected_updated, payload=payload, rfc_id=rfc_id,remote_id=remote_id,remote_hash=remote_hash)
        from .mail_files import Attachment
        return {"ticket": ticket, "sender": sender, "attachments":[Attachment.model_validate(value).summary() for value in draft["attachments"]], **{key: draft[key] for key in ("to_addresses", "cc_addresses", "bcc_addresses", "subject", "body")}}

    def mark(self, store, ticket, state, google_id=""):
        with store.db() as db:
            db.execute("UPDATE mail_deliveries SET state=?,google_id=? WHERE id=? AND scope_id=?", (state, google_id, ticket, store.scope_id))
            if state=="sent":
                db.execute("UPDATE mail_remote_drafts SET state='sent' WHERE scope_id=? AND (local_id,account) IN (SELECT draft_id,account FROM mail_deliveries WHERE id=?)",(store.scope_id,ticket))

    @staticmethod
    def verified(message, rfc_id):
        headers = message.get("payload", {}).get("headers", [])
        ids = [row.get("value") for row in headers if row.get("name", "").casefold() == "message-id"]
        return "SENT" in message.get("labelIds", []) and ids == [rfc_id]

    async def confirm(self, store, body):
        if not body.confirmed:
            raise ValueError("Подтвердите отправку после проверки адресатов и текста")
        self.require_access()
        item, binding = self.mail.lookup(store, body.ticket, "send")
        token, epoch = await self.mail.auth.access()
        self.require_access()
        self.mail.check_binding(store, binding)
        if epoch != binding["epoch"]:
            raise ValueError("Вход Google изменился. Откройте предпросмотр заново")
        if item.get("remote_id"):
            from .mail_remote import mime_hash
            _,raw=await self.mail.remote_drafts.read(item["remote_id"],expected_epoch=binding["epoch"])
            parsed=BytesParser(policy=policy.default).parsebytes(raw)
            if mime_hash(raw)!=item["remote_hash"] or str(parsed.get("Message-ID",""))!=item["rfc_id"]:
                raise ValueError("Черновик Gmail изменился после просмотра. Проверьте письмо заново")
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db, store)
            draft = db.execute("SELECT updated FROM mail_drafts WHERE id=? AND scope_id=?", (item["draft_id"], store.scope_id)).fetchone()
            if not draft or draft[0] != item["revision"]:
                raise ValueError("Черновик изменился. Откройте предпросмотр заново")
            previous = db.execute("SELECT id,state FROM mail_deliveries WHERE scope_id=? AND draft_id=? AND revision=? AND account=?", (store.scope_id, item["draft_id"], item["revision"], binding["account"])).fetchone()
            if previous:
                if previous[1] != "failed":
                    raise ValueError("Эта версия уже отправлялась. Повторная отправка заблокирована")
                db.execute("DELETE FROM mail_deliveries WHERE id=?", (previous[0],))
            db.execute("INSERT INTO mail_deliveries VALUES (?,?,?,?,?,?,?,?,?)", (body.ticket, store.scope_id, item["draft_id"], item["revision"], binding["account"], "sending", "", item["rfc_id"], datetime.now(timezone.utc).isoformat()))
        self.mail.tickets.pop(body.ticket, None)
        google_id = ""
        try:
            result = await self.mail.auth.request("POST", GMAIL + ("/drafts/send" if item.get("remote_id") else "/messages/send"), headers={"Authorization": "Bearer " + token}, json=item["payload"])
            google_id = result.get("id", "")
            if not isinstance(google_id, str) or not re.fullmatch(r"[a-fA-F0-9]{1,128}", google_id):
                google_id = ""
                raise ValueError("Нет идентификатора отправленного письма")
            message = await self.mail.read("/messages/" + google_id, format="metadata", metadataHeaders=["Message-ID"])
            if message.get("id") != google_id or not self.verified(message, item["rfc_id"]):
                raise ValueError("Нет подтверждения в отправленных")
        except GoogleError as error:
            self.mark(store, body.ticket, "failed" if not google_id and error.status in {400,401,403,404,405,413,415,422,429} else "unknown", google_id)
        except (Exception, asyncio.CancelledError) as error:
            self.mark(store, body.ticket, "unknown", google_id)
            # Cancellation is not evidence that Google's send was cancelled.
            if isinstance(error, asyncio.CancelledError):
                raise
        else:
            self.mark(store, body.ticket, "sent", google_id)
        return self.attempt(store, body.ticket)

    async def check(self, store, draft_id):
        receipt = self.delivery(store, draft_id)
        if not receipt:
            raise ValueError("Нет сохранённой попытки отправки этой версии письма")
        binding = self.mail.bound(store)
        if receipt["state"] == "sent":
            return receipt
        ids = [receipt["google_id"]] if receipt["google_id"] else []
        if not ids:
            result = await self.mail.read("/messages", q="in:sent rfc822msgid:" + receipt["rfc_id"], maxResults=10)
            rows = result.get("messages", [])
            if not isinstance(rows, list) or len(rows) > 10:
                raise ValueError("Некорректный результат проверки отправленных")
            ids = [row.get("id", "") for row in rows if isinstance(row, dict)]
        for google_id in ids:
            if not isinstance(google_id, str) or not re.fullmatch(r"[a-fA-F0-9]{1,128}", google_id):
                raise ValueError("Некорректный идентификатор Gmail")
            message = await self.mail.read("/messages/" + google_id, format="metadata", metadataHeaders=["Message-ID"])
            if message.get("id") == google_id and self.verified(message, receipt["rfc_id"]):
                self.mail.check_binding(store, binding)
                self.mark(store, receipt["id"], "sent", google_id)
                break
        return self.delivery(store, draft_id)
