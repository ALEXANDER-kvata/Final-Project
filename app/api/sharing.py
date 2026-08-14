from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_invite_token, decode_invite_token, get_current_user
from app.models.project import Project
from app.models.project_access import ProjectRole
from app.models.user import User
from app.schemas.sharing import AccessOut, ShareLinkOut
from app.services.access import require_role
from app.services.email import send_invite_email
from app.services.sharing import grant_access

router = APIRouter(tags=["sharing"])

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


@router.post("/project/{project_id}/invite", response_model=AccessOut)
async def invite_user(
    project_id: int,
    user: Annotated[str, Query(min_length=3, max_length=100, description="Login to invite")],
    db: Annotated[AsyncSession, Depends(get_db)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.owner))],
) -> AccessOut:
    target = await db.scalar(select(User).where(User.login == user))
    if target is None:
        raise NotFoundError(f"User '{user}' not found")

    access, created = await grant_access(db, project_id, target)
    return AccessOut(
        project_id=project_id,
        user_id=target.id,
        login=target.login,
        role=access.role,
        created=created,
    )


@router.get("/project/{project_id}/share", response_model=ShareLinkOut)
async def share_project(
    project_id: int,
    with_email: Annotated[
        str,
        Query(alias="with", pattern=EMAIL_PATTERN, description="Email address to invite"),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.owner))],
) -> ShareLinkOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")

    token, expires_at = create_invite_token(project_id)
    invite_url = f"{settings.app_base_url.rstrip('/')}/join?token={token}"
    delivery = await send_invite_email(with_email, project.name, invite_url)

    return ShareLinkOut(
        project_id=project_id,
        invite_url=invite_url,
        expires_at=expires_at,
        email_delivery=delivery,
    )


@router.get("/join", response_model=AccessOut)
async def join_project(
    token: Annotated[str, Query(description="Token from the share link")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AccessOut:
    project_id = decode_invite_token(token)

    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")

    access, created = await grant_access(db, project_id, current_user)
    return AccessOut(
        project_id=project_id,
        user_id=current_user.id,
        login=current_user.login,
        role=access.role,
        created=created,
    )
