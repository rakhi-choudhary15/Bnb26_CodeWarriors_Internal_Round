"""Intent Engine validators (AI-ARCHITECTURE.md §2, AI-SKILLS.md `intent.analyze`).

Rule-based post-processing, never model output, decides what is legal: enums,
platform limits, required-skill existence, stage/skill agreement.
"""

from __future__ import annotations

from typing import Any

from app.modules.skills.platform_specs import PLATFORMS
from app.modules.skills.validators import register

VALID_CONTENT_TYPES = {
    "dance_video",
    "podcast",
    "product_ad",
    "educational_talk",
    "short_video",
    "long_video",
    "social_post",
    "carousel",
    "generic",
}

#: Content type -> the blueprint template that serves it.
TEMPLATE_FOR_CONTENT_TYPE: dict[str, str] = {
    "dance_video": "dance_video",
    "podcast": "podcast",
    "product_ad": "product_ad",
    "educational_talk": "educational_talk",
    "short_video": "generic",
    "long_video": "generic",
    "social_post": "generic",
    "carousel": "generic",
    "generic": "generic",
}


@register("intent_enums")
def _intent_enums(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Coerce out-of-vocabulary values instead of failing the whole intent.

    AI-ARCHITECTURE.md §2: schema failure triggers a retry and then a
    deterministic fallback, which is strictly worse than a graceful default.
    """
    warnings: list[str] = []
    content_type = str(data.get("content_type") or "").strip().lower()
    if content_type not in VALID_CONTENT_TYPES:
        data["content_type"] = "generic"
        data["custom_label"] = content_type[:60] or None
        warnings.append(f"content_type_coerced_from_{content_type[:24]}")
        conf = data.get("confidence") or {}
        if isinstance(conf, dict):
            conf["content_type"] = 0.35
    platform = str(data.get("platform") or "").strip().lower()
    if platform not in PLATFORMS:
        data["platform"] = "instagram_reels"
        warnings.append("platform_coerced_to_instagram_reels")
        conf = data.get("confidence") or {}
        if isinstance(conf, dict):
            conf["platform"] = 0.4
    return ", ".join(warnings) if warnings else None


@register("intent_duration_clamp")
def _intent_duration_clamp(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Clamp duration to the chosen platform's hard limits."""
    spec = PLATFORMS.get(str(data.get("platform")), PLATFORMS["other"])
    try:
        duration = int(float(data.get("duration_s", 30)))
    except (TypeError, ValueError):
        duration = 30
    clamped = max(spec.min_duration_s, min(duration, spec.max_duration_s))
    if clamped != duration:
        assumptions = data.setdefault("assumptions", [])
        entry = f"Duration clamped to {clamped}s for {spec.label} (limit {spec.max_duration_s}s)."
        if entry not in assumptions:
            assumptions.append(entry)
        conf = data.get("confidence")
        if isinstance(conf, dict):
            conf["duration_s"] = min(float(conf.get("duration_s", 0.5)), 0.6)
    data["duration_s"] = clamped
    return data


@register("intent_skills_exist")
def _intent_skills_exist(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Only skills present in the registry may appear (WORKFLOW-ENGINE.md §3.3)."""
    from app.modules.skills.registry import skill_ids

    known = skill_ids()
    required = [s for s in (data.get("required_skills") or []) if s in known]
    dropped = len(data.get("required_skills") or []) - len(required)
    data["required_skills"] = required
    return f"dropped_{dropped}_unknown_skills" if dropped else None


@register("intent_stages_match_skills")
def _intent_stages_match_skills(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Stages are keys, not skills; keep both lists consistent and bounded."""
    stages = [str(s).strip() for s in (data.get("stages") or []) if str(s).strip()]
    # WORKFLOW-ENGINE.md §3.3 caps blueprints at 20 stages.
    if len(stages) > 20:
        stages = stages[:20]
    data["stages"] = stages
    if not data.get("required_assets"):
        data["required_assets"] = ["video_footage"]
    return "stages_capped_at_20" if len(stages) == 20 else None


@register("intent_assumptions_present")
def _intent_assumptions_present(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Low-confidence understanding must say what it assumed (explainability)."""
    conf = data.get("confidence") or {}
    overall = float(conf.get("overall", 1.0)) if isinstance(conf, dict) else 1.0
    assumptions = data.setdefault("assumptions", [])
    if overall < 0.6 and not assumptions:
        assumptions.append(
            "Understanding is low confidence — review the fields marked for confirmation."
        )
        return "low_confidence_without_assumptions"
    if overall < 0.6:
        return None
    return None