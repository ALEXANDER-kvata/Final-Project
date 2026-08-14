from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.detail


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Forbidden"


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Invalid request"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    detail = "Payload too large"


class StorageError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    detail = "Storage backend error"


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
