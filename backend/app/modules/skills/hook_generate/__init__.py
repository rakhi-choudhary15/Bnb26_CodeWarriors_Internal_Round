"""Hook generation skill package (registers `hook.generate`)."""

from app.modules.skills.hook_generate import validators as _validators  # noqa: F401
from app.modules.skills.hook_generate.skill import SPEC, HookGenerateSkill  # noqa: F401

__all__ = ["SPEC", "HookGenerateSkill"]