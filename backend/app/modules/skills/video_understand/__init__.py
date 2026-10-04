"""Footage understanding skill package (registers `video.understand`)."""

from app.modules.skills.video_understand import validators as _validators  # noqa: F401
from app.modules.skills.video_understand.skill import (  # noqa: F401
    SPEC,
    VideoUnderstandSkill,
)

__all__ = ["SPEC", "VideoUnderstandSkill"]
