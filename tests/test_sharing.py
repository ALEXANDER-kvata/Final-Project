from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.security import create_access_token, create_invite_token, decode_invite_token
from app.main import app
from app.models.project_access import ProjectAccess, ProjectRole
from app.models.user import User
from app.services.email import send_invite_email
from app.services.sharing import grant_access


class FakeDb:
    """Records what the service would have written, without a database."""

    def __init__(self, existing: ProjectAccess | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, statement: object) -> ProjectAccess | None:
        return self.existing

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


def test_sharing_routes_are_registered_in_openapi() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()

    assert "/project/{project_id}/invite" in schema["paths"]
    assert "/project/{project_id}/share" in schema["paths"]
    assert "/join" in schema["paths"]


def test_share_route_exposes_the_with_alias() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/project/{project_id}/share"]["get"]["parameters"]

    assert "with" in {parameter["name"] for parameter in parameters}


def test_sharing_routes_require_authentication() -> None:
    client = TestClient(app)

    assert client.post("/project/1/invite", params={"user": "someone"}).status_code == 401
    assert client.get("/join", params={"token": "irrelevant"}).status_code == 401


def test_invite_token_round_trips() -> None:
    token, expires_at = create_invite_token(42)

    assert decode_invite_token(token) == 42
    assert expires_at > datetime.now(UTC)


def test_access_token_is_not_accepted_as_an_invite() -> None:
    """Both are signed with the same secret, so the purpose claim must separate them."""
    access_token = create_access_token(user_id=1)

    with pytest.raises(BadRequestError):
        decode_invite_token(access_token)


def test_tampered_invite_token_is_rejected() -> None:
    token, _ = create_invite_token(42)

    with pytest.raises(BadRequestError):
        decode_invite_token(token + "x")


def test_expired_invite_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invite_token_expire_minutes", -1)
    token, _ = create_invite_token(42)

    with pytest.raises(BadRequestError):
        decode_invite_token(token)


async def test_grant_access_creates_a_participant_row() -> None:
    db = FakeDb(existing=None)
    user = User(id=7, login="invitee", password_hash="hidden")

    access, created = await grant_access(db, project_id=3, user=user)

    assert created is True
    assert (access.project_id, access.user_id, access.role) == (3, 7, ProjectRole.participant)
    assert db.added == [access]
    assert db.commits == 1


async def test_grant_access_is_idempotent_for_existing_members() -> None:
    existing = ProjectAccess(project_id=3, user_id=7, role=ProjectRole.participant)
    db = FakeDb(existing=existing)
    user = User(id=7, login="invitee", password_hash="hidden")

    access, created = await grant_access(db, project_id=3, user=user)

    assert created is False
    assert access is existing
    assert db.added == []
    assert db.commits == 0


async def test_grant_access_never_demotes_an_owner() -> None:
    owner_access = ProjectAccess(project_id=3, user_id=1, role=ProjectRole.owner)
    db = FakeDb(existing=owner_access)
    owner = User(id=1, login="owner", password_hash="hidden")

    access, created = await grant_access(db, project_id=3, user=owner)

    assert created is False
    assert access.role == ProjectRole.owner


async def test_grant_access_recovers_when_two_invites_race() -> None:
    """Two concurrent invites can both pass the initial "no existing row" check;
    only one INSERT wins the composite primary key and the loser must recover
    by re-reading what the winner wrote, instead of letting the IntegrityError
    bubble up as a 500."""
    winner = ProjectAccess(project_id=3, user_id=7, role=ProjectRole.participant)

    class RacingDb(FakeDb):
        def __init__(self) -> None:
            super().__init__(existing=None)
            self._scalar_calls = 0

        async def scalar(self, statement: object) -> ProjectAccess | None:
            self._scalar_calls += 1
            return None if self._scalar_calls == 1 else winner

        async def commit(self) -> None:
            self.commits += 1
            raise IntegrityError("insert", {}, Exception("duplicate key"))

    db = RacingDb()
    user = User(id=7, login="invitee", password_hash="hidden")

    access, created = await grant_access(db, project_id=3, user=user)

    assert created is False
    assert access is winner
    assert db.commits == 1


async def test_invite_email_falls_back_to_logging_without_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)

    delivery = await send_invite_email(
        "someone@example.com", "Demo", "http://localhost/join?token=x"
    )

    assert delivery == "logged"


async def test_invite_email_reports_logged_when_smtp_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead mail server must not fail the share request."""
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)

    delivery = await send_invite_email(
        "someone@example.com", "Demo", "http://localhost/join?token=x"
    )

    assert delivery == "logged"
