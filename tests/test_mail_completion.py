import base64
from email import policy
from email.parser import BytesParser
import json

import httpx
import pytest

from core.backups import Backups
from core.chatspaces import Spaces
from core.mail_drafts import Drafts,DraftBody
from core.mail_files import Attachment,MAX_FILE
from core.mail_remote import COMPOSE,mime_hash
from core.mail_send import ConfirmBody
from core.storage import Store
from test_mail_send import setup,vault,anyio_backend


class Remote:
    def __init__(self,fallback):
        self.fallback=fallback
        self.drafts={}
        self.writes=[]
        self.lose=False
        self.reject=False
        self.pages=False
        self.drop=False
    def handle(self,request):
        path=request.url.path
        if "/drafts" not in path: return self.fallback.handle(request)
        if path.endswith("/drafts/send"):
            self.writes.append(request)
            data=json.loads(request.content)
            raw=self.drafts.pop(data["id"])
            rfc=str(BytesParser(policy=policy.default).parsebytes(raw)["Message-ID"])
            self.fallback.messages["fed123"]={"id":"fed123","labelIds":["SENT"],"payload":{"headers":[{"name":"Message-ID","value":rfc}]}}
            return httpx.Response(200,json={"id":"fed123"})
        if request.method in {"POST","PUT"}:
            self.writes.append(request)
            if self.reject: return httpx.Response(403,json={"secret":"do-not-display"})
            if self.drop: raise httpx.ConnectTimeout("never arrived",request=request)
            item_id=path.rsplit("/",1)[-1] if request.method=="PUT" else "draft-1"
            data=json.loads(request.content)
            self.drafts[item_id]=base64.urlsafe_b64decode(data["message"]["raw"])
            if self.lose: raise httpx.ReadTimeout("uncertain",request=request)
            return httpx.Response(200,json={"id":item_id})
        if path.endswith("/drafts"):
            return httpx.Response(200,json={"drafts":[{"id":key} for key in self.drafts],**({"nextPageToken":"more"} if self.pages else {})})
        item_id=path.rsplit("/",1)[-1]
        if item_id not in self.drafts: return httpx.Response(404,json={})
        return httpx.Response(200,json={"id":item_id,"message":{"raw":base64.urlsafe_b64encode(self.drafts[item_id]).decode()}})


async def configured(tmp_path):
    store,fake,mail,draft=await setup(tmp_path)
    remote=Remote(fake)
    await mail.auth.client.aclose()
    mail.auth.client=httpx.AsyncClient(transport=httpx.MockTransport(remote.handle))
    mail.auth.write({**mail.auth.read(),"granted_scopes":[*mail.auth.read()["granted_scopes"],COMPOSE]})
    return store,remote,mail,draft


def attachment(raw=b"binary\r\nbytes",**changes):
    return {**dict(name="файл.bin",type="application/octet-stream",data=base64.b64encode(raw).decode()),**changes}


def test_attachment_exact_bytes_in_eml_and_backup(tmp_path):
    store=Store(tmp_path)
    item=Drafts(store).save(DraftBody(to_addresses=["reader@example.test"],attachments=[attachment()]))
    raw=Drafts(store).eml(item["id"],item["updated"])
    part=list(BytesParser(policy=policy.default).parsebytes(raw).iter_attachments())[0]
    assert part.get_payload(decode=True)==b"binary\r\nbytes" and part.get_filename()=="файл.bin"
    changed=Drafts(store).save(DraftBody(to_addresses=["reader@example.test"],attachments=[attachment(b"binary\nbytes")]),item["id"],item["updated"])
    # CRLF in a binary attachment must never be normalized during verification.
    assert mime_hash(raw)!=mime_hash(Drafts(store).eml(changed["id"],changed["updated"]))
    target=Store(tmp_path/"target")
    backup=Backups(target)
    backup.restore(backup.preview(Backups(store).export())["ticket"])
    assert Drafts(target).get(item["id"])["attachments"]==changed["attachments"]


@pytest.mark.parametrize("changes",[{"name":"../file"},{"name":"a\r\nBcc:x"},{"data":"%%%"},{"type":"text/plain\nfoo"}])
def test_invalid_attachments(changes):
    with pytest.raises(ValueError): Attachment.model_validate(attachment(**changes))


def test_attachment_size_limits():
    with pytest.raises(ValueError): Attachment.model_validate(attachment(b"x"*(MAX_FILE+1)))
    with pytest.raises(ValueError): DraftBody(attachments=[attachment(b"x"*MAX_FILE)]*3)


@pytest.mark.anyio
async def test_reviewed_remote_create_update_and_published_draft_send(tmp_path,vault):
    store,remote,mail,draft=await configured(tmp_path)
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert not remote.writes
    with pytest.raises(ValueError): await mail.remote_drafts.save(store,preview["ticket"],False)
    result=await mail.remote_drafts.save(store,preview["ticket"],True)
    assert result["state"]=="ready" and len(remote.drafts)==1
    preview=await mail.sender.preview(store,draft["id"],draft["updated"])
    assert len(remote.writes)==1
    receipt=await mail.sender.confirm(store,ConfirmBody(ticket=preview["ticket"],confirmed=True))
    assert receipt["state"]=="sent" and not remote.drafts
    assert remote.writes[-1].url.path.endswith("/drafts/send")
    assert mail.remote_drafts.link(store,draft["id"])["state"]=="sent"
    await mail.close()


