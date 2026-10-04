"""Skill registry (AI-ARCHITECTURE.md §3).

Registration happens by import side effect. `load_all_skills()` imports every
skill module; the startup check then asserts that all template skill ids exist
(WORKFLOW-ENGINE.md §5).
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.core.errors import ValidationError
from app.modules.skills.spec import SkillSpec, validate_spec

if TYPE_CHECKING:
    from app.modules.skills.base import SkillModule

_REGISTRY: dict[str, SkillSpec] = {}
_MODULES: dict[str, SkillModule] = {}


def register(spec: SkillSpec, module_factory: Callable[[], SkillModule]) -> SkillModule:
    """Register a skill. `module_factory` returns the object with `run()`."""
    validate_spec(spec)
    if spec.id in _REGISTRY:
        raise ValueError(f"Duplicate skill registration: {spec.id}")
    _REGISTRY[spec.id] = spec
    instance = module_factory()
    _MODULES[spec.id] = instance
    return instance


def get_spec(skill_id: str) -> SkillSpec:
    spec = _REGISTRY.get(skill_id)
    if spec is None:
        raise ValidationError(
            "Unknown skill.",
            details={"skill_id": skill_id, "known": sorted(_REGISTRY)},
        )
    return spec


def get_module(skill_id: str) -> SkillModule:
    load_all_skills()
    module = _MODULES.get(skill_id)
    if module is None:
        raise ValidationError(
            "Skill is registered but has no implementation.",
            details={"skill_id": skill_id},
        )
    return module


def has_skill(skill_id: str) -> bool:
    load_all_skills()
    return skill_id in _REGISTRY


def list_specs() -> list[SkillSpec]:
    load_all_skills()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def skill_ids() -> set[str]:
    load_all_skills()
    return set(_REGISTRY)


def status_map() -> dict[str, str]:
    """id -> status, used to stamp `impl_status` onto workflow steps (D-018)."""
    return {spec.id: spec.status for spec in list_specs()}


_loaded = False


def load_all_skills() -> None:
    """Import every skill package exactly once."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.modules import skills as skills_pkg

    for info in pkgutil.iter_modules(skills_pkg.__path__):
        if info.name.startswith("_") or info.name == "tests":
            continue
        importlib.import_module(f"{skills_pkg.__name__}.{info.name}")


def reset_for_tests() -> None:
    global _loaded, _REGISTRY, _MODULES
    _REGISTRY = {}
    _MODULES = {}
    _loaded = False