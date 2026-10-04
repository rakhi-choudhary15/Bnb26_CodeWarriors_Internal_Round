"""Clip candidate skill package (registers `clip.generate`)."""

from app.modules.skills.clip_generate import validators as _validators  # noqa: F401
from app.modules.skills.clip_generate.skill import SPEC, ClipGenerateSkill  # noqa: F401

__all__ = ["SPEC", "ClipGenerateSkill"]
