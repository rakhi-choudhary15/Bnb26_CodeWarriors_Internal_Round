"""Caption generation skill package (registers `caption.generate`)."""

from app.modules.skills.caption_generate import validators as _validators  # noqa: F401
from app.modules.skills.caption_generate.skill import (  # noqa: F401
    SPEC,
    CaptionGenerateSkill,
)

__all__ = ["SPEC", "CaptionGenerateSkill"]