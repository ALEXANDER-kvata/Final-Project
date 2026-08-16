from httpx import AsyncClient

from app.core.config import settings
from tests.integration.helpers import (
    DEFAULT_PASSWORD,
    auth_headers,
    register_and_login,
    unique_login,
)


async def test_register_login_and_access_a_protected_route(client: AsyncClient) -> None:
    login, token = await register_and_login(client)

    me = await client.get("/me", headers=auth_headers(token))

    assert me.status_code == 200
    assert me.json()["login"] == login
    assert "password_hash" not in me.json()


async def test_duplicate_registration_is_rejected(client: AsyncClient) -> None:
    login = unique_login()
    await register_and_login(client, login)

    second = await client.post(
        "/auth",
        json={"login": login, "password": DEFAULT_PASSWORD, "repeat_password": DEFAULT_PASSWORD},
    )

    assert second.status_code == 409


async def test_login_with_wrong_password_is_rejected(client: AsyncClient) -> None:
    login = unique_login()
    await register_and_login(client, login)

    response = await client.post("/login", json={"login": login, "password": "not-the-password"})

    assert response.status_code == 401


async def test_login_with_unknown_user_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/login", json={"login": unique_login("ghost"), "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401


async def test_expired_token_is_rejected(client: AsyncClient, monkeypatch) -> None:
    _login, _token = await register_and_login(client)

    # Mint a token that is already expired, through the real signing path.
    monkeypatch.setattr(settings, "jwt_expire_minutes", -1)
    from app.core.security import create_access_token

    me = await client.get("/me", headers=auth_headers(create_access_token(user_id=1)))

    assert me.status_code == 401


async def test_missing_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/me")

    assert response.status_code == 401
