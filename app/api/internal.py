"""Endpoints called by trusted backend jobs, not end users.

The Phase 7 Lambda has no database credentials and no JWT — it authenticates
with a shared secret header instead, which is enough for a course project and
keeps the Lambda's IAM footprint to "can call this one API".
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.models.document import Document
from app.models.project import Project

router = APIRouter(prefix="/internal", tags=["internal"])


async def require_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    if not x_internal_secret or not hmac.compare_digest(
        x_internal_secret, settings.internal_shared_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal secret",
        )


class RecomputeSizeOut(BaseModel):
    project_id: int
    total_size_bytes: int


@router.post(
    "/projects/{project_id}/recompute-size",
    response_model=RecomputeSizeOut,
    dependencies=[Depends(require_internal_secret)],
)
async def recompute_project_size(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecomputeSizeOut:
    """Re-derive the denormalized counter from the documents table.

    This is the async correction path for the Phase 2 denormalization: uploads
    and deletes keep the counter right in the common case, and this endpoint
    (triggered by the compute_size Lambda on every S3 write) is what recovers
    it from any drift.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")

    total = await db.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.project_id == project_id
        )
    )
    project.total_size_bytes = int(total)
    await db.commit()

    return RecomputeSizeOut(project_id=project_id, total_size_bytes=project.total_size_bytes)
