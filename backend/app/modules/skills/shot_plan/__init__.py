"""Shot planning skill package (registers `shot.plan`)."""

from app.modules.skills.shot_plan import validators as _validators  # noqa: F401
from app.modules.skills.shot_plan.skill import SPEC, ShotPlanSkill  # noqa: F401

__all__ = ["SPEC", "ShotPlanSkill"]