import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.projects import router as projects_router
from app.api.sharing import router as sharing_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.storage.s3_client import ensure_bucket

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        await ensure_bucket()
    except Exception:  # noqa: BLE001 - storage may be down; the API still serves other routes
        logger.warning("Could not verify the S3 bucket on startup", exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(documents_router)
    app.include_router(sharing_router)
    app.include_router(internal_router)
    return app


app = create_app()
