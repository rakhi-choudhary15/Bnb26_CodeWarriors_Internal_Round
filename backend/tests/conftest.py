"""Shared test fixtures.

Skills are exercised through the same validation path the router uses, so a test
can never pass on output the API would reject.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.ai.gateway.base import ModelGateway, get_gateway
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillResult
from app.modules.skills.router import apply_validation


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
