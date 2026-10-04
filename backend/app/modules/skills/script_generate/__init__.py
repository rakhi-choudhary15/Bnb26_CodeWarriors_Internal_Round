"""Script generation skill package (registers `script.generate`)."""

from app.modules.skills.script_generate import validators as _validators  # noqa: F401
from app.modules.skills.script_generate.skill import (  # noqa: F401
    SPEC,
    ScriptGenerateSkill,
)

__all__ = ["SPEC", "ScriptGenerateSkill"]