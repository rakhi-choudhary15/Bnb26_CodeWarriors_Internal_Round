"""Intent Engine output schema (PRD FR-2, AI-ARCHITECTURE.md §2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.skills.platform_specs import get_spec

ContentType = Literal[
    "dance_video",
    "podcast",
    "product_ad",
    "educational_talk",
    "short_video",
    "long_video",
    "social_post",
    "carousel",
    "generic",
]

Platform = Literal[
    "instagram_reels",
    "youtube_shorts",
    "tiktok",
    "youtube",
    "linkedin",
    "other",
]


class FieldConfidence(BaseModel):
    """Per-field confidence, displayed but not trusted blindly (AI-ARCH §8)."""

    model_config = ConfigDict(extra="forbid")

    content_type: float = Field(default=0.5, ge=0.0, le=1.0)
    platform: float = Field(default=0.5, ge=0.0, le=1.0)
    duration_s: float = Field(default=0.5, ge=0.0, le=1.0)
    tone: float = Field(default=0.5, ge=0.0, le=1.0)
    style: float = Field(default=0.5, ge=0.0, le=1.0)
    audience: float = Field(default=0.5, ge=0.0, le=1.0)
    overall: float = Field(default=0.5, ge=0.0, le=1.0)


class CreationIntent(BaseModel):
    """Structured understanding of what the creator wants to make."""

    model_config = ConfigDict(extra="forbid")

    #: The creator's own words. Structured fields describe the brief; this is the
    #: brief. Downstream skills write copy, so without it they can only produce
    #: generic filler about "your idea" instead of the actual subject.
    primary_text: str = Field(default="", max_length=500)
    details_text: str | None = Field(default=None, max_length=1000)
    content_type: ContentType = "generic"
    custom_label: str | None = None
    format: str = "video"
    platform: Platform = "instagram_reels"
    duration_s: int = Field(default=30, ge=3, le=43200)
    tone: list[str] = Field(default_factory=list, max_length=6)
    style: list[str] = Field(default_factory=list, max_length=6)
    audience: str = "general audience"
    required_assets: list[str] = Field(default_factory=list, max_length=12)
    required_skills: list[str] = Field(default_factory=list, max_length=40)
    stages: list[str] = Field(default_factory=list, max_length=40)
    expected_output: str = ""
    confidence: FieldConfidence = Field(default_factory=FieldConfidence)
    assumptions: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("tone", "style", mode="before")
    @classmethod
    def _dedupe_tags(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        seen: list[str] = []
        for item in value:
            tag = str(item).strip().lower()
            if tag and tag not in seen:
                seen.append(tag)
        return seen

    def apply_platform_limits(self) -> CreationIntent:
        """Rule-based post-processing: clamp duration to the platform (AI-ARCH §2)."""
        spec = get_spec(self.platform)
        clamped = max(spec.min_duration_s, min(self.duration_s, spec.max_duration_s))
        if clamped != self.duration_s:
            self.duration_s = clamped
            self.assumptions.append(
                f"Duration clamped to {clamped}s for {spec.label} (limit {spec.max_duration_s}s)."
            )
            self.confidence.duration_s = min(self.confidence.duration_s, 0.6)
        return self

    def template_hint(self) -> str:
        """Template selection key (AI-ARCHITECTURE.md §2 workflow selection)."""
        return self.content_type


class IntentAnalyzeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_text: str = Field(min_length=5, max_length=500)
    details_text: str | None = Field(default=None, max_length=1000)
    creator_dna: dict[str, Any] | None = None


class IntentAnalyzeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: ContentType = "generic"
    custom_label: str | None = None
    format: str = "video"
    platform: Platform = "instagram_reels"
    duration_s: int = 30
    tone: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    audience: str = "general audience"
    required_assets: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    expected_output: str = ""
    confidence: FieldConfidence = Field(default_factory=FieldConfidence)
    assumptions: list[str] = Field(default_factory=list)
    #: AI-SKILLS.md §3: every skill output carries confidence and warnings.
    warnings: list[str] = Field(default_factory=list)

    def to_intent(self) -> CreationIntent:
        return CreationIntent.model_validate(
            {k: v for k, v in self.model_dump().items() if k != "warnings"}
        )