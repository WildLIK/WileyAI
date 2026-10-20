"""Project-scoped address book; never inferred from private messages."""
from datetime import datetime, timezone, timedelta
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .mail_drafts import address, check_scope


class ContactBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str=Field(min_length=1,max_length=160)
    email:str=Field(default="",max_length=254)
    phone:str=Field(default="",max_length=50)
    telegram:str=Field(default="",max_length=100)
    notes:str=Field(default="",max_length=2000)

    @field_validator("name","phone","telegram")
    @classmethod
    def clean(cls,value):
        if any(ord(char)<32 for char in value) or not value.strip() and value:
            raise ValueError("Некорректное поле контакта")
        return value.strip()

    @field_validator("email")
    @classmethod
    def email_value(cls,value): return address(value) if value else ""


def migrate(db):
    db.execute("CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY,scope_id TEXT NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,telegram TEXT NOT NULL,notes TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL)")


class Contacts:
    def __init__(self,store): self.store=store

    def list(self,query=""):
        if len(query)>200: raise ValueError("Поисковый запрос слишком длинный")
        with self.store.db() as db:
            check_scope(db,self.store)
            values=[dict(row) for row in db.execute("SELECT * FROM contacts WHERE scope_id=? ORDER BY name,id LIMIT 501",(self.store.scope_id,))]
        return [row for row in values if query.casefold() in " ".join(row[key] for key in ("name","email","phone","telegram")).casefold()]

    def save(self,body,item_id=None,expected=None):
        stamp=datetime.now(timezone.utc).isoformat(timespec="microseconds")
        row={**body.model_dump(),"id":item_id or uuid.uuid4().hex,"scope_id":self.store.scope_id,"created":stamp,"updated":stamp}
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            check_scope(db,self.store)
            if item_id:
                old=db.execute("SELECT * FROM contacts WHERE id=? AND scope_id=?",(item_id,self.store.scope_id)).fetchone()
                if not old or old["updated"]!=expected: raise ValueError("Контакт изменился или удалён. Откройте его заново")
                row["created"]=old["created"]
                row["updated"]=max(datetime.fromisoformat(stamp),datetime.fromisoformat(old["updated"])+timedelta(microseconds=1)).isoformat(timespec="microseconds")
                db.execute("DELETE FROM contacts WHERE id=?",(item_id,))
            elif db.execute("SELECT COUNT(*) FROM contacts WHERE scope_id=?",(self.store.scope_id,)).fetchone()[0]>=500:
                raise ValueError("До 500 контактов на пространство")
            db.execute("INSERT INTO contacts(id,scope_id,name,email,phone,telegram,notes,created,updated) VALUES (:id,:scope_id,:name,:email,:phone,:telegram,:notes,:created,:updated)",row)
        return row

    def remove(self,item_id,expected):
        with self.store.db() as db:
            check_scope(db,self.store)
            if not db.execute("DELETE FROM contacts WHERE id=? AND scope_id=? AND updated=?",(item_id,self.store.scope_id,expected)).rowcount:
                raise ValueError("Контакт изменился или удалён")
