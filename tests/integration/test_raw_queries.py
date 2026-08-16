"""Exercises app/db/raw/queries.py — the Phase 2 "without ORM" deliverable.

These hand-written asyncpg functions don't power the real API (the app uses
SQLAlchemy everywhere else); they exist to demonstrate the same database work
without an ORM, so they get their own small, self-contained test setup here
rather than reusing the API/ORM-based fixtures.
"""

import uuid

import asyncpg

from app.db.raw.queries import (
    get_project_with_documents,
    grant_project_access,
    recompute_project_total_size,
)


async def _insert_user(connection: asyncpg.Connection) -> int:
    return await connection.fetchval(
        "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id",
        f"raw-{uuid.uuid4().hex[:12]}",
        "not-a-real-hash",
    )


async def _insert_project(connection: asyncpg.Connection, owner_id: int) -> int:
    return await connection.fetchval(
        "INSERT INTO projects (name, owner_id) VALUES ($1, $2) RETURNING id",
        "Raw SQL project",
        owner_id,
    )


async def _insert_document(
    connection: asyncpg.Connection, project_id: int, uploaded_by_id: int, size_bytes: int
) -> int:
    return await connection.fetchval(
        """
        INSERT INTO documents
            (project_id, s3_key, filename, content_type, size_bytes, uploaded_by_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        project_id,
        f"projects/{project_id}/{uuid.uuid4().hex[:8]}/doc.pdf",
        "doc.pdf",
        "application/pdf",
        size_bytes,
        uploaded_by_id,
    )


async def test_get_project_with_documents_returns_nested_rows(
    raw_connection: asyncpg.Connection,
) -> None:
    user_id = await _insert_user(raw_connection)
    project_id = await _insert_project(raw_connection, user_id)
    await _insert_document(raw_connection, project_id, user_id, size_bytes=42)

    result = await get_project_with_documents(raw_connection, project_id)

    assert result is not None
    assert result["id"] == project_id
    assert len(result["documents"]) == 1
    assert result["documents"][0]["size_bytes"] == 42


async def test_get_project_with_documents_returns_none_for_unknown_project(
    raw_connection: asyncpg.Connection,
) -> None:
    result = await get_project_with_documents(raw_connection, 999_999_999)

    assert result is None


async def test_grant_project_access_inserts_then_upserts_the_role(
    raw_connection: asyncpg.Connection,
) -> None:
    owner_id = await _insert_user(raw_connection)
    guest_id = await _insert_user(raw_connection)
    project_id = await _insert_project(raw_connection, owner_id)

    await grant_project_access(raw_connection, project_id, guest_id, role="participant")
    role = await raw_connection.fetchval(
        "SELECT role FROM project_access WHERE project_id = $1 AND user_id = $2",
        project_id,
        guest_id,
    )
    assert role == "participant"

    # ON CONFLICT DO UPDATE: calling it again with a different role updates
    # the existing row instead of erroring on the composite primary key.
    await grant_project_access(raw_connection, project_id, guest_id, role="owner")
    role = await raw_connection.fetchval(
        "SELECT role FROM project_access WHERE project_id = $1 AND user_id = $2",
        project_id,
        guest_id,
    )
    assert role == "owner"


async def test_recompute_project_total_size_sums_document_bytes(
    raw_connection: asyncpg.Connection,
) -> None:
    owner_id = await _insert_user(raw_connection)
    project_id = await _insert_project(raw_connection, owner_id)
    await _insert_document(raw_connection, project_id, owner_id, size_bytes=10)
    await _insert_document(raw_connection, project_id, owner_id, size_bytes=15)

    total = await recompute_project_total_size(raw_connection, project_id)

    assert total == 25
    stored = await raw_connection.fetchval(
        "SELECT total_size_bytes FROM projects WHERE id = $1", project_id
    )
    assert stored == 25


async def test_recompute_project_total_size_is_zero_with_no_documents(
    raw_connection: asyncpg.Connection,
) -> None:
    owner_id = await _insert_user(raw_connection)
    project_id = await _insert_project(raw_connection, owner_id)

    total = await recompute_project_total_size(raw_connection, project_id)

    assert total == 0
