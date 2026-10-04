"""`platform.adapt` validators (AI-SKILLS.md: "unsupported platform -> spec table").

The spec table is authoritative. A model may write the copy; it may not decide
the aspect ratio, the duration ceiling, or the status badge.
"""

from __future__ import annotations

from typing import Any

from app.modules.skills.platform_specs import get_spec
from app.modules.skills.validators import platform_limit, register


@register("variants_match_spec_table")
def _variants_match_spec_table(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Drop unsupported platforms and overwrite model-invented specs."""
    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in data.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        key = str(variant.get("platform", "")).strip().lower()
        if key in seen:
            warnings.append(f"duplicate_platform_variant_dropped:{key}")
            continue
        try:
            spec = get_spec(key)
        except Exception:  # noqa: BLE001 - unknown platform is a documented failure
            warnings.append(f"unsupported_platform_dropped:{key[:24]}")
            continue
        seen.add(key)
        variant["platform"] = spec.key
        variant["label"] = spec.label
        variant["aspect"] = spec.aspect
        variant["width"] = spec.width
        variant["height"] = spec.height
        variant["impl_status"] = spec.impl_status
        variant["render_capable"] = spec.render_capable
        kept.append(variant)

    if not kept:
        # Falling back to Reels keeps the creator's flow alive and is honest:
        # the warning says the requested platform was not supported.
        spec = get_spec("instagram_reels")
        kept.append(
            {
                "platform": spec.key,
                "label": spec.label,
                "aspect": spec.aspect,
                "width": spec.width,
                "height": spec.height,
                "impl_status": spec.impl_status,
                "render_capable": spec.render_capable,
                "title": "",
                "caption": "",
                "hashtags": [],
                "reframe_notes": [],
                "warnings": ["platform_fallback_to_instagram_reels"],
            }
        )
        warnings.append("platform_fallback_to_instagram_reels")
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.4), 2)

    data["variants"] = kept
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("variant_duration_clamped")
def _variant_duration_clamped(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Every variant must fit its platform's hard duration ceiling."""
    warnings: list[str] = []
    for variant in data.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        spec = get_spec(variant["platform"])
        try:
            duration = float(variant.get("duration_s") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            continue
        clamped = max(spec.min_duration_s, min(duration, spec.max_duration_s))
        if clamped != duration:
            variant["duration_s"] = clamped
            variant.setdefault("warnings", []).append(
                f"duration_clamped_to_{spec.max_duration_s}s"
            )
            warnings.append(f"duration_clamped:{spec.key}")
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("variant_text_within_limits")
def _variant_text_within_limits(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md `caption.generate`/`platform.adapt`: platform char limits."""
    warnings: list[str] = []
    for variant in data.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        limits = platform_limit(variant["platform"])
        caption = str(variant.get("caption") or "")
        caption_limit = int(limits["caption_chars"])
        if len(caption) > caption_limit:
            variant["caption"] = caption[: caption_limit - 1] + "…"
            variant.setdefault("warnings", []).append("caption_truncated")
            warnings.append(f"caption_truncated:{variant['platform']}")
        tags = variant.get("hashtags") or []
        spec = get_spec(variant["platform"])
        if len(tags) > spec.hashtag_limit:
            variant["hashtags"] = list(tags)[: spec.hashtag_limit]
            variant.setdefault("warnings", []).append("hashtags_truncated")
            warnings.append(f"hashtags_truncated:{variant['platform']}")
        for tag in variant.get("hashtags") or []:
            if not str(tag).startswith("#"):
                variant["hashtags"] = [
                    f"#{str(t).lstrip('#')}" for t in variant["hashtags"]
                ]
                break
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("variant_reframe_notes_present")
def _variant_reframe_notes_present(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """A non-9:16 variant cannot be produced by reframing alone without notes."""
    warnings: list[str] = []
    for variant in data.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        if variant["aspect"] == "9:16":
            continue
        if not variant.get("reframe_notes"):
            variant["reframe_notes"] = [
                f"Crop master cut to {variant['aspect']} "
                f"({variant['width']}x{variant['height']}); keep the subject inside the "
                f"safe area ({int(get_spec(variant['platform']).safe_area_pct * 100)}% inset)."
            ]
            warnings.append(f"reframe_notes_defaulted:{variant['platform']}")
        if not variant.get("render_capable"):
            variant.setdefault("warnings", []).append("render_not_supported_on_this_platform")
    return ", ".join(sorted(set(warnings))) if warnings else None
