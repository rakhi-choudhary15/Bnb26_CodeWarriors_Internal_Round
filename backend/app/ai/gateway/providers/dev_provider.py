"""Deterministic development provider (D-024).

Purpose: make the whole product runnable and testable with no API key, without
pretending to be a model. It dispatches on the skill id (`task`) and produces
schema-valid, deterministic output derived from the prompt.

Rules of engagement (mission §9, AGENTS.md §21):
  * every response this provider produces is tagged `provider="dev"` and the UI
    labels those surfaces MOCKED via the skill's registered status;
  * it never invents timestamps for media (D-009) — those come from ffprobe and
    the scene/transcript pipeline, and when neither exists it returns the
    explicit `unavailable` path rather than fabricating numbers;
  * it implements reasoning-free heuristics (keyword matching, enumeration,
    hashing) and says so, so nobody mistakes it for model output.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai.gateway.base import (
    AIProvider,
    EmbeddingResult,
    GenerateResult,
    Message,
    TranscriptResult,
)
from app.ai.gateway.providers.openai_compatible import cosine_similarity, unit_vector
from app.core.errors import AIUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Words that reliably identify a content type. Kept small and explicit: this is
# a keyword router, and it is documented as such.
CONTENT_SIGNALS: dict[str, tuple[str, ...]] = {
    "dance_video": ("dance", "dancing", "choreography", "reel dance", "beat drop"),
    "podcast": ("podcast", "interview", "episode", "conversation", "panel"),
    "product_ad": (
        "product ad",
        "advertisement",
        "commercial",
        "promo",
        "launch video",
        "ad for",
        "marketing video",
    ),
    "educational_talk": (
        "tutorial",
        "explainer",
        "lecture",
        "course",
        "teach",
        "how to",
        "educational",
    ),
    "short_video": ("reel", "short", "tiktok", "vertical video"),
}

TONE_WORDS = (
    "energetic",
    "calm",
    "playful",
    "serious",
    "bold",
    "warm",
    "motivational",
    "educational",
    "funny",
    "cinematic",
    "authentic",
    "urgent",
)

STYLE_WORDS = (
    "cinematic",
    "documentary",
    "vlog",
    "tutorial",
    "aesthetic",
    "raw",
    "polished",
    "minimal",
    "maximal",
    "bollywood",
    "street",
    "studio",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    # Cut on a word boundary: half a word reads as a bug, not as brevity.
    head = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{head}…" if head else text[: limit - 1].rstrip() + "…"


def _seed(text: str) -> int:
    return int(hashlib.sha256(_norm(text).encode()).hexdigest()[:8], 16)


def _pick(options: list[str], seed: int, count: int = 1) -> list[str]:
    if not options:
        return []
    ordered = sorted(options, key=lambda o: hashlib.sha256(f"{seed}:{o}".encode()).hexdigest())
    return ordered[:count]


class DevProvider(AIProvider):
    """Deterministic stand-in provider. Schema-valid, offline, honest."""

    name = "dev"

    def available(self) -> bool:
        return True

    def generate(
        self,
        messages: list[Message],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
    ) -> GenerateResult:
        task = extract_task(messages)
        prompt = "\n".join(m.content for m in messages)
        handler = _TASKS.get(task or "")
        if handler is not None:
            payload = handler(prompt)
            return GenerateResult(
                text=json.dumps(payload, indent=2),
                model=model,
                provider=self.name,
                tokens_in=max(1, len(prompt) // 4),
                tokens_out=max(1, len(json.dumps(payload)) // 4),
                cost_usd=0.0,
                structured=payload,
                warnings=["dev_provider"],
            )
        if json_mode:
            # Unknown task with a schema hint: return the minimal valid shape so a
            # caller never crashes, and flag it loudly.
            logger.warning("DevProvider has no handler for task %r; returning stub", task)
            return GenerateResult(
                text=json.dumps({"warnings": ["dev_provider_stub"], "confidence": 0.2}),
                model=model,
                provider=self.name,
                structured={"warnings": ["dev_provider_stub"], "confidence": 0.2},
                warnings=["dev_provider_stub"],
            )
        return GenerateResult(
            text=_deterministic_prose(prompt, task or "general"),
            model=model,
            provider=self.name,
            tokens_in=max(1, len(prompt) // 4),
            tokens_out=64,
            cost_usd=0.0,
            warnings=["dev_provider"],
        )

    def describe_images(
        self,
        images: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str,
        json_mode: bool = False,
    ) -> GenerateResult:
        """Vision fallback: analyse the pixels we were given, not an imagined scene.

        We compute real cheap image statistics (size, mean luminance, colour
        spread) with PIL so the output is derived from actual data, and label the
        semantic fields as unavailable rather than inventing a description.
        """
        stats = [_image_stats(data) for data, _ in images]
        captions = [
            {
                "caption": (
                    f"Frame {i + 1}: {s['width']}x{s['height']}, "
                    f"brightness {s['mean_luma']:.0f}/255, colour spread {s['saturation']:.0f}/255"
                ),
                "tags": ["frame", "auto_stats"],
                "quality": {
                    "brightness": round(s["mean_luma"] / 255, 3),
                    "saturation": round(s["saturation"] / 255, 3),
                    "motion_energy": None,
                },
                "available": False,
            }
            for i, s in enumerate(stats)
        ]
        payload = {
            "frames": captions,
            "semantic_available": False,
            "confidence": 0.25,
            "warnings": ["vision_unavailable_pixel_stats_only"],
        }
        return GenerateResult(
            text=json.dumps(payload, indent=2),
            model=model,
            provider=self.name,
            structured=payload,
            warnings=["dev_provider", "vision_fallback"],
        )

    def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        """Hash-derived vectors: deterministic, same-text-same-vector.

        These support *deduplication and equality* checks but carry no semantics,
        so every semantic-search consumer is registered with `mocked` status.
        """
        return EmbeddingResult(
            vectors=[unit_vector(_seed(t), _dev_embed_dim()) for t in texts],
            model=f"{model} (dev-deterministic)",
            provider=self.name,
            tokens_in=sum(max(1, len(t) // 4) for t in texts),
            cost_usd=0.0,
        )

    def transcribe(self, audio_path: Path, *, model: str) -> TranscriptResult:
        raise AIUnavailableError(
            "The development provider cannot transcribe audio.",
            details={
                "mitigation": "the pipeline reports no_speech honestly and matches on "
                "visual captions with confidence capped at 0.7 (D-017, VIDEO-PIPELINE §8)",
            },
        )


def _dev_embed_dim() -> int:
    from app.core.config import settings

    return settings.embed_dim


def _image_stats(data: bytes) -> dict[str, float]:
    import io

    try:
        from PIL import Image, ImageStat

        img = Image.open(io.BytesIO(data)).convert("RGB")
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        grey = img.convert("L")
        mean_luma = ImageStat.Stat(grey).mean[0]
        hsv = img.convert("HSV")
        sat = ImageStat.Stat(hsv).mean[1]
        return {
            "width": float(img.width),
            "height": float(img.height),
            "mean_luma": float(mean_luma),
            "saturation": float(sat),
        }
    except Exception:  # noqa: BLE001 - unreadable frame is a normal outcome
        return {"width": 0.0, "height": 0.0, "mean_luma": 0.0, "saturation": 0.0}


_TASK_RE = re.compile(r"^\[task:([a-z0-9_.]+)\]", re.MULTILINE)


def extract_task(messages: list[Message]) -> str | None:
    """Read the skill id from the system prompt marker.

    Skills prefix their system prompt with `[task:<skill_id>]` so any provider can
    route without extra plumbing, and so `skill_runs` can be correlated with the
    prompt that produced it.
    """
    for message in messages:
        match = _TASK_RE.search(message.content)
        if match:
            return match.group(1)
    return None


def _deterministic_prose(prompt: str, task: str) -> str:
    source = _clip(prompt.replace("[task:", "").replace("]", ""), 240)
    return (
        f"[dev-provider:{task}] Deterministic local response. "
        f"Derived from a {len(prompt)} character prompt beginning: {source}"
    )


# ---------------------------------------------------------------------------
# Task handlers — one per skill that needs model output offline.
# ---------------------------------------------------------------------------
def _payload_of(prompt: str, key: str) -> Any:
    """Pull a JSON payload that skills embed in the prompt under `<data>`."""
    match = re.search(rf'<data key="{key}">(.*?)</data>', prompt, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _all_payloads(prompt: str) -> dict[str, Any]:
    return {
        key: value
        for key in ("intent", "concept", "script", "dna", "reference_dna", "shot_plan")
        if (value := _payload_of(prompt, key)) is not None
    }


def _task_intent_analyze(prompt: str) -> dict[str, Any]:
    texts = _payload_of(prompt, "input") or {}
    primary = str(texts.get("primary_text", "") or "")
    details = str(texts.get("details_text", "") or "")
    blob = _norm(f"{primary} {details}")
    seed = _seed(blob)

    content_type = "generic"
    best = 0
    for key, signals in CONTENT_SIGNALS.items():
        hits = sum(1 for s in signals if s in blob)
        if hits > best:
            best, content_type = hits, key
    if best == 0:
        content_type = "short_video" if any(p in blob for p in ("reel", "short", "tiktok")) else "generic"

    platform = _detect_platform(blob)
    duration = _detect_duration(blob) or _default_duration(platform)

    tone = [w for w in TONE_WORDS if w in blob] or _pick(list(TONE_WORDS), seed, 2)
    style = [w for w in STYLE_WORDS if w in blob] or _pick(list(STYLE_WORDS), seed, 1)
    audience = _detect_audience(blob) or "general audience discovering this topic"

    required_assets = ["video_footage"] if content_type != "podcast" else ["audio_footage"]
    required_assets += ["reference_video"] if "reference" in blob or "like" in blob else []

    stages = _stages_for(content_type, platform, duration)
    skills = sorted({s for stage in stages for s in stage["skills"]})

    return {
        "content_type": content_type,
        "custom_label": None,
        "format": "video" if platform != "linkedin" else "post",
        "platform": platform,
        "duration_s": duration,
        "tone": tone[:4],
        "style": style[:3],
        "audience": audience,
        "required_assets": required_assets,
        "required_skills": skills,
        "stages": [s["key"] for s in stages],
        "expected_output": _expected_output(content_type, platform, duration),
        "confidence": {
            "content_type": 0.82 if best else 0.45,
            "platform": 0.88 if _detect_platform(blob) else 0.55,
            "duration_s": 0.9 if _detect_duration(blob) else 0.6,
            "tone": 0.85 if any(w in blob for w in TONE_WORDS) else 0.5,
            "audience": 0.7 if _detect_audience(blob) else 0.4,
            "overall": 0.78 if best else 0.55,
        },
        "assumptions": _assumptions(blob, platform, duration),
    }


def _detect_platform(blob: str) -> str:
    table = (
        (("reel", "reels", "instagram"), "instagram_reels"),
        (("short", "shorts"), "youtube_shorts"),
        (("tiktok",), "tiktok"),
        (("youtube",), "youtube"),
        (("linkedin",), "linkedin"),
    )
    for signals, platform in table:
        if any(s in blob for s in signals):
            return platform
    return "instagram_reels"


def _detect_duration(blob: str) -> int | None:
    # "30-second", "30 seconds", "30s", "60 second"
    match = re.search(r"(\d{1,4})\s*(?:-|\s)?(?:sec|second|s\b|min|minute)", blob)
    if not match:
        return None
    value = int(match.group(1))
    if "min" in blob[match.start() : match.end() + 2]:
        value *= 60
    return max(5, min(value, 900))


def _default_duration(platform: str) -> int:
    return {"youtube": 480, "linkedin": 90, "tiktok": 21}.get(platform, 30)


def _detect_audience(blob: str) -> str | None:
    table = (
        (("gen z", "gen-z", "teen"), "Gen-Z short-form viewers"),
        (("beginner",), "beginners new to the topic"),
        (("professional", "b2b"), "industry professionals"),
        (("student",), "students"),
        (("parent",), "parents"),
        (("fitness",), "fitness enthusiasts"),
    )
    for signals, audience in table:
        if any(s in blob for s in signals):
            return audience
    return None


def _stages_for(content_type: str, platform: str, duration: int) -> list[dict[str, Any]]:
    """Stage plan matching the template catalogue (AI-SKILLS.md)."""
    if content_type == "dance_video":
        return [
            {"key": "concept", "title": "Concept", "skills": ["concept.generate"]},
            {"key": "hook", "title": "Hook", "skills": ["hook.generate"], "needs": ["concept"]},
            {"key": "script", "title": "Script / structure", "skills": ["script.generate"], "needs": ["hook"]},
            {"key": "reference_discovery", "title": "Reference discovery", "skills": ["reference.search"], "optional": True},
            {"key": "reference_analysis", "title": "Reference analysis", "skills": ["reference.analyze"], "optional": True},
            {"key": "shot_plan", "title": "Shot plan", "skills": ["shot.plan"], "needs": ["script"]},
            {"key": "recording_guidance", "title": "Recording guidance", "skills": ["recording.coach"], "needs": ["shot_plan"]},
            {"key": "asset_selection", "title": "Asset selection", "skills": ["asset.recommend"]},
            {"key": "footage_understanding", "title": "Footage understanding", "skills": ["video.transcribe", "video.understand"], "needs": ["asset_selection"]},
            {"key": "clip_selection", "title": "Clip selection", "skills": ["match.script_footage", "clip.generate"]},
            {"key": "editing", "title": "AI-assisted editing", "skills": ["edit.suggest"]},
            {"key": "platform_adaptation", "title": "Platform adaptation", "skills": ["platform.adapt"]},
            {"key": "captions", "title": "Caption / title / description", "skills": ["caption.generate"]},
            {"key": "review", "title": "Review", "skills": [], "manual": True},
        ]
    if content_type == "podcast":
        return [
            {"key": "topic", "title": "Topic & angle", "skills": ["concept.generate"]},
            {"key": "outline", "title": "Outline", "skills": ["script.generate"], "needs": ["topic"]},
            {"key": "questions", "title": "Questions", "skills": ["concept.generate"], "needs": ["topic"]},
            {"key": "recording", "title": "Recording guidance", "skills": ["recording.coach"], "needs": ["outline"]},
            {"key": "footage_understanding", "title": "Transcript", "skills": ["video.transcribe"], "needs": ["recording"]},
            {"key": "highlights", "title": "Highlights", "skills": ["clip.generate"], "needs": ["footage_understanding"]},
            {"key": "social_posts", "title": "Social posts", "skills": ["repurpose.content"], "needs": ["highlights"]},
            {"key": "captions", "title": "Captions", "skills": ["caption.generate"]},
            {"key": "review", "title": "Review", "skills": [], "manual": True},
        ]
    if content_type == "product_ad":
        return [
            {"key": "product_understanding", "title": "Product understanding", "skills": ["concept.generate"]},
            {"key": "audience", "title": "Audience", "skills": ["concept.generate"], "needs": ["product_understanding"]},
            {"key": "hook", "title": "Hook", "skills": ["hook.generate"], "needs": ["product_understanding"]},
            {"key": "script", "title": "Script", "skills": ["script.generate"], "needs": ["hook"]},
            {"key": "shot_list", "title": "Shot list", "skills": ["shot.plan"], "needs": ["script"]},
            {"key": "product_shots", "title": "Product shots", "skills": ["asset.recommend"], "needs": ["shot_list"]},
            {"key": "editing", "title": "Edit", "skills": ["edit.suggest"]},
            {"key": "cta", "title": "Call to action", "skills": ["caption.generate"], "needs": ["script"]},
            {"key": "platform_adaptation", "title": "Platform variants", "skills": ["platform.adapt"], "needs": ["editing"]},
            {"key": "review", "title": "Review", "skills": [], "manual": True},
        ]
    if content_type == "educational_talk":
        return [
            {"key": "concept", "title": "Concept", "skills": ["concept.generate"]},
            {"key": "hook", "title": "Hook", "skills": ["hook.generate"], "needs": ["concept"]},
            {"key": "script", "title": "Script", "skills": ["script.generate"], "needs": ["hook"]},
            {"key": "shot_plan", "title": "Shot plan", "skills": ["shot.plan"], "needs": ["script"]},
            {"key": "footage_understanding", "title": "Footage understanding", "skills": ["video.understand"], "needs": ["shot_plan"]},
            {"key": "match", "title": "Script ↔ footage", "skills": ["match.script_footage"], "needs": ["footage_understanding"]},
            {"key": "editing", "title": "Edit", "skills": ["edit.suggest"]},
            {"key": "platform_adaptation", "title": "Platform variants", "skills": ["platform.adapt"]},
            {"key": "captions", "title": "Captions", "skills": ["caption.generate"]},
            {"key": "review", "title": "Review", "skills": [], "manual": True},
        ]
    return _generic_stages(platform, duration)


def _generic_stages(platform: str, duration: int) -> list[dict[str, Any]]:
    return [
        {"key": "concept", "title": "Concept", "skills": ["concept.generate"]},
        {"key": "script", "title": "Script", "skills": ["script.generate"], "needs": ["concept"]},
        {"key": "shot_plan", "title": "Shot plan", "skills": ["shot.plan"], "needs": ["script"]},
        {"key": "asset_selection", "title": "Asset selection", "skills": ["asset.recommend"]},
        {"key": "footage_understanding", "title": "Footage understanding", "skills": ["video.understand"], "needs": ["asset_selection"]},
        {"key": "editing", "title": "AI-assisted editing", "skills": ["edit.suggest"]},
        {"key": "platform_adaptation", "title": "Platform adaptation", "skills": ["platform.adapt"]},
        {"key": "captions", "title": "Captions", "skills": ["caption.generate"]},
        {"key": "review", "title": "Review", "skills": [], "manual": True},
    ]


def _expected_output(content_type: str, platform: str, duration: int) -> str:
    label = {
        "instagram_reels": "Instagram Reel",
        "youtube_shorts": "YouTube Short",
        "tiktok": "TikTok video",
        "youtube": "YouTube video",
        "linkedin": "LinkedIn post",
        "other": "video",
    }.get(platform, "video")
    if platform == "linkedin":
        return f"{label} with caption and hashtags"
    return f"{duration}s {label}, 9:16, hook in first 3s, with CTA"


def _assumptions(blob: str, platform: str, duration: int) -> list[str]:
    out: list[str] = []
    if not _detect_platform(blob):
        out.append(f"Assumed {platform} as the platform.")
    if not _detect_duration(blob):
        out.append(f"Assumed {duration}s since no duration was mentioned.")
    if "vertical" not in blob and "9:16" not in blob and platform in ("instagram_reels", "tiktok", "youtube_shorts"):
        out.append("Assumed a 9:16 vertical format for short-form platforms.")
    return out


def _task_concept_generate(prompt: str) -> dict[str, Any]:
    intent = _payload_of(prompt, "intent") or {}
    subject = _subject(intent)
    topic = _topic(intent)
    tone = (intent.get("tone") or ["energetic"])[0]
    audience = intent.get("audience") or "this audience"
    return {
        "concepts": [
            {
                "title": f"{topic.title()} — {tone} opener",
                "premise": f"Open on the strongest visual beat, then reveal {subject}.",
                "why": f"Hits {tone} energy in the first second and holds {audience}.",
                "angle": "visual_first",
                "score": 0.71,
            },
            {
                "title": f"Countdown to {topic}",
                "premise": "Three escalating moments that land the payoff on the last beat.",
                "why": "Builds anticipation and gives the editor clean beat markers.",
                "angle": "escalation",
                "score": 0.64,
            },
            {
                "title": f"{_clip(topic.title(), 50)}, explained in one line",
                "premise": "A single-sentence promise followed by immediate proof.",
                "why": f"Direct and re-watchable; {audience} can follow it muted.",
                "angle": "direct",
                "score": 0.58,
            },
        ],
        "selected_index": 0,
        "confidence": 0.62,
        "warnings": [],
    }


#: "I want to create a ..." / "make me a ..." is request scaffolding, not subject.
#: The article is kept: hook sentences need it ("the fastest way to *a* reel").
_SUBJECT_PREFIX = re.compile(
    r"^(i\s+(want|need|would like)\s+to\s+(create|make|build|get)|create|make|build|generate)\s+",
    flags=re.I,
)
#: The destination platform belongs to the intent's structured fields, not in titles.
_SUBJECT_SUFFIX = re.compile(
    r"\s+(for|on|for\s+)\s*(instagram(\s+reels?)?|tiktok|youtube(\s+shorts?)?|linkedin"
    r"|twitter|x|facebook|reels?|shorts?).*$",
    flags=re.I,
)


def _subject(intent: dict[str, Any]) -> str:
    """The thing the creator asked for, as a phrase sentences can embed."""
    # Case is preserved: "Gen-Z" and brand casing survive into titles.
    text = re.sub(r"\s+", " ", str(intent.get("primary_text") or "")).strip()
    if not text:
        return "your idea"
    text = _SUBJECT_SUFFIX.sub("", _SUBJECT_PREFIX.sub("", text)).strip(" .,")
    return _clip(text, 70) or "your idea"


def _topic(intent: dict[str, Any]) -> str:
    """The subject without a leading article, for titles and labels."""
    text = re.sub(r"^(a|an|the)\s+", "", _subject(intent), flags=re.I)
    return text or "your idea"


def _keywords(intent: dict[str, Any], limit: int = 4) -> str:
    """The subject's content words, for slots that have a hard length budget."""
    stop = {
        "a", "an", "the", "for", "of", "to", "and", "with", "that", "this", "my",
        "video", "reel", "clip", "content", "post", "video.", "reel.", "my.",
    }
    words = [w for w in re.findall(r"[\w'-]+", _topic(intent)) if w.lower() not in stop]
    # A duration is already carried by the intent's own fields; "30-second" in a
    # hook reads like a spec, not a tease.
    kept = [w for w in words if not re.fullmatch(r"\d+[- ]?(second|sec|minute|min)s?", w, re.I)]
    return " ".join((kept or words)[:limit]) or _clip(_topic(intent), 24)


