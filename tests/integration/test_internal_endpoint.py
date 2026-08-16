"""Exercises /internal/projects/{id}/recompute-size against a real database.

tests/test_internal.py already covers this route's logic with a FakeDb; this
file proves the real SQLAlchemy query (SUM over documents, written back to
projects.total_size_bytes) against real Postgres — the same call the
compute_size Lambda makes in production (see lambdas/compute_size/handler.py).
"""

from httpx import AsyncClient

from app.core.config import settings
from tests.integration.helpers import auth_headers, create_project, register_and_login


async def test_recompute_size_derives_the_true_total_from_real_documents(
    client: AsyncClient,
) -> None:
    _login, token = await register_and_login(client)
    project_id = await create_project(client, token)

    await client.post(
        f"/project/{project_id}/documents",
        headers=auth_headers(token),
        files={"files": ("a.pdf", b"%PDF-1.4 first document", "application/pdf")},
    )
    await client.post(
        f"/project/{project_id}/documents",
        headers=auth_headers(token),
        files={"files": ("b.pdf", b"%PDF-1.4 second, slightly longer document", "application/pdf")},
    )
    expected_total = len(b"%PDF-1.4 first document") + len(
        b"%PDF-1.4 second, slightly longer document"
    )

    response = await client.post(
        f"/internal/projects/{project_id}/recompute-size",
        headers={"X-Internal-Secret": settings.internal_shared_secret},
    )

    assert response.status_code == 200
    assert response.json() == {"project_id": project_id, "total_size_bytes": expected_total}


async def test_recompute_size_rejects_wrong_secret(client: AsyncClient) -> None:
    _login, token = await register_and_login(client)
    project_id = await create_project(client, token)

    response = await client.post(
        f"/internal/projects/{project_id}/recompute-size",
        headers={"X-Internal-Secret": "definitely-wrong"},
    )

    assert response.status_code == 401


async def test_recompute_size_404s_for_unknown_project(client: AsyncClient) -> None:
    response = await client.post(
        "/internal/projects/999999999/recompute-size",
        headers={"X-Internal-Secret": settings.internal_shared_secret},
    )

    assert response.status_code == 404
