"""Authentication and ownership (SECURITY.md §1).

Two modes behind one dependency:

* ``supabase`` — verifies the Supabase-issued JWT (HS256 shared secret or RS256
  JWKS) and extracts ``sub`` as the owner id. This is the production path.
* ``dev`` — no Supabase project is configured, so the API accepts a caller-
  supplied identity. Every response still flows through the same ownership
  scoping; only the *proof* of identity is weaker, and the mode is surfaced on
  ``/api/health`` so it can never be mistaken for production auth.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.core.config import settings
from app.core.errors import UnauthenticatedError

bearer_scheme = HTTPBearer(auto_error=False)

DEV_OWNER_HEADER = "x-dev-user-id"
DEV_OWNER_FALLBACK = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True, slots=True)
class Principal:
    owner_id: uuid.UUID
    email: str | None = None
    mode: str = "dev"


def _as_owner_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise UnauthenticatedError(
            "Identity is not a valid UUID.",
            details={"hint": "expected a UUID subject"},
        ) from exc


def _verify_supabase_token(token: str) -> Principal:
    """Verify signature, expiry and audience per SECURITY.md §1."""
    if not settings.supabase_service_key:
        raise UnauthenticatedError(
            "Supabase is not configured on this deployment.",
            details={"auth_mode": settings.auth_mode},
        )
    unverified = jwt.get_unverified_header(token)
    algorithm = str(unverified.get("alg") or "")
    if algorithm == "RS256":
        # Newer Supabase projects sign with a project key pair; the public keys
        # come from the project's JWKS endpoint and are cached by PyJWT. Using the
        # service-role secret here would silently reject every valid RS256 token.
        secret: str | object = _jwks_key(token, algorithm)
        algorithms = ["RS256"]
    elif algorithm == "HS256":
        secret = settings.supabase_service_key
        algorithms = ["HS256"]
    else:
        # `alg: none` and anything unexpected must never reach verification.
        raise UnauthenticatedError(
            "Unsupported token algorithm.", details={"algorithm": algorithm[:32]}
        )
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=algorithms,
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Session expired. Sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError("Invalid authentication token.") from exc

    return Principal(
        owner_id=_as_owner_id(str(claims["sub"])),
        email=claims.get("email"),
        mode="supabase",
    )


def _jwks_key(token: str, algorithm: str) -> Any:
    """Resolve the signing key from the Supabase JWKS, caching it per project.

    A new signing key is fetched rather than cached forever, so a key rotation
    does not lock every user out until the process restarts.
    """
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        jwks_client = PyJWKClient(url, cache_keys=True, lifespan=300)
        return jwks_client.get_signing_key_from_jwt(token).key
    except PyJWKClientError as exc:
        # The URL is derived from configuration, never from the token, so this
        # cannot be used to make the server fetch an attacker-chosen address.
        raise UnauthenticatedError(
            "Could not verify the signing key.", details={"algorithm": algorithm}
        ) from exc


def _verify_dev_identity(request: Request, token: str | None) -> Principal:
    """Development identity.

    A bearer token of the form ``dev:<uuid>`` is accepted, as is the
    ``X-Dev-User-Id`` header. Both are explicit opt-in; an anonymous call falls
    back to a fixed demo owner so a fresh checkout is immediately usable.
    """
    candidate = None
    if token and token.startswith("dev:"):
        candidate = token[4:]
    if not candidate:
        candidate = request.headers.get(DEV_OWNER_HEADER)
    if not candidate:
        candidate = settings.demo_owner_id if settings.demo_mode else DEV_OWNER_FALLBACK
    return Principal(owner_id=_as_owner_id(candidate), mode="dev")


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    if settings.auth_mode == "supabase":
        if credentials is None:
            raise UnauthenticatedError("Missing bearer token.")
        return _verify_supabase_token(credentials.credentials)
    return _verify_dev_identity(request, credentials.credentials if credentials else None)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def owner_filter(query, model, principal: Principal):  # type: ignore[no-untyped-def]
    """Apply the ownership scope every repository query must carry."""
    return query.filter(model.owner_id == principal.owner_id)


class DevOwner:
    """FastAPI dependency returning the raw owner id."""

    def __init__(self, principal: Principal) -> None:
        self.owner_id = principal.owner_id
        self.email = principal.email
        self.mode = principal.mode


async def get_current_owner(principal: CurrentPrincipal) -> DevOwner:
    return DevOwner(principal)


CurrentOwner = Annotated[DevOwner, Depends(get_current_owner)]


class SlidingWindowLimiter:
    """In-process sliding-window limiter (SECURITY.md §9).

    Redis is the documented backend; this is the fallback used when no Redis
    server is configured, preserving identical semantics per process.
    """

    def __init__(self, window_s: int = 60) -> None:
        self.window_s = window_s
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_s
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        if len(hits) >= limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


_limiter = SlidingWindowLimiter()


def enforce_rate_limit(key: str, limit: int, scope: str) -> None:
    from app.core.errors import RateLimitedError

    if not _limiter.allow(key, limit):
        raise RateLimitedError(
            f"Too many {scope} requests. Please slow down.",
            details={"limit": limit, "window_s": _limiter.window_s},
        )