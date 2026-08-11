from sqlalchemy.orm import configure_mappers

import app.models
from app.db.base import Base


def test_phase_two_tables_are_registered() -> None:
    expected_tables = {"users", "projects", "project_access", "documents"}

    assert expected_tables.issubset(Base.metadata.tables)


def test_model_relationships_configure() -> None:
    configure_mappers()

    assert app.models.Project.__tablename__ == "projects"
    assert app.models.User.__tablename__ == "users"
    assert app.models.ProjectAccess.__tablename__ == "project_access"
    assert app.models.Document.__tablename__ == "documents"