HOOK_STYLES = ("bold_claim", "question", "story", "challenge", "curiosity")


#: Hooks are cut to the spoken budget by the validator, and a hook cut
#: mid-phrase is not usable copy. Templates are written to fit instead.
_HOOK_WORD_BUDGET = 8


def _task_hook_generate(prompt: str) -> dict[str, Any]:
    intent = _payload_of(prompt, "intent") or {}
    keywords = _keywords(intent)
    subject = _subject(intent)
    duration = int(intent.get("duration_s") or 30)
    candidates = [
        ("bold_claim", f"This is the fastest way to {subject}."),
        ("question", f"Why does everyone struggle with {subject}?"),
        ("story", f"I tried {subject} for 30 days. Here's what changed."),
        ("challenge", f"Beat this in {max(10, duration)} seconds or scroll past."),
        ("curiosity", f"Everyone gets {subject} wrong. Watch the ending."),
        ("bold_claim", f"Stop overthinking {subject}. Do this instead."),
        # Short forms: used when the subject is too long to fit above.
        ("curiosity", f"Wait for the {keywords} reveal."),
        ("question", f"Think you know {keywords}? Watch this."),
        ("bold_claim", f"{keywords} in {max(10, duration)} seconds."),
        ("challenge", f"Your {keywords} attempt vs. this one."),
        ("story", f"Nobody warns you about {keywords}."),
        ("question", f"Still struggling with {keywords}?"),
    ]
    fitting = [c for c in candidates if len(c[1].split()) <= _HOOK_WORD_BUDGET]
    chosen = fitting[: max(3, min(5, duration // 10))]
    hooks = []
    for style, text in chosen:
        words = text.split()
        score = round(max(0.35, 0.9 - 0.03 * len(words) + (0.05 if style == "bold_claim" else 0)), 2)
        hooks.append(
            {
                "text": " ".join(words),
                "style": style,
                "score": score,
                "reason": f"{style.replace('_', ' ').title()} openings retain viewers in the first 3s.",
            }
        )
    return {
        "hooks": hooks,
        "selected_index": 0,
        "confidence": 0.6 if len(fitting) >= 3 else 0.4,
        "warnings": [] if len(fitting) >= 3 else ["no_hooks_fit_spoken_budget"],
    }


def _task_script_generate(prompt: str) -> dict[str, Any]:
    intent = _payload_of(prompt, "intent") or {}
    hooks = (_payload_of(prompt, "hooks") or {}).get("hooks") or []
    reference = _payload_of(prompt, "reference_dna") or {}
    duration = int(intent.get("duration_s") or 30)
    hook_text = hooks[0]["text"] if hooks else f"A strong start about {_subject(intent)}."
    subject = _subject(intent)

    # D-009 / AI-SKILLS.md: estimated spoken duration is computed here, not asked
    # of the model. ~2.6 words/second is the conversational short-form rate.
    words_per_second = 2.6
    beats: list[dict[str, Any]] = [
        ("hook", hook_text, "line"),
        ("setup", f"Here's the setup that makes {subject} work.", "line"),
        ("build", "Step one: get the movement and the frame right.", "line"),
        ("build", "Step two: lock the rhythm before you polish.", "line"),
        ("payoff", f"And that's the moment {subject} clicks.", "line"),
        ("cta", "Save this and try it today.", "cta"),
    ]
    if duration <= 20:
        beats = beats[:4]

    lines = []
    for beat, text, kind in beats:
        est = len(text.split()) / words_per_second
        lines.append(
            {
                "beat": beat,
                "text": text,
                "kind": kind,
                "estimated_seconds": round(est, 2),
            }
        )
    total = round(sum(line["estimated_seconds"] for line in lines), 2)
    if reference.get("shots"):
        # Structural constraint from Reference DNA (REFERENCE-DNA.md §5):
        # hook duration must stay close to the reference's hook window.
        ref_hook = float((reference.get("hook") or {}).get("duration_s") or 0) or 2.8
        lines[0]["estimated_seconds"] = round(ref_hook, 2)
        total = round(sum(line["estimated_seconds"] for line in lines), 2)

    drift = abs(total - duration) / max(duration, 1)
    warnings = [] if drift <= 0.1 else [f"estimated_duration_drift_{round(drift, 2)}"]
    return {
        "title": f"{_clip(subject.title(), 60)} — script",
        "lines": lines,
        "cta": lines[-1]["text"] if lines[-1]["kind"] == "cta" else "Follow for more.",
        "estimated_duration_s": total,
        "confidence": 0.6,
        "warnings": warnings,
    }


def _task_caption_generate(prompt: str) -> dict[str, Any]:
    intent = _payload_of(prompt, "intent") or {}
    script = _payload_of(prompt, "script") or {}
    platform = str(intent.get("platform") or "instagram_reels")
    subject = _subject(intent)
    lines = script.get("lines") or []
    hook_text = lines[0]["text"] if lines else subject
    tags = ["#" + w.replace(" ", "") for w in subject.split()[:3] if len(w) > 3]
    tags += ["#creatorai", "#fyp"]
    limits = {"instagram_reels": 2200, "tiktok": 2200, "youtube_shorts": 1000, "linkedin": 3000, "youtube": 5000}
    caption = f"{hook_text}\n\n{subject} — here's exactly how.\n\n{' '.join(tags)}"
    caption = _clip(caption, limits.get(platform, 2200))
    return {
        "caption": caption,
        "title": _clip(subject.title(), 90),
        "description": _clip(f"A short breakdown of {subject}.", 500),
        "hashtags": tags,
        "confidence": 0.6,
        "warnings": [],
    }


def _task_shot_plan(prompt: str) -> dict[str, Any]:
    intent = _payload_of(prompt, "intent") or {}
    script = _payload_of(prompt, "script") or {}
    reference = _payload_of(prompt, "reference_dna") or {}
    duration = float(intent.get("duration_s") or 30)
    lines = script.get("lines") or []

    avg_shot = float((reference.get("shots") or {}).get("avg_s") or 0) or 2.0
    framing_mix = (reference.get("framing") or {}) or {}
    framing_pref = (
        max(framing_mix, key=lambda k: framing_mix[k]) if framing_mix else "full_body"
    )
    hook_s = float((reference.get("hook") or {}).get("duration_s") or 0) or min(3.0, duration / 5)

    # One shot per script line, with the first split into hook + reaction beat.
    shot_count = max(5, min(12, len(lines) + 1))
    per_shot = duration / shot_count
    shots = []
    for i in range(shot_count):
        start = round(i * per_shot, 2)
        end = round(duration if i == shot_count - 1 else (i + 1) * per_shot, 2)
        is_hook = i == 0
        shots.append(
            {
                "n": i + 1,
                "start_s": start,
                "end_s": end,
                "framing": "close" if is_hook else framing_pref,
                "distance_m": 1.2 if is_hook else 2.5,
                "camera_height": "eye_level" if is_hook else "waist",
                "action": (
                    "Beat drop / first move hits the lens"
                    if is_hook
                    else f"Performance beat {i}: hit the accent move on the beat"
                ),
                "lighting": "backlit haze" if is_hook else "natural front light",
                "background": "clean single colour, no clutter",
                "notes": (
                    f"Hook must land in {hook_s:.1f}s — cut on the beat."
                    if is_hook
                    else f"Cut on the beat every {avg_shot:.1f}s to match reference rhythm."
                ),
            }
        )
    total = round(sum(s["end_s"] - s["start_s"] for s in shots), 2)
    return {
        "shots": shots,
        "total_duration_s": total,
        "checklist": {
            "props": ["tripod or stable surface", "shoes with grip"],
            "space": f"Clear {2.5 * 2:.1f}m x {2.5 * 2:.1f}m of floor",
            "lighting": "One key light in front, no harsh backlight unless intended",
        },
        "confidence": 0.6,
        "warnings": [],
    }


def _task_recording_coach(prompt: str) -> dict[str, Any]:
    plan = _payload_of(prompt, "shot_plan") or {}
    shots = plan.get("shots") or []
    tips = [
        f"Shot {s.get('n')}: {s.get('framing')} at {s.get('distance_m')}m, "
        f"{s.get('camera_height')} height. {s.get('notes', '')}"
        for s in shots[:6]
    ]
    return {
        "checklist": plan.get("checklist") or {},
        "tips": tips or ["Frame the shot list before you record."],
        "setup": [
            "Lock the phone horizontally locked and tap to focus before recording.",
            "Record 3 takes per shot; the editor uses the cleanest accent.",
        ],
        "confidence": 0.5,
        "warnings": [],
    }


def _task_blueprint_customize(prompt: str) -> dict[str, Any]:
    """Template customisation.

    The dev provider returns the template unchanged, which is the correct
    conservative behaviour: an unvalidated diff is worse than none
    (WORKFLOW-ENGINE.md §3.3).
    """
    return {"ops": [], "confidence": 0.5, "warnings": ["template_kept_unchanged"]}


def _task_platform_adapt(prompt: str) -> dict[str, Any]:
    specs = _payload_of(prompt, "platform_specs") or {}
    intent = _payload_of(prompt, "intent") or {}
    source = _payload_of(prompt, "source") or {}
    platforms = list(specs) or [str(intent.get("platform") or "instagram_reels")]
    master_caption = str(source.get("caption") or "")
    master_title = str(source.get("title") or "")
    master_duration = float(intent.get("master_duration_s") or intent.get("duration_s") or 30)
    subject = _subject(intent)

    variants = []
    for platform in platforms:
        spec = specs.get(platform) or {}
        max_s = float(spec.get("max_duration_s") or 600)
        hashtag_limit = int(spec.get("hashtag_limit") or 10)
        caption_limit = int(spec.get("caption_chars") or 2200)
        duration = min(master_duration, max_s)
        tags = ["#creatorai", "#shortform"]
        if platform == "instagram_reels":
            tags.append("#reels")
        elif platform == "youtube_shorts":
            tags.append("#shorts")
        reframe: list[str] = []
        if str(spec.get("aspect") or "9:16") != "9:16":
            reframe.append(
                f"Crop master cut to {spec.get('aspect')} "
                f"({spec.get('width')}x{spec.get('height')}); keep the subject centred."
            )
        if duration < master_duration:
            reframe.append(
                f"Cut the last {round(master_duration - duration, 1)}s to fit the {max_s:.0f}s ceiling."
            )
        variants.append(
            {
                "platform": platform,
                "duration_s": round(duration, 2),
                "title": _clip(master_title or f"{subject} — cut for {platform}", 100),
                "caption": _clip(master_caption or f"{subject}, adapted for {platform}.", caption_limit - 1),
                "hashtags": tags[:hashtag_limit],
                "reframe_notes": reframe,
            }
        )
    return {"variants": variants, "confidence": 0.55, "warnings": []}


def _task_edit_suggest(prompt: str) -> dict[str, Any]:
    clip = _payload_of(prompt, "clip") or {}
    start = float(clip.get("start_s") or 0.0)
    end = float(clip.get("end_s") or 0.0)
    duration = max(0.0, end - start)
    src_asset = str(clip.get("asset_id") or "")
    lines = (_payload_of(prompt, "script") or {}).get("lines") or []
    hook_text = lines[0]["text"] if lines else ""

    # EDL ranges are source-asset seconds; captions are timeline seconds
    # (VIDEO-PIPELINE.md §3).
    edl = {
        "version": 1,
        "aspect": "9:16",
        "clip_id": str(clip.get("clip_id") or clip.get("id") or ""),
        "tracks": {
            "video": [
                {
                    "src_asset": src_asset,
                    "in_s": round(start, 2),
                    "out_s": round(end, 2),
                    "reframe": {"mode": "center", "x": 0.5, "y": 0.5, "zoom": 1.0},
                }
            ],
            "captions": [
                {
                    "start_s": 0.2,
                    "end_s": round(min(duration, 3.0), 2),
                    "text": _clip(hook_text or "Your hook here", 90),
                    "style": "bold_center",
                }
            ],
            "markers": [{"t": 0.0, "type": "transition", "name": "hard_cut"}],
        },
        "suggestions": [],
    }

    suggestions = [
        {
            "id": "s_trim",
            "type": "trim",
            "start_s": round(start, 2),
            "end_s": round(end, 2),
            "detail": f"Trim dead air at the head and tail; keep {duration:.1f}s of usable action.",
            "confidence": 0.72,
            "applied": True,
        },
        {
            "id": "s_reframe",
            "type": "reframe",
            "start_s": round(start, 2),
            "end_s": round(end, 2),
            "detail": "Crop centre to 9:16 for Reels; keep the subject inside the safe area.",
            "confidence": 0.68,
            "applied": True,
        },
        {
            "id": "s_caption",
            "type": "caption",
            "start_s": 0.2,
            "end_s": round(min(duration, 3.0), 2),
            "detail": "Burn a bold-centre caption for the opening hook.",
            "confidence": 0.65,
            "applied": True,
        },
        # music / broll / transition are MOCKED by design (MVP-SCOPE 11b):
        # advisory text only, never `applied`.
        {
            "id": "s_music",
            "type": "music",
            "start_s": round(start, 2),
            "end_s": round(end, 2),
            "detail": "Add a royalty-free energetic track at the detected beat (suggestion only).",
            "confidence": 0.4,
            "applied": False,
        },
        {
            "id": "s_broll",
            "type": "broll",
            "start_s": round(start, 2),
            "end_s": round(end, 2),
            "detail": (
                f"Consider B-roll for: {_clip(lines[2]['text'], 90)}"
                if len(lines) > 2
                else "Consider B-roll for the setup beat."
            ),
            "confidence": 0.35,
            "applied": False,
        },
        {
            "id": "s_transition",
            "type": "transition",
            "start_s": round(start, 2),
            "end_s": round(end, 2),
            "detail": "Hard cut on the beat between sections (suggestion only).",
            "confidence": 0.45,
            "applied": False,
        },
    ]
    return {"edl": edl, "suggestions": suggestions, "confidence": 0.6, "warnings": []}


def _task_genome_propagate(prompt: str) -> dict[str, Any]:
    """Impact classification.

    The traversal and level assignment are deterministic code (see
    `modules/genome/impact.py`); the model only supplies the human-readable
    reason and suggestion. Offline we compose those from the already-computed
    level and node type, which keeps the text truthful instead of invented.
    """
    items = _payload_of(prompt, "candidates") or []
    out = []
    for item in items:
        level = item.get("level", "possibly_affected")
        node_type = item.get("node_type", "variant")
        if level == "affected":
            detail = "Re-check the matched range and update the burned caption."
        elif level == "text_affected":
            detail = "Rewrite the quoted claim to match the new wording."
        else:
            detail = "Review for consistency; no direct dependency detected."
        out.append(
            {
                "node_id": item.get("node_id"),
                "level": level,
                "reason": f"Derived from the edited {item.get('node_type', 'content')} via {node_type}.",
                "suggested_change": {
                    "summary": detail,
                    "new_text": item.get("suggested_text"),
                },
                "confidence": 0.6 if level != "possibly_affected" else 0.35,
            }
        )
    return {"items": out, "confidence": 0.6, "warnings": []}


def _task_intelligence_recommend(prompt: str) -> dict[str, Any]:
    data = _payload_of(prompt, "input") or {}
    dna = data.get("dna") or {}
    hooks = ((dna.get("hooks") or {}).get("styles") or {})
    top_hook = max(hooks, key=lambda k: hooks[k]) if hooks else "bold_claim"
    return {
        "next_ideas": [
            {
                "title": f"Repeat your {top_hook.replace('_', ' ')} hook in a new format",
                "rationale": "Your strongest hooks use this style; repetition compounds recall.",
                "effort": "low",
                "score": 0.78,
            },
            {
                "title": "Turn your best-performing clip into a carousel",
                "rationale": "Short-form performance carries into text formats on your audience.",
                "effort": "medium",
                "score": 0.64,
            },
            {
                "title": "Batch three hooks into one recording session",
                "rationale": "Reduces production overhead; your durations cluster tightly.",
                "effort": "low",
                "score": 0.55,
            },
        ],
        "gaps": [
            "No long-form (YouTube) variant published in the last 30 days.",
            "Second platform beyond Reels is unproven for this account.",
        ],
        "patterns": {"repeated_hooks": [top_hook], "durations": [30, 45]},
        "confidence": 0.45,
        "warnings": ["mocked_over_seeded_data"],
    }


def _task_dna_learn(prompt: str) -> dict[str, Any]:
    data = _payload_of(prompt, "input") or {}
    texts = data.get("texts") or []
    joined = " ".join(texts)
    tones = [t for t in TONE_WORDS if t in _norm(joined)]
    return {
        "profile": {
            "writing": {
                "tone": tones[:3] or ["direct"],
                "avg_sentence_words": round(
                    sum(len(s.split()) for s in _sentences(joined)) / max(1, len(_sentences(joined))), 1
                ),
                "emoji_rate": 0.0,
                "languages": ["en"],
            },
            "hooks": {
                "styles": {"bold_claim": 0.6, "question": 0.4},
                "avg_words": round(
                    sum(len(s.split()) for s in _sentences(joined)[:1]) or 8, 1
                ),
                "repeated": [],
            },
            "cta": {"style": "soft", "examples_count": len(texts)},
            "duration": {"instagram_reels": 30},
            "visual": {"framing": ["full_body"], "palette": [], "lighting": "natural_front"},
            "editing": {"avg_shot_s": 2.0, "caption_style": "bold_center", "transitions": ["hard_cut"]},
            "topics": [{"label": t, "freq": 0.6} for t in tones[:3]] or [{"label": "general", "freq": 1.0}],
            "confidence": {"writing": 0.4, "visual": 0.2},
        },
        "summary": "Updated from accepted outputs using deterministic statistics.",
        "confidence": 0.4,
        "warnings": [],
    }


def _task_archaeology_scan(prompt: str) -> dict[str, Any]:
    data = _payload_of(prompt, "input") or {}
    assets = data.get("assets") or []
    opportunities = []
    for asset in assets[:6]:
        minutes = float(asset.get("duration_s") or 0) / 60
        if minutes < 0.3:
            continue
        opportunities.append(
            {
                "kind": "short_form",
                "title": f"Cut a {min(1, max(0.2, minutes)):.1f} min highlight from {asset.get('filename')}",
                "rationale": f"{minutes:.1f} minutes of footage never referenced by any clip.",
                "source_asset_ids": [asset.get("id")],
                "source_ranges": [{"start_s": 0.0, "end_s": min(45.0, float(asset.get("duration_s") or 0))}],
                "effort": "low",
                "score": round(min(0.9, 0.4 + minutes * 0.1), 2),
            }
        )
    return {
        "opportunities": opportunities,
        "unused_minutes": round(
            sum(float(a.get("duration_s") or 0) for a in assets) / 60, 1
        ),
        "confidence": 0.45,
        "warnings": [],
    }


def _task_impact_explain(prompt: str) -> dict[str, Any]:
    items = _payload_of(prompt, "candidates") or []
    return {
        "items": [
            {
                "node_id": item.get("node_id"),
                "level": item.get("level"),
                "reason": item.get("reason") or "Downstream of the edit.",
                "suggested_change": {"summary": "Review this node."},
                "confidence": 0.5,
            }
            for item in items
        ],
        "confidence": 0.5,
        "warnings": [],
    }


def _task_clip_generate(prompt: str) -> dict[str, Any]:
    """`clip.generate` makes two structured calls under one skill id.

    The `[subtask:...]` marker selects the response shape: the scoring shape for
    hook strength, the prose shape for review reasons.
    """
    candidates = _payload_of(prompt, "candidates") or []
    if "[subtask:reason]" in prompt:
        return {
            "reasons": [
                {
                    "id": candidate.get("id"),
                    "reason": _dev_clip_reason(candidate),
                }
                for candidate in candidates
            ]
        }
    scores = []
    for candidate in candidates:
        speech = str(candidate.get("speech") or "").strip()
        scene = candidate.get("scene") or {}
        # Speech in the opening is the strongest signal available offline.
        strength = 0.62 if speech else 0.28
        if not scene.get("caption") and not scene.get("tags"):
            strength -= 0.08
        scores.append({"id": candidate.get("id"), "hook_strength": round(max(0.05, strength), 3)})
    return {"scores": scores}


def _dev_clip_reason(candidate: dict[str, Any]) -> str:
    speech = _clip(str(candidate.get("speech") or "").strip(), 120)
    scene = candidate.get("scene") or {}
    visual = _clip(str(scene.get("caption") or "").strip(), 90)
    if speech and visual:
        return f'{visual}, over the line "{speech}".'
    if speech:
        return f'Opens on "{speech}" and holds a complete thought.'
    if visual:
        return f"{visual} with no speech, so it needs a caption to carry the point."
    return "Sustained usable action, but no speech or visual description was available."


def _task_video_understand(prompt: str) -> dict[str, Any]:
    scenes = _payload_of(prompt, "scenes") or []
    described = [
        {
            "index": scene.get("index", index),
            "caption": (
                f"Continuous shot of {_clip(str((scene.get('quality') or {}).get('score', 0.0)), 4)}"
                " visual quality."
            ),
            "tags": ["auto_stats"],
        }
        for index, scene in enumerate(scenes)
    ]
    return {"scenes": described, "confidence": 0.4, "warnings": ["dev_provider"]}


_TASKS: dict[str, Callable[[str], dict[str, Any]]] = {
    "intent.analyze": _task_intent_analyze,
    "concept.generate": _task_concept_generate,
    "hook.generate": _task_hook_generate,
    "script.generate": _task_script_generate,
    "caption.generate": _task_caption_generate,
    "shot.plan": _task_shot_plan,
    "recording.coach": _task_recording_coach,
    "blueprint.customize": _task_blueprint_customize,
    "platform.adapt": _task_platform_adapt,
    "edit.suggest": _task_edit_suggest,
    "clip.generate": _task_clip_generate,
    "video.understand": _task_video_understand,
    "genome.propagate": _task_genome_propagate,
    "intelligence.recommend": _task_intelligence_recommend,
    "dna.learn": _task_dna_learn,
    "archaeology.scan": _task_archaeology_scan,
    "genome.explain": _task_impact_explain,
}


__all__ = ["DevProvider", "cosine_similarity", "extract_task"]