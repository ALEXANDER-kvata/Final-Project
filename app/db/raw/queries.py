from typing import Any, Literal

import asyncpg

ProjectRole = Literal["owner", "participant"]


async def get_project_with_documents(
    conn: asyncpg.Connection,
    project_id: int,
) -> dict[str, Any] | None:
    project = await conn.fetchrow(
        """
        SELECT id, name, description, owner_id, total_size_bytes, created_at
        FROM projects
        WHERE id = $1
        """,
        project_id,
    )
    if project is None:
        return None

    documents = await conn.fetch(
        """
        SELECT id, project_id, s3_key, filename, content_type, size_bytes,
               uploaded_by_id, created_at
        FROM documents
        WHERE project_id = $1
        ORDER BY created_at DESC, id DESC
        """,
        project_id,
    )

    return {
        **dict(project),
        "documents": [dict(document) for document in documents],
    }


async def grant_project_access(
    conn: asyncpg.Connection,
    project_id: int,
    user_id: int,
    role: ProjectRole = "participant",
) -> None:
    await conn.execute(
        """
        INSERT INTO project_access (project_id, user_id, role)
        VALUES ($1, $2, $3)
        ON CONFLICT (project_id, user_id)
        DO UPDATE SET role = EXCLUDED.role
        """,
        project_id,
        user_id,
        role,
    )


async def recompute_project_total_size(
    conn: asyncpg.Connection,
    project_id: int,
) -> int:
    total_size = await conn.fetchval(
        """
        SELECT COALESCE(SUM(size_bytes), 0)
        FROM documents
        WHERE project_id = $1
        """,
        project_id,
    )
    total_size = int(total_size)

    await conn.execute(
        """
        UPDATE projects
        SET total_size_bytes = $2
        WHERE id = $1
        """,
        project_id,
        total_size,
    )
    return total_size
