"""Fixtures for the integration suite.

Unlike tests/*.py (fast, dependency-injected fakes, no external services),
these tests drive the real FastAPI app through httpx against a real Postgres
database and real LocalStack S3 — genuine end-to-end coverage of routing,
SQLAlchemy, password hashing, JWT, and S3 calls together.

They need `docker compose up` (at least the db and localstack services)
running. When either is unreachable, every test here is skipped rather than
failed, so a plain `pytest` still passes for someone who hasn't started
Docker — matching how the rest of the suite behaves.

Why LocalStack and not moto: this app talks to S3 through aioboto3
(aiobotocore), which makes its HTTP calls over aiohttp. moto's request
interception patches botocore's own HTTP layer and does not reliably catch
aiohttp-based calls, so it silently doesn't mock aiobotocore traffic. The
plan's Phase 8 notes explicitly allow this alternative ("mock S3 with moto,
or point at LocalStack in CI"), and this project already has a fully wired,
verified LocalStack setup from Phase 5/7 — reusing it here is both more
reliable and less to maintain than fighting that incompatibility.
"""

import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import settings
from app.core.dependencies import get_db
from app.main import app
from app.storage.s3_client import ensure_bucket

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DB_NAME = "project_dashboard_test"

pytestmark = pytest.mark.integration


def _database_base_url() -> str:
    return settings.database_url.rsplit("/", 1)[0]


def _test_database_url() -> str:
    return f"{_database_base_url()}/{TEST_DB_NAME}"


def _asyncpg_dsn() -> str:
    # asyncpg.connect() speaks a plain postgresql:// DSN, not SQLAlchemy's
    # driver-qualified postgresql+asyncpg:// URL.
    return _test_database_url().replace("postgresql+asyncpg://", "postgresql://", 1)


def _service_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _ensure_test_database_exists() -> None:
    admin_engine = create_async_engine(
        f"{_database_base_url()}/postgres", isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await admin_engine.dispose()


def _run_migrations(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )


@pytest.fixture(scope="session")
def services_available() -> bool:
    # Postgres and LocalStack's edge port, both published by docker-compose.yml.
    return _service_reachable("localhost", 5432) and _service_reachable("localhost", 4566)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def environment_ready(services_available: bool) -> None:
    if not services_available:
        pytest.skip(
            "Postgres/LocalStack not reachable on localhost — "
            "run `docker compose up -d db localstack` to enable the integration suite"
        )

    await _ensure_test_database_exists()
    _run_migrations(_test_database_url())
    await ensure_bucket()


@pytest_asyncio.fixture
async def db_session(environment_ready: None) -> AsyncIterator[AsyncSession]:
    """One test = one engine, one connection, one outer transaction rolled back at the end.

    The engine is created fresh per test (cheap: create_async_engine doesn't
    open a connection by itself) rather than shared across tests, because the
    asyncpg connections it hands out are bound to the event loop that opened
    them — pytest-asyncio gives each test function its own loop, so a shared,
    session-scoped engine would hand test 2 a connection object created on
    test 1's already-closed loop. join_transaction_mode turns the app's own
    `session.commit()` calls into SAVEPOINTs nested inside this transaction
    instead of real commits, so nothing a test does is visible to another
    test or left behind in the database.
    """
    engine: AsyncEngine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.begin()
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                await session.close()
                await connection.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def raw_connection(environment_ready: None) -> AsyncIterator[asyncpg.Connection]:
    """A plain asyncpg connection for exercising app/db/raw/queries.py directly —
    the Phase 2 "without ORM" deliverable, independent of the SQLAlchemy session
    above. Wrapped in its own rolled-back transaction for the same isolation.
    """
    connection = await asyncpg.connect(_asyncpg_dsn())
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_db, None)
