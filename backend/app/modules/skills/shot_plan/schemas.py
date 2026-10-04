"""`shot.plan` schemas (AI-SKILLS.md: script, intent, Reference DNA -> shots[])."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    framing: str = Field(default="", max_length=40)
    distance_m: float | None = Field(default=None, ge=0.0)
    camera_height: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=200)
    background: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=400)
    #: Set by the validator; the plan is only usable once shots are contiguous.
    contiguous: bool = True

    @property
    def duration_s(self) -> float:
        return round(max(0.0, self.end_s - self.start_s), 2)


class ShotPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shots: list[Shot] = Field(min_length=1, max_length=40)
    total_duration_s: float = Field(default=0.0, ge=0.0)
    target_duration_s: float = Field(default=30.0, gt=0.0)
    #: Populated for `recording.coach`, which consumes this output.
    checklist: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
