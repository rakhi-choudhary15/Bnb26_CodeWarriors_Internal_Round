"""SQLAlchemy engine/session wiring.

D-020: the documented target is Supabase Postgres. When no Postgres server is
reachable the same models run against SQLite so development, tests and the demo
remain executable. Ownership scoping in repositories is enforced in Python in
both cases; Postgres additionally enforces it with RLS.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.core.types import Base

logger = get_logger(__name__)


def _build_engine() -> Engine:
    kwargs: dict[str, object] = {"echo": settings.database_echo, "future": True}
    if settings.is_sqlite:
        # check_same_thread=False is required by the threaded job queue.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    engine = create_engine(settings.database_url, **kwargs)
    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for workers, scripts and tests."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def migrate_to_head() -> str:
    """Bring the configured database up to the latest Alembic revision.

    Alembic owns the schema on every dialect (AGENTS.md §10/§21). This runs
    programmatically so `uvicorn app.main:app` needs no separate migration step,
    which is what makes the demo path work from a clean checkout.

    A database that holds tables but carries no Alembic revision is refused rather
    than migrated: those tables came from `create_all` or an older schema, so the
    only safe next step is a decision by whoever owns the data.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(ini_path.parent / "migrations"))
    # Take the URL from the engine rather than from settings: the engine is what
    # every session will actually use, so this can never migrate a different
    # database than the app talks to (tests swap the engine for a temporary file).
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current = context.get_current_heads()
        if not current:
            inspector = inspect(connection)
            unmanaged = sorted(set(inspector.get_table_names()) - {"alembic_version"})
            if unmanaged:
                raise RuntimeError(
                    f"{settings.database_url} already has {len(unmanaged)} table(s) "
                    f"(for example {unmanaged[:3]}) but no Alembic revision, so the "
                    "schema cannot be migrated safely. Run `alembic stamp head` if it "
                    "already matches the models, or delete the file to rebuild it."
                )

    head = ScriptDirectory.from_config(config).get_current_head()
    if current == head:
        return "current" if current else "empty"

    command.upgrade(config, "head")
    return "migrated"


def create_all() -> None:
    """Create the schema directly, without Alembic.

    Only for tests, which need a throwaway schema per test session. Anything that
    persists data must use `migrate_to_head()`, because Alembic is the migration
    of record and `create_all` cannot express a data backfill.
    """
    # Import for side-effect: models register themselves on Base.metadata.
    from app.core import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    from app.core import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)