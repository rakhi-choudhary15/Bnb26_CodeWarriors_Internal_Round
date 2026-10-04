"""`concept.generate` schemas (AI-SKILLS.md: intent → 3 concepts {title, premise, why}).

Deliberately close to the documented contract. The service layer assigns node ids
for the genome graph; a skill must not invent identifiers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Concept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=4, max_length=120)
    premise: str = Field(min_length=8, max_length=400)
    why: str = Field(default="", max_length=400)
    #: Optional label of the attention mechanism, e.g. "before_after".
    angle: str = Field(default="", max_length=40)
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Cleared by the validator when the concept is a near-duplicate.
    distinct: bool = True

    @field_validator("score")
    @classmethod
    def _round(cls, value: float) -> float:
        return round(value, 2)

    def embedding_text(self) -> str:
        """Text used for the distinctness check (AI-SKILLS.md: sim < 0.9)."""
        return f"{self.title}. {self.premise}"


class ConceptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concepts: list[Concept] = Field(min_length=1, max_length=6)
    selected_index: int = Field(default=0, ge=0, le=5)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @property
    def selected(self) -> Concept | None:
        if 0 <= self.selected_index < len(self.concepts):
            return self.concepts[self.selected_index]
        return None
