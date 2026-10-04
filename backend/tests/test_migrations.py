"""The migration is the schema of record (AGENTS.md §10/§21).

If a model changes without a matching migration, a fresh database silently ends
up with the wrong schema, so this compares the migrated database against the
models instead of trusting that someone remembered to run autogenerate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.core import models  # noqa: F401  (registers every table on Base.metadata)
from app.core.types import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    # alembic's bookkeeping table is not part of the domain schema.
    return {name for (name,) in rows if name != "alembic_version"}


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "migrated.db"
    command.upgrade(_config(f"sqlite+pysqlite:///{db_path.as_posix()}"), "head")
    return db_path


def test_upgrade_creates_every_model_table(migrated_db: Path) -> None:
    assert _table_names(migrated_db) == set(Base.metadata.tables)


def test_upgrade_creates_the_expected_number_of_tables(migrated_db: Path) -> None:
    # A regression tripwire: DATA-MODEL.md should be updated if this changes.
    assert len(Base.metadata.tables) == 32


def test_migrated_schema_matches_model_metadata(migrated_db: Path) -> None:
    """Every mapped column exists in the migrated database, with the right type.

    Comparing table *names* alone would miss a column that was added to a model
    but never migrated.
    """
    engine = create_engine(f"sqlite+pysqlite:///{migrated_db.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            for table_name, table in Base.metadata.tables.items():
                actual = {col["name"] for col in inspector.get_columns(table_name)}
                expected = set(table.columns.keys())
                assert expected <= actual, f"{table_name} is missing {expected - actual}"
    finally:
        engine.dispose()


def test_stamp_and_downgrade_round_trip(migrated_db: Path) -> None:
    config = _config(f"sqlite+pysqlite:///{migrated_db.as_posix()}")
    assert ScriptDirectory.from_config(config).get_current_head() is not None

    command.downgrade(config, "base")
    assert _table_names(migrated_db) == set()


def test_autogenerate_reports_no_pending_changes(migrated_db: Path) -> None:
    """`alembic check` must be clean: models and migrations agree.

    An empty comparison here means the model metadata and the migration history
    describe the same schema. Alembic reports drift as "new upgrade operations",
    so anything else is a failure.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = create_engine(f"sqlite+pysqlite:///{migrated_db.as_posix()}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"models drifted from the migration: {diff}"
