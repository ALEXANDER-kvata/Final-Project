from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.core.security import get_current_user
from app.models.document import Document
from app.models.project import Project
from app.models.project_access import ProjectRole
from app.models.user import User
from app.schemas.document import DocumentOut
from app.services.access import require_document_role, require_role
from app.services.documents import (
    DEFAULT_CONTENT_TYPE,
    content_disposition,
    ensure_project_capacity,
    read_upload,
    sanitize_filename,
    validate_extension,
)
from app.storage import s3_client

router = APIRouter(tags=["documents"])


async def load_project(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")

    return project


@router.post(
    "/project/{project_id}/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    project_id: int,
    files: Annotated[list[UploadFile], File(description="One or more .pdf/.docx files")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.participant))],
) -> list[Document]:
    project = await load_project(db, project_id)

    payloads: list[tuple[str, str, bytes]] = []
    for upload in files:
        filename = sanitize_filename(upload.filename)
        validate_extension(filename)
        content_type = upload.content_type or DEFAULT_CONTENT_TYPE
        payloads.append((filename, content_type, await read_upload(upload)))

    total_bytes = sum(len(data) for _, _, data in payloads)
    ensure_project_capacity(project, total_bytes)

    documents: list[Document] = []
    uploaded_keys: list[str] = []
    try:
        for filename, content_type, data in payloads:
            document = Document(
                project_id=project_id,
                # The key needs the row id, so insert with a unique placeholder first.
                s3_key=f"pending/{uuid4().hex}",
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                uploaded_by_id=current_user.id,
            )
            db.add(document)
            await db.flush()

            document.s3_key = s3_client.build_document_key(project_id, document.id, filename)
            await s3_client.upload(document.s3_key, data, content_type)
            uploaded_keys.append(document.s3_key)
            documents.append(document)

        project.total_size_bytes += total_bytes
        await db.commit()
    except Exception:
        await db.rollback()
        await s3_client.delete_objects(uploaded_keys)
        raise

    for document in documents:
        await db.refresh(document)

    return documents


@router.get("/project/{project_id}/documents", response_model=list[DocumentOut])
async def list_project_documents(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _role: Annotated[ProjectRole, Depends(require_role(ProjectRole.participant))],
) -> list[Document]:
    result = await db.scalars(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
    )
    return list(result)


@router.get("/document/{document_id}", response_class=StreamingResponse)
async def download_document(
    document: Annotated[Document, Depends(require_document_role(ProjectRole.participant))],
) -> StreamingResponse:
    await s3_client.ensure_object_exists(document.s3_key)

    return StreamingResponse(
        s3_client.stream_object(document.s3_key),
        media_type=document.content_type,
        headers={"Content-Disposition": content_disposition(document.filename)},
    )


@router.put("/document/{document_id}", response_model=DocumentOut)
async def replace_document(
    file: Annotated[UploadFile, File(description="Replacement .pdf/.docx file")],
    db: Annotated[AsyncSession, Depends(get_db)],
    document: Annotated[Document, Depends(require_document_role(ProjectRole.participant))],
) -> Document:
    filename = sanitize_filename(file.filename)
    validate_extension(filename)
    content_type = file.content_type or DEFAULT_CONTENT_TYPE
    data = await read_upload(file)

    project = await load_project(db, document.project_id)
    size_delta = len(data) - document.size_bytes
    ensure_project_capacity(project, size_delta)

    previous_key = document.s3_key
    new_key = s3_client.build_document_key(document.project_id, document.id, filename)
    await s3_client.upload(new_key, data, content_type)

    try:
        document.s3_key = new_key
        document.filename = filename
        document.content_type = content_type
        document.size_bytes = len(data)
        project.total_size_bytes += size_delta
        await db.commit()
    except Exception:
        await db.rollback()
        if new_key != previous_key:
            await s3_client.delete_object(new_key)
        raise

    if new_key != previous_key:
        await s3_client.delete_object(previous_key)

    await db.refresh(document)
    return document


@router.delete("/document/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    db: Annotated[AsyncSession, Depends(get_db)],
    document: Annotated[Document, Depends(require_document_role(ProjectRole.participant))],
) -> Response:
    project = await load_project(db, document.project_id)
    freed_bytes = document.size_bytes
    key = document.s3_key

    await db.delete(document)
    project.total_size_bytes = max(0, project.total_size_bytes - freed_bytes)
    await db.commit()

    await s3_client.delete_object(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
