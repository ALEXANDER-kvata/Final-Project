import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ForbiddenError, NotFoundError
from app.main import app
from app.models.project_access import ProjectRole
from app.models.user import User
from app.services.access import require_role


def test_project_routes_are_registered_in_openapi() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()

    assert "/projects" in schema["paths"]
    assert "/project/{project_id}/info" in schema["paths"]
    assert "/project/{project_id}" in schema["paths"]


def test_project_routes_require_authentication() -> None:
    client = TestClient(app)

    response = client.get("/projects")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_require_role_allows_owner_for_owner_action() -> None:
    class FakeDb:
        async def scalar(self, statement: object) -> ProjectRole:
            return ProjectRole.owner

    dependency = require_role(ProjectRole.owner)
    role = await dependency(
        project_id=1,
        db=FakeDb(),
        current_user=User(id=1, login="demo", password_hash="hidden"),
    )

    assert role == ProjectRole.owner


@pytest.mark.asyncio
async def test_require_role_rejects_participant_for_owner_action() -> None:
    class FakeDb:
        async def scalar(self, statement: object) -> ProjectRole:
            return ProjectRole.participant

    dependency = require_role(ProjectRole.owner)

    with pytest.raises(ForbiddenError):
        await dependency(
            project_id=1,
            db=FakeDb(),
            current_user=User(id=1, login="demo", password_hash="hidden"),
        )


@pytest.mark.asyncio
async def test_require_role_hides_project_without_access() -> None:
    class FakeDb:
        async def scalar(self, statement: object) -> None:
            return None

    dependency = require_role(ProjectRole.participant)

    with pytest.raises(NotFoundError):
        await dependency(
            project_id=1,
            db=FakeDb(),
            current_user=User(id=1, login="demo", password_hash="hidden"),
        )
