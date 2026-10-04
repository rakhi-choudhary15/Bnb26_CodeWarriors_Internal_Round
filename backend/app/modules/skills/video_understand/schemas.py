"""`video.understand` schemas (AI-SKILLS.md: video -> scenes[{start,end,caption,tags,quality}]).

Scene *boundaries* are always produced by the deterministic detector in the
worker, never by the model. Only captions and tags come from a vision call, so
an unavailable vision provider degrades to empty captions instead of invented
times.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Vision capability is reported honestly so the UI can badge the scenes.
VisionStatus = Literal["real", "mocked", "unavailable"]


class SceneQuality(BaseModel):
    """Deterministic OpenCV metrics for one scene (VIDEO-PIPELINE.md §2)."""

    model_config = ConfigDict(extra="forbid")

    #: 0..1 Laplacian variance, normalised against the asset's own mean.
    sharpness: float = Field(default=0.5, ge=0.0, le=1.0)
    brightness: float = Field(default=0.5, ge=0.0, le=1.0)
    motion: float = Field(default=0.0, ge=0.0, le=1.0)
    #: 0..1 combined visual quality used by `clip.generate` scoring.
    score: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def usable(self) -> bool:
        """Reject unusable footage before it is ever proposed as a clip."""
        return self.score >= 0.15


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Seconds relative to the original asset (never timeline time).
    start_s: float = Field(ge=0.0)
    end_s: float = Field(gt=0.0)
    caption: str = ""
    tags: list[str] = Field(default_factory=list)
    quality: SceneQuality = Field(default_factory=SceneQuality)

    @model_validator(mode="after")
    def _ordered(self) -> Scene:
        if self.end_s <= self.start_s:
            raise ValueError("scene end_s must be greater than start_s")
        return self

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


class UnderstandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=64)
    duration_s: float = Field(gt=0.0)
    #: Deterministic scene boundaries from the detector. Required: the model is
    #: never allowed to decide where a scene starts.
    detected_scenes: list[dict[str, Any]] = Field(default_factory=list)
    #: True when the audio has no speech, which changes downstream scoring.
    has_speech: bool = True


class VideoUnderstandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    scenes: list[Scene] = Field(default_factory=list)
    #: Frame cap actually honoured (VIDEO-PIPELINE.md §1).
    frames_analyzed: int = Field(default=0, ge=0)
    #: Honest report of how the captions were produced.
    vision_status: VisionStatus = "unavailable"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @property
    def has_captions(self) -> bool:
        return any(scene.caption.strip() for scene in self.scenes)

    @property
    def duration_s(self) -> float:
        return round(sum(scene.duration_s for scene in self.scenes), 3)
