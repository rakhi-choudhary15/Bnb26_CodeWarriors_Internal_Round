"""Shared FastAPI dependencies (API-SPECIFICATION.md §1).

Everything a route needs to identify a caller, a request and a transaction is
resolved here, so no route re-implements ownership, idempotency or rate limits.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.auth import CurrentPrincipal, enforce_rate_limit, get_principal
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import ValidationError

DbSession = Annotated[Session, Depends(get_db)]


async def current_owner_id(principal: CurrentPrincipal) -> uuid.UUID:
    """The caller as an id.

    Routes and services deal in `uuid.UUID`, never in auth objects: ownership is
    a data question, identity is a transport concern (AGENTS.md §8).
    """
    return principal.owner_id


CurrentOwner = Annotated[uuid.UUID, Depends(current_owner_id)]


async def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """The client-supplied key for an expensive POST, if any.

    Absent is fine: the job service falls back to an owner-scoped content hash,
    which gives the same de-duplication for an accidental double-click.
    """
    if key is None:
        return ""
    cleaned = key.strip()
    if len(cleaned) > 200:
        raise ValidationError("Idempotency-Key is too long.", details={"max_length": 200})
    return cleaned


IdempotencyKey = Annotated[str, Depends(idempotency_key)]


def general_rate_limit(owner_id: CurrentOwner) -> None:
    """60 req/min per creator (API-SPECIFICATION.md §Conventions)."""
    enforce_rate_limit(f"general:{owner_id}", settings.rate_limit_general, "API")


def ai_rate_limit(owner_id: CurrentOwner) -> None:
    """10 req/min on routes that spend a model call."""
    enforce_rate_limit(f"ai:{owner_id}", settings.rate_limit_ai, "AI")


def upload_rate_limit(owner_id: CurrentOwner) -> None:
    """20 upload reservations per hour per creator."""
    enforce_rate_limit(f"upload:{owner_id}", settings.rate_limit_uploads_per_hour, "upload")


GeneralRateLimit = Annotated[None, Depends(general_rate_limit)]
AiRateLimit = Annotated[None, Depends(ai_rate_limit)]
UploadRateLimit = Annotated[None, Depends(upload_rate_limit)]


def request_id(request: Request) -> str:
    """Correlation id for this request, echoed in every response and error."""
    return getattr(request.state, "request_id", "") or ""


RequestId = Annotated[str, Depends(request_id)]


__all__ = [
    "AiRateLimit",
    "CurrentOwner",
    "CurrentPrincipal",
    "DbSession",
    "GeneralRateLimit",
    "IdempotencyKey",
    "RequestId",
    "UploadRateLimit",
    "get_principal",
]
