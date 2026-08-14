from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document import DocumentOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    total_size_bytes: int
    created_at: datetime
    documents: list[DocumentOut] = []

    model_config = ConfigDict(from_attributes=True)
