"""Domain exceptions and the single API error envelope (API-SPECIFICATION.md).

Every failure path in the application raises one of these so the HTTP layer can
render `{error:{code,message,details,request_id}}` without leaking stack traces
(AGENTS.md §16).
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every error surfaced to a client."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_payload(self, request_id: str | None) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id,
            }
        }


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class UnauthenticatedError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"


class NotFoundError(AppError):
    """Ownership failures also surface as 404 so IDs cannot be enumerated."""

    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UnsupportedMediaError(AppError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA"


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class AIUnavailableError(AppError):
    status_code = 503
    code = "AI_UNAVAILABLE"


class AIOutputInvalidError(AppError):
    status_code = 502
    code = "AI_OUTPUT_INVALID"


class JobFailedError(AppError):
    status_code = 500
    code = "JOB_FAILED"


class CapabilityUnavailableError(AppError):
    """A required local binary or backing service is not installed.

    Used for ffmpeg/ffprobe absence (D-022) so the failure is explicit instead
    of silently producing empty results.
    """

    status_code = 503
    code = "CAPABILITY_UNAVAILABLE"


class PromptInjectionError(AppError):
    """Guard raised when untrusted input trips an injection heuristic."""

    status_code = 422
    code = "PROMPT_INJECTION"