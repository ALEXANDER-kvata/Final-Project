from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select

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


class SupportsScalarLookup(Protocol):
    """The slice of ``AsyncSession`` that ``get_user_role`` relies on.

    Kept narrow so tests can pass a lightweight fake instead of a real
    ``AsyncSession`` without upsetting the type checker.
    """

    async def scalar(self, statement: object) -> ProjectRole | None: ...


class SupportsDocumentLookup(SupportsScalarLookup, Protocol):
    """The slice of ``AsyncSession`` that ``require_document_role`` relies on."""

    async def get(self, entity: type[Document], ident: int) -> Document | None: ...


class RoleDependency(Protocol):
    """Callable shape of a ``require_role`` dependency, keyed by name.

    FastAPI's ``Depends`` resolves these by parameter name, and tests call
    them the same way, so the type keeps those names rather than collapsing
    to a positional ``Callable``.
    """

    async def __call__(
        self,
        project_id: int,
        db: SupportsScalarLookup,
        current_user: User,
    ) -> ProjectRole: ...


class DocumentRoleDependency(Protocol):
    """Callable shape of a ``require_document_role`` dependency, keyed by name."""

    async def __call__(
        self,
        document_id: int,
        db: SupportsDocumentLookup,
        current_user: User,
    ) -> Document: ...


async def get_user_role(
    db: SupportsScalarLookup,
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
) -> RoleDependency:
    async def dependency(
        project_id: int,
        db: Annotated[SupportsScalarLookup, Depends(get_db)],
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
) -> DocumentRoleDependency:
    """Resolve a document and authorize the caller against its *parent project*."""

    async def dependency(
        document_id: int,
        db: Annotated[SupportsDocumentLookup, Depends(get_db)],
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
