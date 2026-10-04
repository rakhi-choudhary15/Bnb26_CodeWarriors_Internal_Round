"""`caption.generate` validators (AI-SKILLS.md: "platform char limits")."""

from __future__ import annotations

from typing import Any

from app.modules.skills.validators import platform_limit, register

MIN_HASHTAGS = 3
MAX_HASHTAGS = 30


@register("platform_caption_limits")
def _platform_caption_limits(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Trim caption/title/hashtags to the target platform's hard limits."""
    platform = str(data.get("platform") or "instagram_reels").strip().lower()
    data["platform"] = platform
    limits = platform_limit(platform)
    warnings: list[str] = []

    caption = str(data.get("caption") or "")
    caption_limit = int(limits["caption_chars"])
    if len(caption) > caption_limit:
        data["caption"] = caption[: caption_limit - 1] + "…"
        warnings.append("caption_truncated")

    title = str(data.get("title") or "")
    title_limit = 0 if platform in ("instagram_reels", "tiktok") else 100
    if title_limit and len(title) > title_limit:
        data["title"] = title[:title_limit]
        warnings.append("title_truncated")
    if not title_limit and title:
        # Reels and TikTok have no title field; keeping it would mislead the API.
        warnings.append("title_dropped_platform_has_no_title_field")

    description = str(data.get("description") or "")
    if len(description) > caption_limit:
        data["description"] = description[: caption_limit - 1] + "…"
        warnings.append("description_truncated")

    data["hashtags"] = _clean_hashtags(data.get("hashtags") or [])
    if len(data["hashtags"]) > MAX_HASHTAGS:
        data["hashtags"] = data["hashtags"][:MAX_HASHTAGS]
        warnings.append("hashtags_capped")

    thumbnail = str(data.get("thumbnail_text") or "")
    if len(thumbnail) > 80:
        data["thumbnail_text"] = thumbnail[:80]
        warnings.append("thumbnail_text_truncated")

    return ", ".join(sorted(set(warnings))) if warnings else None


def _clean_hashtags(tags: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        text = str(tag).strip().lstrip("#").lower()
        text = "".join(ch for ch in text if ch.isalnum() or ch == "_")
        if not text:
            continue
        formatted = f"#{text}"
        if formatted not in cleaned:
            cleaned.append(formatted)
    return cleaned


@register("caption_first_line_is_the_hook")
def _caption_first_line_is_the_hook(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Feed surfaces show roughly one line before the "more" cut."""
    caption = str(data.get("caption") or "")
    if not caption:
        return "caption_empty"
    first = caption.splitlines()[0].strip()
    if not first:
        return "caption_first_line_empty"
    if len(first) > 125:
        data["caption"] = first[:122] + "..." + caption[len(first) :]
        return "caption_first_line_truncated_for_feed_preview"
    return None


@register("caption_hashtags_present")
def _caption_hashtags_present(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    if len(data.get("hashtags") or []) >= MIN_HASHTAGS:
        return None
    # Do not fabricate tags; flag the shortfall so the creator supplies intent.
    data["warnings"] = list(data.get("warnings") or []) + [
        f"fewer_than_{MIN_HASHTAGS}_hashtags"
    ]
    return "hashtag_count_low"
