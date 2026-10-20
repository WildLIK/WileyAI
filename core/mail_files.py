"""Bounded, inert mail attachments. No file execution or implicit downloads."""
import base64
import binascii
import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1,max_length=240)
    type: str = Field(default="application/octet-stream",max_length=100)
    data: str = Field(max_length=7*1024*1024)

    @field_validator("name")
    @classmethod
    def filename(cls,value):
        if any(ord(char)<32 or ord(char)==127 or char in '/\\' for char in value) or value in {".",".."}:
            raise ValueError("Некорректное имя вложения")
        return value

    @field_validator("type")
    @classmethod
    def mime(cls,value):
        if not re.fullmatch(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+",value):
            raise ValueError("Некорректный MIME-тип вложения")
        return value.lower()

    @field_validator("data")
    @classmethod
    def encoded(cls,value):
        decode(value)
        return value

    def summary(self):
        raw=decode(self.data)
        return {"name":self.name,"type":self.type,"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}


def decode(value):
    try:
        raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error) as error:
        raise ValueError("Повреждённое вложение") from error
    if len(raw)>MAX_FILE:
        raise ValueError("Одно вложение не должно превышать 5 МБ")
    return raw


def add_to_message(message,attachments):
    for value in attachments:
        item=Attachment.model_validate(value)
        main,sub=item.type.split("/",1)
        message.add_attachment(decode(item.data),maintype=main,subtype=sub,filename=item.name)
