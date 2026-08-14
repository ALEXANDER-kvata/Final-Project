from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import get_current_user
from app.models.document import Document
from app.models.project_access import ProjectAccess, ProjectRole
from app.models.user import User

ROLE_RANK = {
    ProjectRole.participant: 1,
    ProjectRole.owner: 2,
}


async def get_user_role(
    db: AsyncSession,
    project_id: int,
    user_id: int,
) -> ProjectRole | None:
    return await db.scalar(
        select(ProjectAccess.role).where(
            ProjectAccess.project_id == project_id,
            ProjectAccess.user_id == user_id,
        )
    )


def require_role(
    minimum_role: ProjectRole,
) -> Callable[[int, AsyncSession, User], ProjectRole]:
    async def dependency(
        project_id: int,
        db: Annotated[AsyncSession, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> ProjectRole:
        role = await get_user_role(db, project_id, current_user.id)
        if role is None:
            raise NotFoundError("Project not found")

        if ROLE_RANK[role] < ROLE_RANK[minimum_role]:
            raise ForbiddenError("You do not have permission to perform this action")

        return role

    return dependency


def require_document_role(
    minimum_role: ProjectRole,
) -> Callable[[int, AsyncSession, User], Document]:
    """Resolve a document and authorize the caller against its *parent project*."""

    async def dependency(
        document_id: int,
        db: Annotated[AsyncSession, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> Document:
        document = await db.get(Document, document_id)
        if document is None:
            raise NotFoundError("Document not found")

        role = await get_user_role(db, document.project_id, current_user.id)
        if role is None:
            raise NotFoundError("Document not found")

        if ROLE_RANK[role] < ROLE_RANK[minimum_role]:
            raise ForbiddenError("You do not have permission to perform this action")

        return document

    return dependency
