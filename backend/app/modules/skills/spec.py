"""Skill specification (AI-ARCHITECTURE.md §3).

A skill is one folder with `schemas.py`, `prompt.md`, `validators.py` and
`skill.py`. Registering it must not require changes to the router, the workflow
engine or any template loader beyond adding the stage (D-006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

ImplStatus = Literal["real", "mocked", "stubbed", "future"]
Capability = Literal["text", "vision", "embedding", "stt", "none", "mixed"]

#: Capabilities a skill declares. `mixed` means it orchestrates sub-capabilities.
CAPABILITIES: frozenset[str] = frozenset(
    {"text", "vision", "embedding", "stt", "none", "mixed"}
)


@dataclass(frozen=True, slots=True)
class ModelRequirement:
    capability: Capability
    json_mode: bool = False
    min_context_tokens: int = 8_000
    temperature: float = 0.6

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "json_mode": self.json_mode,
            "min_context_tokens": self.min_context_tokens,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class SkillSpec:
    id: str
    name: str
    purpose: str
    input_schema: type[BaseModel] | None
    output_schema: type[BaseModel] | None
    model_requirements: ModelRequirement = field(
        default_factory=lambda: ModelRequirement(capability="none")
    )
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    failure_conditions: tuple[str, ...] = ()
    validation_rules: tuple[str, ...] = ()
    status: ImplStatus = "real"
    #: True when execution must happen in a worker rather than a request.
    async_job: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "purpose": self.purpose,
            "input_schema": (
                self.input_schema.__name__ if self.input_schema is not None else None
            ),
            "output_schema": (
                self.output_schema.__name__ if self.output_schema is not None else None
            ),
            "model_requirements": self.model_requirements.to_dict(),
            "dependencies": list(self.dependencies),
            "permissions": list(self.permissions),
            "failure_conditions": list(self.failure_conditions),
            "validation_rules": list(self.validation_rules),
            "status": self.status,
            "async_job": self.async_job,
        }


def validate_spec(spec: SkillSpec) -> None:
    """Fail fast on a malformed spec; called by the registry startup check."""
    if not spec.id or "." not in spec.id:
        raise ValueError(f"Skill id must be 'domain.action': {spec.id!r}")
    if spec.model_requirements.capability not in CAPABILITIES:
        raise ValueError(
            f"{spec.id}: unknown capability {spec.model_requirements.capability!r}"
        )
    if spec.input_schema is None and spec.model_requirements.capability != "none":
        raise ValueError(f"{spec.id}: capability skills need an input schema")
    if spec.status not in ("real", "mocked", "stubbed", "future"):
        raise ValueError(f"{spec.id}: invalid status {spec.status!r}")