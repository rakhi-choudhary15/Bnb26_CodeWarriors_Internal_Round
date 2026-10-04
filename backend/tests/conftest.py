"""Shared test fixtures.

Skills are exercised through the same validation path the router uses, so a test
can never pass on output the API would reject.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway.base import ModelGateway, get_gateway
from app.core import db as db_module
from app.core.models import Base
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillResult
from app.modules.skills.router import apply_validation

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _stamp_head(engine: Engine) -> None:
    """Record the migration revision on a database built with `create_all`."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    raw_url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", raw_url)
    command.stamp(config, "head")


def _drain_jobs() -> None:
    """Let in-flight worker threads finish before the temp database disappears."""
    from app.core.jobs import get_queue

    queue = get_queue()
    if hasattr(queue, "drain_for_tests"):
        queue.drain_for_tests(timeout=10.0)  # type: ignore[attr-defined]


def _override_session(factory: sessionmaker[Session]):
    def _get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    return _get_db


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient bound to a throwaway SQLite file.

    The engine is rebuilt per test so no state leaks between them; Pydantic
    settings are frozen because `app.core.db` reads them at import time.
    """
    url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001 - SQLAlchemy hook signature
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", testing_session)
    monkeypatch.setattr(db_module, "engine", engine)
    Base.metadata.create_all(engine)
    # The lifespan runs real migrations on startup. Stamp this throwaway database
    # as being at head so that startup is a no-op instead of trying to create the
    # same tables a second time.
    _stamp_head(engine)

    from app.main import app

    # Re-resolve the dependency so routes use the patched session factory.
    app.dependency_overrides[db_module.get_db] = _override_session(testing_session)
    with TestClient(app) as test_client:
        yield test_client
    _drain_jobs()
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def gateway() -> ModelGateway:
    """The deterministic dev provider: no network, deterministic output."""
    return get_gateway()


@pytest.fixture
def make_ctx(gateway: ModelGateway):
    """Build a SkillContext whose `skill_id` matches the skill under test.

    `skill_id` is what the dev provider routes on (`[task:<id>]`), so it must be
    the real skill id or the provider cannot answer.
    """

    def factory(skill_id: str = "test", **context: Any) -> SkillContext:
        return SkillContext(
            owner_id=uuid.uuid4(),
            project_id=None,
            step_id=None,
            skill_id=skill_id,
            gateway=gateway,
            context=dict(context),
        )

    return factory


@pytest.fixture
def ctx(make_ctx) -> SkillContext:
    return make_ctx("test")


def context_holder(**context: Any):
    """A minimal stand-in for SkillContext when a rule is unit-tested directly."""
    return type("ContextHolder", (), {"context": dict(context)})()


def run_validated(skill_id: str, payload: Any, ctx: SkillContext) -> SkillResult:
    """Run a skill and apply its declared validators, as the router does."""
    module = registry.get_module(skill_id)
    assert module is not None, f"skill {skill_id} is not registered"
    result = module.run(payload, ctx)
    assert result.status == "ok", result.warnings
    validated, warnings = apply_validation(module.spec, result.output, ctx)
    return SkillResult(
        status="ok",
        output=validated,
        confidence=result.confidence,
        warnings=[*result.warnings, *warnings],
    )


def run_to_model(skill_id: str, payload: Any, ctx: SkillContext, model: Any):
    """Run a skill through validation and return its output as a Pydantic model."""
    result = run_validated(skill_id, payload, ctx)
    return model.model_validate(result.output)
