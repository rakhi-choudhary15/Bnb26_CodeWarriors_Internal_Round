"""`hook.generate` schemas (AI-SKILLS.md: hooks[{text, style, score, reason}])."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Hook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3, max_length=200)
    style: str = Field(default="", max_length=40)
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)
    #: Spoken-length budget the validator enforces (AI-SKILLS.md: <=12 words).
    word_count: int = Field(default=0, ge=0)
    estimated_seconds: float = Field(default=0.0, ge=0.0)

    @field_validator("score")
    @classmethod
    def _round(cls, value: float) -> float:
        return round(value, 2)


class HookOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hooks: list[Hook] = Field(min_length=1, max_length=6)
    selected_index: int = Field(default=0, ge=0, le=5)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @property
    def selected(self) -> Hook | None:
        if 0 <= self.selected_index < len(self.hooks):
            return self.hooks[self.selected_index]
        return None
