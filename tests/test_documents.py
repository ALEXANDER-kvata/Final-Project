import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
)
from app.core.security import get_current_user
from app.main import app
from app.models.document import Document
from app.models.project import Project
from app.models.project_access import ProjectRole
from app.models.user import User
from app.services.access import require_document_role
from app.services.documents import (
    content_disposition,
    ensure_project_capacity,
    read_upload,
    sanitize_filename,
    validate_extension,
)
from app.storage import s3_client
from app.storage.s3_client import build_document_key


class FakeUpload:
    """Minimal stand-in for UploadFile: only ``read`` and ``filename`` are used."""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._offset
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_document_routes_are_registered_in_openapi() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()

    assert "/project/{project_id}/documents" in schema["paths"]
    assert "/document/{document_id}" in schema["paths"]
    assert set(schema["paths"]["/document/{document_id}"]) == {"get", "put", "delete"}


def test_document_routes_require_authentication() -> None:
    client = TestClient(app)

    response = client.get("/document/1")

    assert response.status_code == 401


def test_build_document_key_groups_objects_by_project() -> None:
    assert build_document_key(7, 42, "report.pdf") == "projects/7/42/report.pdf"


def test_sanitize_filename_drops_directory_components() -> None:
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename(r"C:\Users\demo\report.docx") == "report.docx"


def test_sanitize_filename_rejects_empty_names() -> None:
    with pytest.raises(BadRequestError):
        sanitize_filename(None)


def test_validate_extension_accepts_configured_types() -> None:
    validate_extension("report.pdf")
    validate_extension("NOTES.DOCX")


def test_validate_extension_rejects_other_types() -> None:
    with pytest.raises(BadRequestError):
        validate_extension("payload.exe")


async def test_read_upload_returns_full_content() -> None:
    upload = FakeUpload("report.pdf", b"%PDF-1.7 sample bytes")

    assert await read_upload(upload) == b"%PDF-1.7 sample bytes"


async def test_read_upload_rejects_oversized_files() -> None:
    upload = FakeUpload("report.pdf", b"x" * 64)

    with pytest.raises(PayloadTooLargeError):
        await read_upload(upload, max_bytes=16)


def test_ensure_project_capacity_allows_upload_within_limit() -> None:
    project = Project(id=1, name="demo", owner_id=1, total_size_bytes=0)

    ensure_project_capacity(project, 1024)


def test_ensure_project_capacity_rejects_upload_over_limit() -> None:
    project = Project(
        id=1,
        name="demo",
        owner_id=1,
        total_size_bytes=settings.max_project_size_bytes,
    )

    with pytest.raises(PayloadTooLargeError):
        ensure_project_capacity(project, 1)


def test_content_disposition_keeps_unicode_filenames_readable() -> None:
    header = content_disposition("отчёт.pdf")

    assert header.startswith("attachment; filename=")
    assert "filename*=UTF-8''" in header
    assert header.isascii()


async def test_upload_documents_cleans_up_s3_when_the_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DB failure after files are already in S3 must not leave orphaned
    objects behind: the route rolls back the transaction and deletes
    everything it just uploaded."""
    project = Project(id=1, name="demo", owner_id=1, total_size_bytes=0)

    class FailingDb:
        def __init__(self) -> None:
            self.rolled_back = False
            self._next_id = 100

        async def get(self, entity: object, ident: object) -> Project:
            return project

        async def scalar(self, statement: object) -> ProjectRole:
            return ProjectRole.participant

        def add(self, instance: Document) -> None:
            instance.id = self._next_id
            self._next_id += 1

        async def flush(self) -> None:
            pass

        async def commit(self) -> None:
            raise IntegrityError("insert", {}, Exception("boom"))

        async def rollback(self) -> None:
            self.rolled_back = True

    db = FailingDb()
    deleted_keys: list[str] = []

    async def fake_upload(key: str, data: bytes, content_type: str) -> None:
        pass

    async def fake_delete_objects(keys: list[str]) -> None:
        deleted_keys.extend(keys)

    monkeypatch.setattr(s3_client, "upload", fake_upload)
    monkeypatch.setattr(s3_client, "delete_objects", fake_delete_objects)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, login="demo", password_hash="hidden"
    )
    client = TestClient(app)

    try:
        with pytest.raises(IntegrityError):
            client.post(
                "/project/1/documents",
                files=[("files", ("report.pdf", b"%PDF-1.7", "application/pdf"))],
            )
    finally:
        app.dependency_overrides.clear()

    assert db.rolled_back is True
    assert deleted_keys == ["projects/1/100/report.pdf"]


def _document(project_id: int = 1) -> Document:
    return Document(
        id=10,
        project_id=project_id,
        s3_key="projects/1/10/report.pdf",
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=5,
        uploaded_by_id=1,
    )


class FakeDb:
    def __init__(self, document: Document | None, role: ProjectRole | None) -> None:
        self._document = document
        self._role = role

    async def get(self, entity: object, ident: object) -> Document | None:
        return self._document

    async def scalar(self, statement: object) -> ProjectRole | None:
        return self._role


async def test_require_document_role_returns_document_for_member() -> None:
    document = _document()
    dependency = require_document_role(ProjectRole.participant)

    resolved = await dependency(
        document_id=10,
        db=FakeDb(document, ProjectRole.participant),
        current_user=User(id=1, login="demo", password_hash="hidden"),
    )

    assert resolved is document


async def test_require_document_role_hides_documents_from_non_members() -> None:
    dependency = require_document_role(ProjectRole.participant)

    with pytest.raises(NotFoundError):
        await dependency(
            document_id=10,
            db=FakeDb(_document(), None),
            current_user=User(id=2, login="intruder", password_hash="hidden"),
        )


async def test_require_document_role_rejects_participant_for_owner_action() -> None:
    dependency = require_document_role(ProjectRole.owner)

    with pytest.raises(ForbiddenError):
        await dependency(
            document_id=10,
            db=FakeDb(_document(), ProjectRole.participant),
            current_user=User(id=2, login="helper", password_hash="hidden"),
        )


async def test_require_document_role_404s_on_missing_document() -> None:
    dependency = require_document_role(ProjectRole.participant)

    with pytest.raises(NotFoundError):
        await dependency(
            document_id=999,
            db=FakeDb(None, ProjectRole.owner),
            current_user=User(id=1, login="demo", password_hash="hidden"),
        )
