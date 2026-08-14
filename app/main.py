from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(projects_router)
    return app


app = create_app()
