"""Platform adaptation skill package (registers `platform.adapt`)."""

from app.modules.skills.platform_adapt import validators as _validators  # noqa: F401
from app.modules.skills.platform_adapt.skill import (  # noqa: F401
    SPEC,
    PlatformAdaptSkill,
)

__all__ = ["SPEC", "PlatformAdaptSkill"]