"""A bounded snapshot of the exact document text selected for one answer."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentFragment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=4096)
    offset: int = Field(ge=0, lt=1_000_000)
    text: str = Field(min_length=1, max_length=1200)
    total: int = Field(ge=1, le=1_000_000)

    @model_validator(mode="after")
    def valid_range(self):
        if self.offset + len(self.text) > self.total:
            raise ValueError("Фрагмент выходит за границы документа")
        return self
