"""Fixture-plumbing sanity check. The real coverage lives in the other files."""

from httpx import AsyncClient


async def test_can_register_a_user(client: AsyncClient) -> None:
    response = await client.post(
        "/auth",
        json={
            "login": "smoketest",
            "password": "supersecret123",
            "repeat_password": "supersecret123",
        },
    )

    assert response.status_code == 201
    assert response.json()["login"] == "smoketest"
