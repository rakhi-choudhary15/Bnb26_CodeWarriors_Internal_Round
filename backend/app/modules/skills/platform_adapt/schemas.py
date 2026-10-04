"""`platform.adapt` schemas (AI-SKILLS.md: node, platforms -> variants).

Per MVP-SCOPE only Instagram Reels is REAL; the rest are MOCKED metadata
variants. Each variant therefore carries its own status so the UI can badge it
without consulting a separate table.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PlatformVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    label: str = ""
    aspect: str = "9:16"
    width: int = 1080
    height: int = 1920
    duration_s: float = Field(default=0.0, ge=0.0)
    title: str = Field(default="", max_length=200)
    caption: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    #: Honest implementation status of this platform (AI-SKILLS.md MVP column).
    impl_status: str = "mocked"
    render_capable: bool = False
    #: Editor instructions required to reframe the master cut, not applied here.
    reframe_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlatformAdaptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variants: list[PlatformVariant] = Field(min_length=1, max_length=6)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    def for_platform(self, platform: str) -> PlatformVariant | None:
        for variant in self.variants:
            if variant.platform == platform:
                return variant
        return None
