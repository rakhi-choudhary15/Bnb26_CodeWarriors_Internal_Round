"""Repository for creation intents (AGENTS.md §8).

All reads are owner-scoped. A row owned by someone else is reported as missing,
never as forbidden, so IDs cannot be enumerated (SECURITY.md §1).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.models import CreationIntent


def create(
    db: Session,
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID,
    primary_text: str,
    details_text: str | None,
    parsed: dict[str, Any],
    confidence: dict[str, Any],
    parse_status: str,
    fallback: bool,
) -> CreationIntent:
    intent = CreationIntent(
        owner_id=owner_id,
        project_id=project_id,
        primary_text=primary_text[:500],
        details_text=details_text,
        parsed=parsed,
        confidence=confidence,
        parse_status=parse_status,
        fallback=fallback,
    )
    db.add(intent)
    db.flush()
    return intent


def get(db: Session, *, owner_id: uuid.UUID, intent_id: uuid.UUID | str) -> CreationIntent:
    resolved = _uuid(intent_id, "intent_id")
    intent = db.execute(
        select(CreationIntent).where(
            CreationIntent.id == resolved, CreationIntent.owner_id == owner_id
        )
    ).scalar_one_or_none()
    if intent is None:
        raise NotFoundError("Intent not found.", details={"intent_id": str(resolved)})
    return intent


def update(
    db: Session,
    *,
    owner_id: uuid.UUID,
    intent_id: uuid.UUID | str,
    changes: dict[str, Any],
) -> CreationIntent:
    """Apply a creator's edits to the parsed intent.

    A human edit always wins over the model's parse, and the row is flagged
    `user_edited` so downstream stages stop second-guessing it.
    """
    intent = get(db, owner_id=owner_id, intent_id=intent_id)
    parsed = {**(intent.parsed or {}), **changes.get("parsed", {})}
    intent.parsed = parsed
    if "confidence" in changes:
        intent.confidence = changes["confidence"]
    if changes.get("primary_text"):
        intent.primary_text = str(changes["primary_text"])[:500]
    if "details_text" in changes:
        intent.details_text = changes["details_text"]
    intent.user_edited = True
    intent.parse_status = "ready"
    db.add(intent)
    db.flush()
    return intent


def latest_for_project(db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID) -> CreationIntent | None:
    return db.execute(
        select(CreationIntent)
        .where(CreationIntent.owner_id == owner_id, CreationIntent.project_id == project_id)
        .order_by(CreationIntent.created_at.desc())
    ).scalars().first()


def _uuid(value: uuid.UUID | str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFoundError("Intent not found.", details={"field": field}) from exc
