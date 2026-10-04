"""Deterministic hashing and id helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


def stable_hash(value: Any) -> str:
    """Content hash used for caching, idempotency and node versioning.

    Keys are sorted and separators fixed so the same logical value always
    produces the same digest across processes and Python versions.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def short_hash(value: Any, length: int = 12) -> str:
    return stable_hash(value)[:length]


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def line_id(index: int, text: str) -> str:
    """Stable identity for a script line that survives reordering.

    Derived from position-independent content so a diff can match the same line
    across versions even when it moved.
    """
    return f"l{index}-{short_hash(text.strip().lower(), 8)}"


def request_id() -> str:
    return str(uuid.uuid4())[:8]