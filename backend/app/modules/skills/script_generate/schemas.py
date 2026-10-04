"""`script.generate` schemas (AI-SKILLS.md: lines[{beat,text,kind}], cta)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Beat = Literal["hook", "setup", "problem", "build", "payoff", "proof", "cta", "bridge"]
LineKind = Literal["line", "b_roll", "caption", "cta"]


class ScriptLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat: Beat = "line"
    text: str = Field(default="", max_length=400)
    kind: LineKind = "line"
    estimated_seconds: float = Field(default=0.0, ge=0.0)
    #: Optional visual direction; never a timestamp, the model cannot measure.
    visual: str = Field(default="", max_length=300)


class ScriptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=140)
    lines: list[ScriptLine] = Field(default_factory=list, max_length=60)
    cta: str = Field(default="", max_length=200)
    target_duration_s: float = Field(default=30.0, gt=0.0)
    estimated_duration_s: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        return value.strip()

    @property
    def duration_drift(self) -> float:
        if self.target_duration_s <= 0:
            return 0.0
        return abs(self.estimated_duration_s - self.target_duration_s) / self.target_duration_s

    @property
    def spoken_lines(self) -> list[ScriptLine]:
        return [line for line in self.lines if line.kind in ("line", "cta") and line.text.strip()]
