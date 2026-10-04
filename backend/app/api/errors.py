"""Error envelope and request-id middleware (API-SPECIFICATION.md §1, §Errors).

Every failure leaves the API as `{"error": {code, message, details, request_id}}`.
Stack traces are never returned; unexpected exceptions become a generic 500 with
the trace logged against the request id.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, RateLimitedError
from app.core.logging import get_logger, request_id_var

logger = get_logger(__name__)


def install(app: FastAPI) -> None:
    """Attach the request-id middleware and every exception handler."""
    app.middleware("http")(request_context)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Route a 404/405/... through the same envelope as everything else."""
    status_code = getattr(exc, "status_code", 500)
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHENTICATED"}.get(
        status_code, "HTTP_ERROR"
    )
    detail = getattr(exc, "detail", None) or "Request failed."
    if isinstance(detail, str) and status_code >= 500:
        # Never echo an internal explanation back to the client.
        logger.error("http %s on %s", status_code, request.url.path)
        detail = "Something went wrong on our side."
    return _envelope(AppError(str(detail), code=code, status_code=status_code), request)


async def request_context(request: Request, call_next):
    """Attach a request id and log the outcome of every call."""
    incoming = request.headers.get("x-request-id") or ""
    resolved = incoming[:64] if incoming else uuid.uuid4().hex
    request.state.request_id = resolved
    token = request_id_var.set(resolved)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # The user id is hashed, never logged raw (SECURITY.md §1).
    response.headers["x-request-id"] = resolved
    response.headers["x-response-time-ms"] = str(elapsed_ms)
    logger.info(
        "request",
        extra={
            "event": "http.request",
            "route": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": elapsed_ms,
        },
    )
    return response


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, AppError) else AppError(str(exc))
    if error.status_code >= 500:
        logger.error(
            "unhandled domain error",
            extra={"event": "http.error", "code": error.code, "path": request.url.path},
        )
    return _envelope(error, request)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic request errors become 422 with field paths the UI can highlight."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    details: dict[str, Any] = {
        "fields": [
            {
                "field": ".".join(str(part) for part in item.get("loc", [])[1:]) or "body",
                "message": str(item.get("msg", ""))[:200],
            }
            for item in errors[:20]
        ]
    }
    return _envelope(
        AppError(
            "Some fields need attention.",
            details=details,
            code="VALIDATION_ERROR",
            status_code=422,
        ),
        request,
    )


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # The driver's message can contain row values, so it is logged and not returned.
    logger.error(
        "database error on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _envelope(
        AppError(
            "The database could not complete this request.",
            code="DATABASE_ERROR",
            status_code=503,
        ),
        request,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", extra={"event": "http.unhandled"})
    return _envelope(
        AppError("Something went wrong on our side.", code="INTERNAL_ERROR", status_code=500),
        request,
    )


def _envelope(error: AppError, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"x-request-id": request_id} if request_id else {}
    if isinstance(error, RateLimitedError):
        headers["retry-after"] = str(error.details.get("retry_after_s", 60))
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_payload(request_id),
        headers=headers,
    )
