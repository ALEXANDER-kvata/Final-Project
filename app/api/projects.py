from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.core.security import get_current_user
from app.models.document import Document
from app.models.project import Project
from app.models.project_access import ProjectAccess, ProjectRole
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.access import require_role
from app.storage.s3_client import delete_objects

router = APIRouter(tags=["projects"])


async def get_project_for_user(
    db: AsyncSession,
    project_id: int,
    user_id: int,
) -> Project:
    project = await db.scalar(
        select(Project)
        .join(ProjectAccess)
        .where(Project.id == project_id, ProjectAccess.user_id == user_id)
        .options(selectinload(Project.documents))
    )
    if project is None:
        raise NotFoundError("Project not found")

    return project


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Project:
    project = Project(
        name=payload.name,
        description=payload.description,
        owner_id=current_user.id,
        total_size_bytes=0,
    )
    db.add(project)
    await db.flush()

    db.add(
        ProjectAccess(
            project_id=project.id,
            user_id=current_user.id,
            role=ProjectRole.owner,
        )
    )

    await db.commit()
    await db.refresh(project, attribute_names=["documents"])
    return project


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[Project]:
    result = await db.scalars(
        select(Project)
        .join(ProjectAccess)
        .where(ProjectAccess.user_id == current_user.id)
        .options(selectinload(Project.documents))
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    return list(result.unique())


@router.get("/project/{project_id}/info", response_model=ProjectOut)
async def get_project_info(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.participant))],
) -> Project:
    return await get_project_for_user(db, project_id, current_user.id)


@router.put("/project/{project_id}/info", response_model=ProjectOut)
async def update_project_info(
    project_id: int,
    payload: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.participant))],
) -> Project:
    project = await get_project_for_user(db, project_id, current_user.id)

    if payload.name is not None:
        project.name = payload.name
    if "description" in payload.model_fields_set:
        project.description = payload.description

    await db.commit()
    await db.refresh(project, attribute_names=["documents"])
    return project


@router.delete("/project/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.owner))],
) -> Response:
    project = await get_project_for_user(db, project_id, current_user.id)
    document_keys = list(
        await db.scalars(select(Document.s3_key).where(Document.project_id == project_id))
    )

    await delete_objects(document_keys)
    await db.delete(project)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
