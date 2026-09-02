import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Base class for application errors. Every error in this API -- ours or
    FastAPI's -- ends up serialized as {"error": {"code", "message", "details"}}
    so clients can rely on one consistent shape."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "bad_request"

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details
        super().__init__(message)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class GoneError(AppError):
    status_code = status.HTTP_410_GONE
    error_code = "gone"


class UnprocessableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "unprocessable"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limited"


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder(
                _error_body(
                    "validation_error",
                    "Request validation failed",
                    {"errors": exc.errors()},
                )
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Catch-all so a genuine bug or infra failure (e.g. a DB outage) still
        # returns the same {"error": {...}} shape as every other endpoint,
        # instead of falling through to FastAPI's default {"detail": ...}
        # response. The real exception is logged server-side but never sent
        # to the client, to avoid leaking internals.
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("internal_error", "An unexpected error occurred"),
        )
