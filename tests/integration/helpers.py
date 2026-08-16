"""Small helpers shared across the integration test modules."""

import uuid

from httpx import AsyncClient

DEFAULT_PASSWORD = "supersecret123"


def unique_login(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def register_and_login(client: AsyncClient, login: str | None = None) -> tuple[str, str]:
    """Returns (login, access_token)."""
    login = login or unique_login()
    register = await client.post(
        "/auth",
        json={"login": login, "password": DEFAULT_PASSWORD, "repeat_password": DEFAULT_PASSWORD},
    )
    assert register.status_code == 201, register.text

    login_response = await client.post(
        "/login", json={"login": login, "password": DEFAULT_PASSWORD}
    )
    assert login_response.status_code == 200, login_response.text

    return login, login_response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_project(client: AsyncClient, token: str, name: str = "Integration project") -> int:
    response = await client.post(
        "/projects",
        headers=auth_headers(token),
        json={"name": name, "description": "created by the integration suite"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
