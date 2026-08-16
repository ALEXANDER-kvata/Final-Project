import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.dependencies import get_db
from app.main import app
from app.models.project import Project


def test_recompute_size_route_is_registered_in_openapi() -> None:
    client = TestClient(app)

    schema = client.get("/openapi.json").json()

    assert "/internal/projects/{project_id}/recompute-size" in schema["paths"]


def test_recompute_size_rejects_missing_secret() -> None:
    client = TestClient(app)

    response = client.post("/internal/projects/1/recompute-size")

    assert response.status_code == 401


def test_recompute_size_rejects_wrong_secret() -> None:
    client = TestClient(app)

    response = client.post(
        "/internal/projects/1/recompute-size",
        headers={"X-Internal-Secret": "not-the-secret"},
    )

    assert response.status_code == 401


def test_recompute_size_sums_documents_and_updates_the_project() -> None:
    project = Project(id=1, name="demo", owner_id=1, total_size_bytes=999)

    class FakeDb:
        commits = 0

        async def get(self, _model: object, _pk: object) -> Project:
            return project

        async def scalar(self, _statement: object) -> int:
            return 30

        async def commit(self) -> None:
            self.commits += 1

    fake_db = FakeDb()
    app.dependency_overrides[get_db] = lambda: fake_db
    client = TestClient(app)

    try:
        response = client.post(
            "/internal/projects/1/recompute-size",
            headers={"X-Internal-Secret": settings.internal_shared_secret},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"project_id": 1, "total_size_bytes": 30}
    assert project.total_size_bytes == 30
    assert fake_db.commits == 1


def test_recompute_size_treats_no_documents_as_zero() -> None:
    project = Project(id=1, name="demo", owner_id=1, total_size_bytes=999)

    class FakeDb:
        async def get(self, _model: object, _pk: object) -> Project:
            return project

        async def scalar(self, _statement: object) -> int:
            return 0

        async def commit(self) -> None:
            pass

    app.dependency_overrides[get_db] = lambda: FakeDb()
    client = TestClient(app)

    try:
        response = client.post(
            "/internal/projects/1/recompute-size",
            headers={"X-Internal-Secret": settings.internal_shared_secret},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total_size_bytes"] == 0


def test_recompute_size_404s_for_unknown_project() -> None:
    class FakeDb:
        async def get(self, _model: object, _pk: object) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: FakeDb()
    client = TestClient(app)

    try:
        response = client.post(
            "/internal/projects/999/recompute-size",
            headers={"X-Internal-Secret": settings.internal_shared_secret},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("projects/7/42/report.pdf", 7),
        ("projects/1/1/a b.pdf", 1),
        ("thumbnails/7/42/report.pdf", None),
        ("projects/", None),
        ("projects/not-a-number/42/report.pdf", None),
        ("", None),
    ],
)
def test_compute_size_lambda_parses_project_id_from_key(key: str, expected: int | None) -> None:
    from lambdas.compute_size.handler import _project_id_from_key

    assert _project_id_from_key(key) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("projects/7/42/photo.png", "thumbnails/7/42/photo.png"),
        ("projects/7/42/report.pdf", "thumbnails/7/42/report.pdf"),
        ("thumbnails/7/42/photo.png", None),
        ("other/7/42/photo.png", None),
    ],
)
def test_resize_image_lambda_derives_thumbnail_key(key: str, expected: str | None) -> None:
    from lambdas.resize_image.logic import thumbnail_key

    assert thumbnail_key(key) == expected


@pytest.mark.parametrize(
    ("filename", "is_image"),
    [
        ("photo.png", True),
        ("photo.JPG", True),
        ("photo.jpeg", True),
        ("report.pdf", False),
        ("report.docx", False),
    ],
)
def test_resize_image_lambda_extension_filter(filename: str, is_image: bool) -> None:
    from lambdas.resize_image.logic import is_image_key

    assert is_image_key(filename) is is_image
