from datetime import datetime

from pydantic import BaseModel

from app.models.project_access import ProjectRole


class AccessOut(BaseModel):
    project_id: int
    user_id: int
    login: str
    role: ProjectRole
    created: bool = True
    """False when the user already had access and the request was a no-op."""


class ShareLinkOut(BaseModel):
    project_id: int
    invite_url: str
    expires_at: datetime
    email_delivery: str
    """"smtp" when the mail server accepted it, "logged" when it went to the log."""
