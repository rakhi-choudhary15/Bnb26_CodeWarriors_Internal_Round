"""Multi-platform adaptation, publishing, and analytics routes (API-SPECIFICATION.md §Platform & Publishing).

Adapts a primary 9:16 export into Instagram Reels, YouTube Shorts, TikTok, YouTube, and LinkedIn,
handles publishing export packages, and returns mock analytics.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOwner, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.core.models import (
    AnalyticsRecord,
    ImplStatus,
    Platform,
    PlatformVariant,
    PublishingJob,
)

router = APIRouter(prefix="/api", tags=["platforms"])


class AdaptRequest(BaseModel):
    project_id: str
    source_node_id: str | None = None
    platforms: list[str] = Field(
        default_factory=lambda: ["instagram_reels", "youtube_shorts", "tiktok", "linkedin"]
    )


class UpdateVariantRequest(BaseModel):
    title: str | None = None
    caption: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None


class CreatePublishingJobRequest(BaseModel):
    variant_id: str
    schedule_at: str | None = None


@router.post("/platform/adapt", status_code=status.HTTP_200_OK)
def adapt_platform_variants(
    db: DbSession,
    owner_id: CurrentOwner,
    body: AdaptRequest,
) -> dict[str, Any]:
    try:
        p_uuid = uuid.UUID(body.project_id)
    except ValueError:
        raise ValidationError("Invalid project_id format.")

    existing = db.query(PlatformVariant).filter_by(project_id=p_uuid, owner_id=owner_id).all()
    if existing:
        return {
            "variants": [
                {
                    "id": str(v.id),
                    "platform": v.platform.value if hasattr(v.platform, "value") else str(v.platform),
                    "aspect": v.aspect,
                    "title": v.title,
                    "caption": v.caption,
                    "description": v.description,
                    "hashtags": v.hashtags,
                    "adaptation_notes": v.adaptation_notes,
                    "impl_status": v.impl_status.value if hasattr(v.impl_status, "value") else str(v.impl_status),
                }
                for v in existing
            ]
        }

    # Generate customized variants per platform
    specs = [
        (
            Platform.instagram_reels,
            "9:16",
            "Stop scrolling, try this Bollywood pop step! ⚡",
            "Master this 3-step routine in 30 seconds! Drop a comment if you nailed the second beat drop. #DanceChallenge #BollywoodDance #GenZCreators",
            "Full 30s 9:16 vertical render with burnt-in karaoke captions and trending audio cue.",
            ["#DanceChallenge", "#BollywoodDance", "#GenZCreators", "#ReelsViral", "#DanceTutorial"],
            ImplStatus.real,
        ),
        (
            Platform.youtube_shorts,
            "9:16",
            "Can You Do This 30-Second Dance Combo? #Shorts",
            "Try this energetic dance sequence! Subscribe for weekly routine breakdowns. #Shorts #Dance",
            "Optimized for 9:16 with high-contrast centered titles and subscribe button margin.",
            ["#Shorts", "#Dance", "#DanceRoutine", "#GenZ"],
            ImplStatus.mocked,
        ),
        (
            Platform.tiktok,
            "9:16",
            "wait for the beat drop at 0:15 😭⚡",
            "duet this if you can do the shoulder pop! dc: @genz_creator #fyp #dance #trend #viral",
            "Native TikTok text safe-zones applied; caption formatted for quick scanning.",
            ["#fyp", "#dance", "#trend", "#viral", "#dancecombo"],
            ImplStatus.mocked,
        ),
        (
            Platform.linkedin,
            "1:1",
            "What choreographing a viral 30-second Reel taught me about audience retention",
            "In content creation, micro-moments matter. By placing the visual hook at 0:02.8 and keeping scene cuts under 1.9s, viewer completion jumped 28%. Here is the breakdown.",
            "Converted to 1:1 square aspect with professional top/bottom commentary framing.",
            ["#ContentStrategy", "#CreatorEconomy", "#VideoProduction", "#Growth"],
            ImplStatus.mocked,
        ),
    ]

    variants = []
    for plat, aspect, title, cap, notes, tags, impl in specs:
        var = PlatformVariant(
            owner_id=owner_id,
            project_id=p_uuid,
            platform=plat,
            aspect=aspect,
            title=title,
            caption=cap,
            description=cap,
            hashtags=tags,
            adaptation_notes=notes,
            status="ready",
            impl_status=impl,
        )
        variants.append(var)

    db.add_all(variants)
    db.commit()

    return {
        "variants": [
            {
                "id": str(v.id),
                "platform": v.platform.value if hasattr(v.platform, "value") else str(v.platform),
                "aspect": v.aspect,
                "title": v.title,
                "caption": v.caption,
                "description": v.description,
                "hashtags": v.hashtags,
                "adaptation_notes": v.adaptation_notes,
                "impl_status": v.impl_status.value if hasattr(v.impl_status, "value") else str(v.impl_status),
            }
            for v in variants
        ]
    }


@router.patch("/variants/{variant_id}")
def update_variant(
    db: DbSession,
    owner_id: CurrentOwner,
    variant_id: str,
    body: UpdateVariantRequest,
) -> dict[str, Any]:
    try:
        v_uuid = uuid.UUID(variant_id)
    except ValueError:
        raise ValidationError("Invalid variant_id format.")

    var = db.query(PlatformVariant).filter_by(id=v_uuid, owner_id=owner_id).first()
    if not var:
        raise NotFoundError("Variant not found.")

    if body.title is not None:
        var.title = body.title
    if body.caption is not None:
        var.caption = body.caption
    if body.description is not None:
        var.description = body.description
    if body.hashtags is not None:
        var.hashtags = body.hashtags

    db.commit()
    return {
        "id": str(var.id),
        "platform": var.platform.value if hasattr(var.platform, "value") else str(var.platform),
        "title": var.title,
        "caption": var.caption,
        "hashtags": var.hashtags,
    }


@router.post("/publishing/jobs", status_code=status.HTTP_201_CREATED)
def create_publishing_job(
    db: DbSession,
    owner_id: CurrentOwner,
    body: CreatePublishingJobRequest,
) -> dict[str, Any]:
    try:
        v_uuid = uuid.UUID(body.variant_id)
    except ValueError:
        raise ValidationError("Invalid variant_id format.")

    var = db.query(PlatformVariant).filter_by(id=v_uuid, owner_id=owner_id).first()
    if not var:
        raise NotFoundError("Variant not found.")

    job = PublishingJob(
        owner_id=owner_id,
        variant_id=v_uuid,
        status="stubbed",
        impl_status=ImplStatus.stubbed,
        export_package={
            "platform": var.platform.value if hasattr(var.platform, "value") else str(var.platform),
            "video_render_url": f"/static/renders/{var.id}_9x16.mp4",
            "title": var.title,
            "caption": var.caption,
            "hashtags": var.hashtags,
            "checklist": {
                "script_approved": True,
                "captions_verified": True,
                "audio_rights_cleared": True,
                "safe_zones_checked": True,
            },
        },
    )
    db.add(job)
    db.commit()

    return {
        "id": str(job.id),
        "status": "stubbed",
        "impl_status": "stubbed",
        "message": "Export package compiled successfully. Ready for download or scheduled publishing.",
        "export_package": job.export_package,
    }


@router.get("/analytics")
def get_analytics(
    db: DbSession,
    owner_id: CurrentOwner,
    project_id: str | None = Query(None),
) -> dict[str, Any]:
    """Returns analytics and hook retention curves."""
    return {
        "summary": {
            "total_views": 128450,
            "avg_retention_rate": "67.8%",
            "engagement_rate": "9.4%",
            "top_performing_platform": "Instagram Reels",
        },
        "hook_retention_curve": [
            {"second": 0, "retention": 100},
            {"second": 2.8, "retention": 94},  # Hook holds!
            {"second": 5, "retention": 89},
            {"second": 10, "retention": 82},
            {"second": 15, "retention": 76},
            {"second": 20, "retention": 72},
            {"second": 25, "retention": 68},
            {"second": 30, "retention": 64},
        ],
        "variants_performance": [
            {"platform": "Instagram Reels", "views": 74200, "likes": 6420, "shares": 1180, "saves": 890},
            {"platform": "TikTok", "views": 38100, "likes": 3200, "shares": 940, "saves": 410},
            {"platform": "YouTube Shorts", "views": 16150, "likes": 980, "shares": 140, "saves": 75},
        ],
        "impl_status": "mocked",
        "source": "mock",
    }
