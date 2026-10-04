"""`clip.generate` schemas (AI-SKILLS.md, VIDEO-PIPELINE.md §3).

`start_s`/`end_s` are always source-asset seconds so a candidate can be rendered
straight from the original asset without re-deriving offsets.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoreBreakdown(BaseModel):
    """The five documented score components, kept so the creator sees the why."""

    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    hook_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    visual_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    dna_fit: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def total(self) -> float:
        from app.core.config import settings

        return round(
            settings.clip_weight_relevance * self.relevance
            + settings.clip_weight_hook * self.hook_strength
            + settings.clip_weight_visual_quality * self.visual_quality
            + settings.clip_weight_completeness * self.completeness
            + settings.clip_weight_dna_fit * self.dna_fit,
            4,
        )


class ClipCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    asset_id: str = Field(min_length=1, max_length=64)
    #: Source-asset seconds, preserved from the original asset.
    start_s: float = Field(ge=0.0)
    end_s: float = Field(gt=0.0)
    reason: str = Field(default="", max_length=600)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    target_platform: str = "instagram_reels"
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    #: Set when the window was scored without speech evidence.
    visual_only: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> ClipCandidate:
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


class ClipGenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=64)
    duration_s: float = Field(gt=0.0)
    platform: str = "instagram_reels"
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    intent: str = ""
    reference_dna: dict[str, Any] = Field(default_factory=dict)


class ClipGenerateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    clips: list[ClipCandidate] = Field(default_factory=list)
    #: Windows considered before scoring; useful for diagnosing thin results.
    candidates_considered: int = Field(default=0, ge=0)
    visual_only: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @property
    def has_clips(self) -> bool:
        return bool(self.clips)
