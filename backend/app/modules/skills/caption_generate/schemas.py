"""`caption.generate` schemas (AI-SKILLS.md: captions/title/description/hashtags)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CaptionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    caption: str = Field(default="", max_length=5000)
    description: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    thumbnail_text: str = Field(default="", max_length=80)
    platform: str = "instagram_reels"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