@pytest.mark.anyio
async def test_remote_changed_after_review_and_two_create_previews(tmp_path,vault):
    store,remote,mail,draft=await configured(tmp_path)
    one=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    two=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    await mail.remote_drafts.save(store,one["ticket"],True)
    with pytest.raises(ValueError): await mail.remote_drafts.save(store,two["ticket"],True)
    third=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    remote.drafts["draft-1"]=remote.drafts["draft-1"].replace(b"Subject:",b"Subject: Changed ")
    with pytest.raises(ValueError,match="изменился после просмотра"): await mail.remote_drafts.save(store,third["ticket"],True)
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert preview["remote_changed"]
    await mail.remote_drafts.save(store,preview["ticket"],True)
    send=await mail.sender.preview(store,draft["id"],draft["updated"])
    remote.drafts["draft-1"]=remote.drafts["draft-1"].replace(b"Subject:",b"Subject: Changed ")
    with pytest.raises(ValueError): await mail.sender.confirm(store,ConfirmBody(ticket=send["ticket"],confirmed=True))
    assert len(remote.writes)==2
    await mail.close()


@pytest.mark.anyio
async def test_remote_lost_create_reconciles_without_resend_and_rejection_allows_retry(tmp_path,vault):
    store,remote,mail,draft=await configured(tmp_path)
    remote.reject=True
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    with pytest.raises(ValueError,match="отклонил"): await mail.remote_drafts.save(store,preview["ticket"],True)
    assert mail.remote_drafts.link(store,draft["id"]) is None
    remote.reject=False
    remote.lose=True
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert (await mail.remote_drafts.save(store,preview["ticket"],True))["state"]=="unknown"
    with pytest.raises(ValueError): await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    remote.pages=True
    with pytest.raises(ValueError,match="Неполный"): await mail.remote_drafts.check(store,draft["id"])
    remote.pages=False
    assert (await mail.remote_drafts.check(store,draft["id"]))["state"]=="ready"
    assert len(remote.writes)==2
    await mail.close()


@pytest.mark.anyio
async def test_remote_save_that_never_reached_gmail_can_be_retried(tmp_path,vault):
    store,remote,mail,draft=await configured(tmp_path)
    remote.drop=True
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert (await mail.remote_drafts.save(store,preview["ticket"],True))["state"]=="unknown"
    # Nothing was created in Gmail: the uncertain row is dropped instead of blocking forever.
    assert await mail.remote_drafts.check(store,draft["id"]) is None
    remote.drop=False
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    created=await mail.remote_drafts.save(store,preview["ticket"],True)
    assert created["state"]=="ready" and len(remote.drafts)==1
    # An update that never reached Gmail restores the previous link.
    remote.drop=True
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert (await mail.remote_drafts.save(store,preview["ticket"],True))["state"]=="unknown"
    restored=await mail.remote_drafts.check(store,draft["id"])
    assert restored["state"]=="ready" and restored["remote_id"]==created["remote_id"] and restored["remote_hash"]==created["remote_hash"]
    remote.drop=False
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert not preview["remote_changed"]
    assert (await mail.remote_drafts.save(store,preview["ticket"],True))["state"]=="ready"
    await mail.close()


@pytest.mark.anyio
async def test_attachment_ticket_scope_and_remote_permission_gate(tmp_path,vault):
    store,remote,mail,draft=await configured(tmp_path)
    binding=mail.bound(store)
    key=mail.ticket(store,binding,"attachment",message_id="abc123",body={"data":base64.urlsafe_b64encode(b"file").decode()},name="file.txt",mime="text/plain")
    assert await mail.attachment(store,key)==(b"file","file.txt")
    space=Spaces(store)
    project=space.create_project("Other")
    chat=space.create_chat(project["id"])
    with pytest.raises(ValueError): await mail.attachment(store.for_chat(chat["id"]),key)
    mail.auth.write({**mail.auth.read(),"granted_scopes":[]})
    with pytest.raises(ValueError,match="Отдельно"): await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    assert not remote.writes
    await mail.close()


@pytest.mark.anyio
async def test_oauth_account_changed_during_token_access_never_writes_to_new_account(tmp_path,vault,monkeypatch):
    store,remote,mail,draft=await configured(tmp_path)
    preview=await mail.remote_drafts.preview(store,draft["id"],draft["updated"])
    original=mail.auth.access
    async def changed_account():
        token,_=await original()
        mail.auth.write({**mail.auth.read(),"epoch":"different-account"})
        return token,"different-account"
    monkeypatch.setattr(mail.auth,"access",changed_account)
    with pytest.raises(ValueError,match="отклонил"): await mail.remote_drafts.save(store,preview["ticket"],True)
    assert not remote.writes and not remote.drafts
    with store.db() as db: assert not db.execute("SELECT * FROM mail_remote_drafts").fetchall()
    await mail.close()
