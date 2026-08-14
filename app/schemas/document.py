from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    id: int
    project_id: int
    s3_key: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
