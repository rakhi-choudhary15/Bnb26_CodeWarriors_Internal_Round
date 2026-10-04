"""Health routes (API-SPECIFICATION.md §Intelligence).

`/api/health` is the only unauthenticated route. It reports what is *actually*
wired up — no green checks on services that are merely configured — because the
demo has to be able to say which parts are real.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.media.probe import ffmpeg_available, ffprobe_available, unavailable_reason
from app.modules.skills.registry import list_specs

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: DbSession) -> dict[str, Any]:
    """Unauthenticated liveness plus a truthful capability report."""
    database_ok, database_detail = _database_status(db)
    registered = list_specs()
    missing_media = _missing_media()
    degraded = not database_ok or bool(missing_media)
    return {
        "status": "degraded" if degraded else "ok",
        "service": settings.app_env,
        "demo_mode": settings.demo_mode,
        "database": {
            "ok": database_ok,
            "dialect": db.bind.dialect.name if db.bind is not None else "unknown",
            "detail": database_detail,
        },
        "queue": {
            "backend": settings.queue_backend,
            "workers": settings.queue_workers,
            "note": "auto falls back to in-process threads when Redis is unreachable (D-021)",
        },
        "media": {
            "ok": not missing_media,
            "ffprobe": ffprobe_available(),
            "ffmpeg": ffmpeg_available(),
            "missing": missing_media,
        },
        "skills": {
            "registered": len(registered),
            "real": sum(1 for s in registered if s.status == "real"),
            "mocked": sum(1 for s in registered if s.status == "mocked"),
            "stubbed": sum(1 for s in registered if s.status in ("stubbed", "future")),
        },
    }


def _missing_media() -> list[str]:
    """Names the binaries that are absent, or empty when media work can run.

    `unavailable_reason` is the authoritative explanation and is preferred when it
    knows something the `which` checks do not.
    """
    reason = unavailable_reason()
    if reason:
        return [reason]
    missing: list[str] = []
    if not ffprobe_available():
        missing.append("ffprobe")
    if not ffmpeg_available():
        missing.append("ffmpeg")
    return missing


def _database_status(db: DbSession) -> tuple[bool, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - reported, never raised from /health
        logger.warning("health: database unreachable (%s)", type(exc).__name__)
        return False, type(exc).__name__
    return True, "ok"
