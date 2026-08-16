"""GET /health talks to Postgres through its own engine, independent of the
per-test session override, so this just confirms the real dev database
(not the isolated test database) is reachable."""

from httpx import AsyncClient


async def test_health_reports_ok_when_the_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
