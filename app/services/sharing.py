"""Granting project access to other users."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_access import ProjectAccess, ProjectRole
from app.models.user import User


async def grant_access(
    db: AsyncSession,
    project_id: int,
    user: User,
    role: ProjectRole = ProjectRole.participant,
) -> tuple[ProjectAccess, bool]:
    """Give ``user`` access to a project, returning ``(access, created)``.

    Idempotent by design: an existing membership is returned untouched, so
    re-inviting somebody is a no-op and can never demote a project owner.
    """
    existing = await db.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project_id,
            ProjectAccess.user_id == user.id,
        )
    )
    if existing is not None:
        return existing, False

    access = ProjectAccess(project_id=project_id, user_id=user.id, role=role)
    db.add(access)

    try:
        await db.commit()
    except IntegrityError:
        # Two invites raced for the same composite primary key; the other won.
        await db.rollback()
        existing = await db.scalar(
            select(ProjectAccess).where(
                ProjectAccess.project_id == project_id,
                ProjectAccess.user_id == user.id,
            )
        )
        if existing is None:
            raise
        return existing, False

    return access, True
