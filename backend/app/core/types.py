"""Shared column types and mixins.

`Vector` degrades to a JSONB-backed column on SQLite (D-020) while remaining a
real `pgvector.vector` column on Postgres, so the production schema in
`DATA-MODEL.md` is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Text, TypeDecorator, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


class JSONBType(TypeDecorator):
    """JSONB on Postgres, JSON on SQLite, with the same Python surface."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        import json

        return json.dumps(value) if dialect.name != "postgresql" else value

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, str):
            import json

            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value


class VectorType(TypeDecorator):
    """`vector(EMBED_DIM)` on Postgres; JSON text on SQLite.

    Similarity search is implemented in `app.ai.vectorstore` against whichever
    backend is active, so no caller depends on this difference.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]

            return dialect.type_descriptor(Vector(settings.embed_dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        import json

        return json.dumps([float(v) for v in value])

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, str):
            import json

            try:
                return [float(v) for v in json.loads(value)]
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError):
            return None


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class Base(DeclarativeBase):
    """Declarative base for every table."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)