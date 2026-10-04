"""Platform specifications (API-SPECIFICATION.md, AI-SKILLS.md `platform.adapt`).

Single source of truth for aspect, duration and text limits. `platform.adapt`
validates against this table, so an unsupported platform is rejected rather than
invented (AI-SKILLS.md key failure condition).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import ValidationError


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    key: str
    label: str
    aspect: str
    width: int
    height: int
    max_duration_s: int
    min_duration_s: int
    caption_chars: int
    title_chars: int
    hashtag_limit: int
    hook_window_s: float
    #: AI-SKILLS.md / MVP-SCOPE: Reels is REAL; the rest are MOCKED metadata output.
    impl_status: str
    render_capable: bool
    notes: str = ""
    safe_area_pct: float = 0.12
    tone_hint: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


PLATFORMS: dict[str, PlatformSpec] = {
    "instagram_reels": PlatformSpec(
        key="instagram_reels",
        label="Instagram Reels",
        aspect="9:16",
        width=1080,
        height=1920,
        max_duration_s=90,
        min_duration_s=3,
        caption_chars=2200,
        title_chars=0,
        hashtag_limit=30,
        hook_window_s=3.0,
        impl_status="real",
        render_capable=True,
        notes="Hook in first 3s, captions burned in for sound-off viewing.",
        tone_hint="punchy",
        tags=("reels", "trending audio ok"),
    ),
    "youtube_shorts": PlatformSpec(
        key="youtube_shorts",
        label="YouTube Shorts",
        aspect="9:16",
        width=1080,
        height=1920,
        max_duration_s=60,
        min_duration_s=3,
        caption_chars=1000,
        title_chars=100,
        hashtag_limit=15,
        hook_window_s=2.0,
        impl_status="mocked",
        render_capable=False,
        notes="Tighter hook than Reels; loop-friendly ending.",
        tone_hint="direct",
    ),
    "tiktok": PlatformSpec(
        key="tiktok",
        label="TikTok",
        aspect="9:16",
        width=1080,
        height=1920,
        max_duration_s=600,
        min_duration_s=3,
        caption_chars=2200,
        title_chars=0,
        hashtag_limit=20,
        hook_window_s=2.0,
        impl_status="mocked",
        render_capable=False,
        notes="Longer form allowed; captions and on-screen text drive watch time.",
        tone_hint="native",
    ),
    "youtube": PlatformSpec(
        key="youtube",
        label="YouTube",
        aspect="16:9",
        width=1920,
        height=1080,
        max_duration_s=43200,
        min_duration_s=30,
        caption_chars=5000,
        title_chars=100,
        hashtag_limit=15,
        hook_window_s=15.0,
        impl_status="mocked",
        render_capable=False,
        notes="Longer hook window; chaptered structure pays off.",
        tone_hint="substantive",
    ),
    "linkedin": PlatformSpec(
        key="linkedin",
        label="LinkedIn",
        aspect="1:1",
        width=1080,
        height=1080,
        max_duration_s=600,
        min_duration_s=5,
        caption_chars=3000,
        title_chars=200,
        hashtag_limit=10,
        hook_window_s=5.0,
        impl_status="mocked",
        render_capable=False,
        notes="Text-first: the caption carries the argument, video supports it.",
        tone_hint="professional",
    ),
    "other": PlatformSpec(
        key="other",
        label="Other",
        aspect="16:9",
        width=1920,
        height=1080,
        max_duration_s=600,
        min_duration_s=3,
        caption_chars=2000,
        title_chars=140,
        hashtag_limit=10,
        hook_window_s=5.0,
        impl_status="mocked",
        render_capable=False,
    ),
}

SUPPORTED_PLATFORMS: tuple[str, ...] = tuple(PLATFORMS)


def get_spec(platform: str) -> PlatformSpec:
    key = (platform or "").strip().lower()
    spec = PLATFORMS.get(key)
    if spec is None:
        raise ValidationError(
            "Unsupported platform.",
            details={"platform": platform, "supported": list(SUPPORTED_PLATFORMS)},
        )
    return spec


def clamp_duration(platform: str, seconds: float) -> float:
    spec = get_spec(platform)
    return round(max(spec.min_duration_s, min(float(seconds), spec.max_duration_s)), 2)


def all_specs() -> list[PlatformSpec]:
    return list(PLATFORMS.values())