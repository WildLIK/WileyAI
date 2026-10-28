"""Explicit, version-reviewed Gmail drafts with uncertain-create reconciliation."""
import base64
from email import policy
from email.parser import BytesParser
import hashlib
import json
import re
import secrets
from urllib.parse import quote

from .mail_drafts import Drafts, check_scope
from .google_calendar_auth import GoogleError

COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def mime_hash(raw):
    message=BytesParser(policy=policy.default).parsebytes(raw)
    values={name:[str(value) for value in message.get_all(name,[])] for name in ("From","To","Cc","Bcc","Subject","In-Reply-To","References")}
    parts=list(message.walk())
    if len(parts)>200: raise ValueError("Слишком сложный черновик Gmail")
    values["parts"]=[]
    for part in parts:
        if part.is_multipart(): continue
        data=part.get_payload(decode=True) or b""
        if part.get_content_maintype()=="text" and not part.get_filename(): data=data.replace(b"\r\n",b"\n")
        values["parts"].append((part.get_content_type(),part.get_filename(),hashlib.sha256(data).hexdigest()))
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class RemoteDrafts:
    def __init__(self,mail):
        self.mail=mail
        with mail.store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS mail_remote_drafts(scope_id TEXT NOT NULL,local_id TEXT NOT NULL,account TEXT NOT NULL,remote_id TEXT NOT NULL,remote_hash TEXT NOT NULL,rfc_id TEXT NOT NULL,state TEXT NOT NULL,previous_hash TEXT NOT NULL DEFAULT '',PRIMARY KEY(scope_id,local_id,account))")
            # Remote hash before an uncertain update, so a PUT that never reached Gmail can be recognised.
            if "previous_hash" not in {row["name"] for row in db.execute("PRAGMA table_info(mail_remote_drafts)")}: db.execute("ALTER TABLE mail_remote_drafts ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''")

    def require(self):
        if COMPOSE not in self.mail.auth.read().get("granted_scopes",[]):
            raise ValueError("Отдельно разрешите работу с черновиками Gmail через Google")

    async def call(self,method,path,*,expected_epoch=None,**kwargs):
        self.require()
        token,epoch=await self.mail.auth.access()
        self.require()
        if expected_epoch is not None and epoch!=expected_epoch: raise GoogleError(401)
        result=await self.mail.auth.request(method,BASE+path,headers={"Authorization":"Bearer "+token},max_bytes=20*1024*1024,**kwargs)
        if self.mail.auth.read().get("epoch")!=epoch: raise ValueError("Вход Google изменился. Обновите черновик")
        return result

    def link(self,store,local_id):
        binding=self.mail.bound(store)
        Drafts(store).get(local_id)
        with store.db() as db:
            row=db.execute("SELECT * FROM mail_remote_drafts WHERE scope_id=? AND local_id=? AND account=?",(store.scope_id,local_id,binding["account"])).fetchone()
        return dict(row) if row else None

    async def read(self,remote_id,*,expected_epoch=None):
        if not isinstance(remote_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}",remote_id): raise ValueError("Некорректный ID черновика Gmail")
        value=await self.call("GET","/drafts/"+quote(remote_id,safe=""),params={"format":"raw"},expected_epoch=expected_epoch)
        encoded=value.get("message",{}).get("raw","")
        if value.get("id")!=remote_id or not isinstance(encoded,str) or len(encoded)>20*1024*1024: raise ValueError("Некорректный черновик Gmail")
        try: raw=base64.b64decode(encoded+"="*((-len(encoded))%4),altchars=b"-_",validate=True)
        except ValueError as error: raise ValueError("Повреждённый черновик Gmail") from error
        return value,raw

    async def preview(self,store,local_id,revision):
        self.require()
        binding=self.mail.bound(store)
        draft=Drafts(store).get(local_id)
        if draft["source_account"] and draft["source_account"].casefold()!=binding["account"].casefold(): raise ValueError("Исходное письмо принадлежит другому аккаунту")
        if draft["updated"]!=revision: raise ValueError("Черновик изменился. Сохраните его и повторите просмотр")
        delivery=self.mail.sender.delivery(store,local_id)
        if delivery and delivery["state"] in {"sending","unknown"}: raise ValueError("Сначала проверьте результат отправки этого письма")
        link=self.link(store,local_id)
        if link and link["state"]=="unknown": raise ValueError("Результат прошлого сохранения неизвестен. Сначала проверьте черновик Gmail")
        if link and link["state"]=="sent": link=None
        remote_hash,remote_text="",""
        if link:
            _,raw=await self.read(link["remote_id"],expected_epoch=binding["epoch"])
            remote_hash=mime_hash(raw)
            parsed=BytesParser(policy=policy.default).parsebytes(raw)
            remote_text="\n".join(str(parsed.get(key,"")) for key in ("To","Cc","Bcc","Subject"))
            for part in parsed.walk():
                if part.get_content_type()=="text/plain" and not part.get_filename():
                    data=(part.get_payload(decode=True) or b"")[:400000]
                    try: text=data.decode(part.get_content_charset() or "utf-8",errors="replace")
                    except LookupError: text=data.decode("utf-8",errors="replace")
                    remote_text+="\n"+text[:max(0,100000-len(remote_text))]
        raw=Drafts(store).eml(local_id,revision,require_recipient=False)
        message=BytesParser(policy=policy.SMTP).parsebytes(raw)
        del message["X-Unsent"]
        if message["From"]: del message["From"]
        message["From"]=binding["account"]
        rfc_id="<"+secrets.token_hex(24)+"@wileyai.local>"
        message["Message-ID"]=rfc_id
        raw=message.as_bytes()
        payload={"raw":base64.urlsafe_b64encode(raw).decode()}
        if draft["source_message_id"]:
            source=await self.mail.read("/messages/"+draft["source_message_id"],format="metadata",metadataHeaders=["Message-ID"])
            thread=source.get("threadId")
            if source.get("id")!=draft["source_message_id"] or not isinstance(thread,str) or not re.fullmatch(r"[a-fA-F0-9]{1,128}",thread): raise ValueError("Не удалось проверить цепочку исходного письма")
            payload["threadId"]=thread
        self.mail.check_binding(store,binding)
        ticket=self.mail.ticket(store,binding,"remote-draft",local_id=local_id,revision=revision,remote_id=link["remote_id"] if link else "",remote_hash=remote_hash,payload=payload,expected_hash=mime_hash(raw),rfc_id=rfc_id)
        from .mail_files import Attachment
        return {"ticket":ticket,"account":binding["account"],"remote_changed":bool(link and remote_hash!=link["remote_hash"]),"remote_text":remote_text,"attachments":[Attachment.model_validate(value).summary() for value in draft["attachments"]],**{key:draft[key] for key in ("to_addresses","cc_addresses","bcc_addresses","subject","body")}}

    async def save(self,store,ticket,confirmed):
        if not confirmed: raise ValueError("Подтвердите сохранение показанной версии в Gmail")
        item,binding=self.mail.lookup(store,ticket,"remote-draft")
        if Drafts(store).get(item["local_id"])["updated"]!=item["revision"]: raise ValueError("Локальный черновик изменился")
        if item["remote_id"]:
            _,raw=await self.read(item["remote_id"],expected_epoch=binding["epoch"])
            if mime_hash(raw)!=item["remote_hash"]: raise ValueError("Черновик Gmail изменился после просмотра. Сравните версии заново")
        current=self.link(store,item["local_id"])
        if current and current["state"]=="unknown": raise ValueError("Предыдущее сохранение ещё не подтверждено")
        if current and current["state"]=="ready" and current["remote_id"]!=item["remote_id"]:
            raise ValueError("Другой предпросмотр уже создал черновик Gmail. Обновите версию")
        self.mail.check_binding(store,binding)
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db,store)
            row=db.execute("SELECT updated FROM mail_drafts WHERE id=? AND scope_id=?",(item["local_id"],store.scope_id)).fetchone()
            if not row or row[0]!=item["revision"]: raise ValueError("Локальный черновик изменился")
            db.execute("INSERT OR REPLACE INTO mail_remote_drafts (scope_id,local_id,account,remote_id,remote_hash,rfc_id,state,previous_hash) VALUES (?,?,?,?,?,?,?,?)",(store.scope_id,item["local_id"],binding["account"],item["remote_id"],item["expected_hash"],item["rfc_id"],"unknown",item["remote_hash"]))
        self.mail.tickets.pop(ticket,None)
        written=False
        try:
            path="/drafts"+("/"+item["remote_id"] if item["remote_id"] else "")
            result=await self.call("PUT" if item["remote_id"] else "POST",path,json={"message":item["payload"]},expected_epoch=binding["epoch"])
            written=True
            remote_id=result.get("id","")
            _,raw=await self.read(remote_id,expected_epoch=binding["epoch"])
            if mime_hash(raw)!=item["expected_hash"]: raise ValueError("Gmail не подтвердил содержимое черновика")
        except GoogleError as error:
            if not written and error.status in {400,401,403,404,405,413,415,422,429}:
                with store.db() as db:
                    db.execute("DELETE FROM mail_remote_drafts WHERE scope_id=? AND local_id=? AND account=?",(store.scope_id,item["local_id"],binding["account"]))
                    if current: db.execute("INSERT INTO mail_remote_drafts (scope_id,local_id,account,remote_id,remote_hash,rfc_id,state) VALUES (?,?,?,?,?,?,?)",tuple(current[key] for key in ("scope_id","local_id","account","remote_id","remote_hash","rfc_id","state")))
                raise ValueError("Gmail отклонил сохранение. Проверьте доступ и повторите предпросмотр") from error
            return {"state":"unknown","message":"Результат сохранения неизвестен. Проверьте черновик; автоматического повтора нет"}
        except ValueError:
            return {"state":"unknown","message":"Результат сохранения неизвестен. Проверьте черновик; автоматического повтора нет"}
        with store.db() as db:
            db.execute("UPDATE mail_remote_drafts SET remote_id=?,state='ready' WHERE scope_id=? AND local_id=? AND account=?",(remote_id,store.scope_id,item["local_id"],binding["account"]))
        return self.link(store,item["local_id"])

    async def check(self,store,local_id):
        binding=self.mail.bound(store)
        link=self.link(store,local_id)
        if not link: return None
        key=(store.scope_id,local_id,link["account"])
        def settle(remote_id,remote_hash):
            with store.db() as db:
                db.execute("UPDATE mail_remote_drafts SET remote_id=?,remote_hash=?,state='ready',previous_hash='' WHERE scope_id=? AND local_id=? AND account=?",(remote_id,remote_hash,*key))
        if link["remote_id"]:
            try: _,raw=await self.read(link["remote_id"],expected_epoch=binding["epoch"])
            except GoogleError as error:
                if error.status!=404 or link["state"]!="unknown": raise
                # The Gmail draft is gone, so the uncertain update cannot have landed; allow a fresh save.
                with store.db() as db: db.execute("DELETE FROM mail_remote_drafts WHERE scope_id=? AND local_id=? AND account=?",key)
                return None
            value=mime_hash(raw)
            if value==link["remote_hash"]: settle(link["remote_id"],value)
            elif link["state"]=="unknown" and link["previous_hash"] and value==link["previous_hash"]:
                # The update never reached Gmail: restore the previous link so the user can retry.
                settle(link["remote_id"],value)
            elif link["state"]=="unknown":
                # Changed by someone else; keep the expected hash so the next preview reports the remote change.
                settle(link["remote_id"],link["remote_hash"])
            return self.link(store,local_id)
        result=await self.call("GET","/drafts",params={"q":"rfc822msgid:"+link["rfc_id"],"maxResults":20},expected_epoch=binding["epoch"])
        rows=result.get("drafts",[])
        if not isinstance(rows,list) or len(rows)>20 or result.get("nextPageToken"): raise ValueError("Неполный список черновиков Gmail. Повторите проверку позже")
        own=None
        for remote_id in [row.get("id","") for row in rows if isinstance(row,dict)]:
            _,raw=await self.read(remote_id,expected_epoch=binding["epoch"])
            if mime_hash(raw)==link["remote_hash"]:
                settle(remote_id,link["remote_hash"])
                return self.link(store,local_id)
            if own is None and str(BytesParser(policy=policy.default).parsebytes(raw).get("Message-ID","")).strip()==link["rfc_id"]: own=remote_id
        if link["state"]=="unknown":
            if own:
                # Our draft exists but was edited in Gmail; link it and let the next preview show the difference.
                settle(own,link["remote_hash"])
            else:
                # The create never reached Gmail: forget the uncertain row so the user can save again.
                with store.db() as db: db.execute("DELETE FROM mail_remote_drafts WHERE scope_id=? AND local_id=? AND account=?",key)
        return self.link(store,local_id)
