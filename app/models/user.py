from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.project import Project
    from app.models.project_access import ProjectAccess


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    owned_projects: Mapped[list[Project]] = relationship(
        back_populates="owner",
        foreign_keys="Project.owner_id",
    )
    access_entries: Mapped[list[ProjectAccess]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    projects: Mapped[list[Project]] = relationship(
        secondary="project_access",
        back_populates="users",
        viewonly=True,
    )
    uploaded_documents: Mapped[list[Document]] = relationship(
        back_populates="uploaded_by",
        foreign_keys="Document.uploaded_by_id",
    )
