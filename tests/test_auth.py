from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import get_current_user, hash_password, verify_password
from app.main import app
from app.models.user import User
from app.schemas.user import UserCreate


def test_user_create_requires_matching_passwords() -> None:
    with pytest.raises(ValidationError):
        UserCreate(login="demo", password="password123", repeat_password="different123")


def test_password_hashing_round_trip() -> None:
    password_hash = hash_password("password123")

    assert password_hash != "password123"
    assert verify_password("password123", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_me_requires_bearer_token() -> None:
    client = TestClient(app)

    response = client.get("/me")

    assert response.status_code == 401


def test_me_returns_current_user_without_password_hash() -> None:
    async def override_current_user() -> User:
        return User(
            id=1,
            login="demo",
            password_hash="hidden",
            created_at=datetime(2026, 1, 1),
        )

    app.dependency_overrides[get_current_user] = override_current_user
    client = TestClient(app)

    try:
        response = client.get("/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "login": "demo",
        "created_at": "2026-01-01T00:00:00",
    }
    assert "password_hash" not in response.json()


def test_login_route_is_registered_in_openapi() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()

    assert "/auth" in schema["paths"]
    assert "/login" in schema["paths"]


def test_login_accepts_json_payload() -> None:
    user = User(id=1, login="demo", password_hash=hash_password("password123"))

    class FakeDb:
        async def scalar(self, _statement: object) -> User:
            return user

    app.dependency_overrides[get_db] = lambda: FakeDb()
    client = TestClient(app)

    try:
        response = client.post("/login", json={"login": "demo", "password": "password123"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_register_recovers_when_two_registrations_race() -> None:
    """Two concurrent registrations for the same login can both pass the
    initial "login is free" check; the DB's unique constraint is the real
    guard, and the loser must turn that IntegrityError into a 409 instead of
    a 500."""

    class RacingDb:
        def __init__(self) -> None:
            self.rolled_back = False

        async def scalar(self, _statement: object) -> None:
            return None

        def add(self, _instance: object) -> None:
            pass

        async def commit(self) -> None:
            raise IntegrityError("insert", {}, Exception("duplicate key"))

        async def rollback(self) -> None:
            self.rolled_back = True

    db = RacingDb()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    try:
        response = client.post(
            "/auth",
            json={
                "login": "demo",
                "password": "password123",
                "repeat_password": "password123",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert db.rolled_back is True


def test_login_accepts_oauth_form_payload() -> None:
    user = User(id=1, login="demo", password_hash=hash_password("password123"))

    class FakeDb:
        async def scalar(self, _statement: object) -> User:
            return user

    app.dependency_overrides[get_db] = lambda: FakeDb()
    client = TestClient(app)

    try:
        response = client.post(
            "/login",
            data={"username": "demo", "password": "password123"},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_access_token_contains_user_subject() -> None:
    from app.core.security import create_access_token

    token = create_access_token(user_id=42)
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )

    assert payload["sub"] == "42"
    assert "exp" in payload
