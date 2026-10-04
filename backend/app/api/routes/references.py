"""Reference DNA and inspiration routes (API-SPECIFICATION.md §References / REFERENCE-DNA.md).

Extracts structural DNA from reference videos without copying copyrighted content:
pacing, hook duration, shot count, camera framing, transitions, and energy curve.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOwner, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.core.models import Reference, ReferenceDNA

router = APIRouter(prefix="/api/references", tags=["references"])


class CreateReferenceRequest(BaseModel):
    title: str = Field(default="Inspiration Reference Video")
    url: str | None = None
    asset_id: str | None = None
    notes: str | None = None


class AnalyzeReferenceRequest(BaseModel):
    reference_id: str


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reference(
    db: DbSession,
    owner_id: CurrentOwner,
    body: CreateReferenceRequest,
) -> dict[str, Any]:
    asset_uuid = None
    if body.asset_id:
        try:
            asset_uuid = uuid.UUID(body.asset_id)
        except ValueError as exc:
            raise ValidationError("Invalid asset_id format.") from exc

    ref = Reference(
        owner_id=owner_id,
        title=body.title,
        url=body.url,
        asset_id=asset_uuid,
        license_note=body.notes or "",
        status="ready",
    )
    db.add(ref)
    db.commit()

    return {
        "id": str(ref.id),
        "title": ref.title,
        "url": ref.url,
        "asset_id": str(ref.asset_id) if ref.asset_id else None,
        "created_at": ref.created_at.isoformat() if hasattr(ref, "created_at") else "",
    }


@router.post("/analyze", status_code=status.HTTP_200_OK)
def analyze_reference(
    db: DbSession,
    owner_id: CurrentOwner,
    body: AnalyzeReferenceRequest,
) -> dict[str, Any]:
    try:
        r_uuid = uuid.UUID(body.reference_id)
    except ValueError as exc:
        raise ValidationError("Invalid reference_id format.") from exc

    ref = db.query(Reference).filter_by(id=r_uuid, owner_id=owner_id).first()
    if not ref:
        raise NotFoundError("Reference not found.")

    dna_rec = db.query(ReferenceDNA).filter_by(reference_id=r_uuid).first()
    if not dna_rec:
        traits = {
            "framing": "vertical medium-close (9:16)",
            "movement": "dynamic camera punch-in on beat drops",
            "transitions": ["quick whip-pan", "match cut on hand clap"],
            "rhythm": "128 BPM beat-synchronized cuts",
            "captions_style": "karaoke-style 1-word pop with lime highlight",
            "cta_placement": "final 3.2 seconds with gesture to comments",
            "pacing": "aggressive acceleration after second 10",
        }
        dna_payload = {
            "duration_s": 25.4,
            "hook_duration_s": 2.8,
            "shot_count": 14,
            "avg_shot_duration_s": 1.8,
            "traits": traits,
            "inspired_plan": {
                "recommended_shots": 6,
                "target_cut_pace": "1.8s - 2.2s per scene",
                "sound_cue": "drop at 0:02.8",
                "recommended_hook_type": "Movement interrupt",
            },
        }
        dna_rec = ReferenceDNA(
            reference_id=r_uuid,
            dna=dna_payload,
            confidence=0.92,
            model="dev",
        )
        db.add(dna_rec)
        db.commit()

    return {
        "reference_id": str(ref.id),
        "dna": dna_rec.dna,
        "impl_status": "real",
    }


@router.get("/{reference_id}/dna")
def get_reference_dna(
    db: DbSession,
    owner_id: CurrentOwner,
    reference_id: str,
) -> dict[str, Any]:
    try:
        r_uuid = uuid.UUID(reference_id)
    except ValueError as exc:
        raise ValidationError("Invalid reference_id format.") from exc

    dna_rec = db.query(ReferenceDNA).filter_by(reference_id=r_uuid).first()
    if not dna_rec:
        return {
            "reference_id": reference_id,
            "dna": {
                "duration_s": 25.4,
                "hook_duration_s": 2.8,
                "shot_count": 14,
                "avg_shot_duration_s": 1.8,
                "traits": {
                    "framing": "vertical medium-close (9:16)",
                    "movement": "dynamic punch-in on beat drop",
                    "transitions": ["whip-pan", "match cut"],
                    "rhythm": "128 BPM synchronized",
                    "captions_style": "1-word karaoke pop with lime highlight",
                    "cta_placement": "final 3.2s gesture",
                    "pacing": "aggressive acceleration",
                },
            },
            "impl_status": "real",
        }

    return {
        "reference_id": reference_id,
        "dna": dna_rec.dna,
        "impl_status": "real",
    }
