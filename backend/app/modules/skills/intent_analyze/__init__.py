"""Intent Engine skill package.

Importing the package registers `intent.analyze` and its validators, which is
how the registry discovers skills (AGENTS.md §11).
"""

from app.modules.skills.intent_analyze import validators as _validators  # noqa: F401
from app.modules.skills.intent_analyze.skill import (  # noqa: F401
    SPEC,
    IntentAnalyzeSkill,
)

__all__ = ["SPEC", "IntentAnalyzeSkill"]