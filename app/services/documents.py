"""Validation helpers shared by the document endpoints."""

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BadRequestError, PayloadTooLargeError
from app.models.project import Project

READ_CHUNK_SIZE = 1024 * 1024
DEFAULT_CONTENT_TYPE = "application/octet-stream"


def sanitize_filename(filename: str | None) -> str:
    """Strip any directory part so a client cannot steer the S3 key layout."""
    candidate = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    if not candidate:
        raise BadRequestError("Every uploaded document needs a filename")

    return candidate


def validate_extension(filename: str) -> None:
    allowed = settings.allowed_document_extension_set
    if PurePosixPath(filename).suffix.lower() not in allowed:
        raise BadRequestError(
            f"Unsupported file type for '{filename}'. "
            f"Allowed extensions: {', '.join(sorted(allowed))}"
        )


async def read_upload(upload: UploadFile, max_bytes: int | None = None) -> bytes:
    """Read an upload chunk by chunk, aborting as soon as it passes the limit."""
    limit = settings.max_document_size_bytes if max_bytes is None else max_bytes
    chunks: list[bytes] = []
    total = 0

    while chunk := await upload.read(READ_CHUNK_SIZE):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(
                f"'{upload.filename}' is larger than the {limit} byte per-document limit"
            )
        chunks.append(chunk)

    return b"".join(chunks)


def ensure_project_capacity(project: Project, additional_bytes: int) -> None:
    """Check the denormalized counter instead of summing document rows."""
    projected = project.total_size_bytes + additional_bytes
    if projected > settings.max_project_size_bytes:
        raise PayloadTooLargeError(
            f"Project storage limit exceeded: {projected} bytes requested, "
            f"{settings.max_project_size_bytes} bytes allowed"
        )


def content_disposition(filename: str) -> str:
    """RFC 5987 header so non-ASCII filenames survive the download."""
    fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
