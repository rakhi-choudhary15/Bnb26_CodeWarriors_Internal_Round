"""Creation routes (API-SPECIFICATION.md §Creation).

These endpoints are synchronous and fast: `intent.analyze` is one model call.
Anything heavier is a job elsewhere. Response shapes follow the spec exactly,
including the `intent`/`blueprint` envelopes.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import CurrentOwner, DbSession
from app.api.serializers import blueprint_out, intent_out
from app.core.errors import ValidationError
from app.modules.intent import repository as intent_repo
from app.modules.intent import service as intent_service
from app.modules.intent.schemas import CreateIntentRequest, UpdateIntentRequest
from app.modules.workflow import service as workflow_service
from app.modules.workflow.schemas import CreateBlueprintRequest, UpdateBlueprintRequest

router = APIRouter(prefix="/api/creation", tags=["creation"])


@router.post("/intents", status_code=status.HTTP_201_CREATED)
def create_intent(
    db: DbSession, owner_id: CurrentOwner, body: CreateIntentRequest
) -> dict[str, Any]:
    """Create the project and its intent, then run `intent.analyze`.

    The spec makes this a 201 even when the parse falls back: a low-confidence
    generic intent is a usable starting point, and `fallback:true` tells the UI
    to ask the creator to confirm the parse (API-SPECIFICATION.md §Creation).
    """
    project = workflow_service.create_project(
        db, owner_id=owner_id, title=body.primary_text[:80]
    )
    intent = intent_service.analyze(
        owner_id=owner_id,
        project_id=project.id,
        primary_text=body.primary_text,
        details_text=body.details_text,
        creator_dna=body.creator_dna,
        db=db,
    )
    db.commit()
    return {"project_id": str(project.id), "intent": intent_out(intent)}


@router.get("/intents/{intent_id}")
def read_intent(db: DbSession, owner_id: CurrentOwner, intent_id: str) -> dict[str, Any]:
    return {"intent": intent_out(intent_repo.get(db, owner_id=owner_id, intent_id=intent_id))}


@router.patch("/intents/{intent_id}")
def update_intent(
    db: DbSession, owner_id: CurrentOwner, intent_id: str, body: UpdateIntentRequest
) -> dict[str, Any]:
    """A creator edit always wins over the model's parse."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationError("Nothing to update.")
    intent = intent_repo.update(db, owner_id=owner_id, intent_id=intent_id, changes=changes)
    db.commit()
    return {"intent": intent_out(intent)}


@router.post("/blueprints", status_code=status.HTTP_201_CREATED)
def create_blueprint(
    db: DbSession, owner_id: CurrentOwner, body: CreateBlueprintRequest
) -> dict[str, Any]:
    """Turn a parsed intent into a validated stage list."""
    intent = intent_repo.get(db, owner_id=owner_id, intent_id=body.intent_id)
    blueprint = workflow_service.build_blueprint(
        db, owner_id=owner_id, project_id=intent.project_id, intent=intent
    )
    db.commit()
    return {"blueprint": blueprint_out(blueprint)}


@router.get("/blueprints/{blueprint_id}")
def read_blueprint(db: DbSession, owner_id: CurrentOwner, blueprint_id: str) -> dict[str, Any]:
    return {
        "blueprint": blueprint_out(
            workflow_service.get_blueprint(db, owner_id=owner_id, blueprint_id=blueprint_id)
        )
    }


@router.patch("/blueprints/{blueprint_id}")
def update_blueprint(
    db: DbSession, owner_id: CurrentOwner, blueprint_id: str, body: UpdateBlueprintRequest
) -> dict[str, Any]:
    """Blueprint versions are immutable: an edit writes version n+1."""
    blueprint = workflow_service.update_blueprint(
        db, owner_id=owner_id, blueprint_id=blueprint_id, stages=body.stages
    )
    db.commit()
    return {"blueprint": blueprint_out(blueprint)}


def intent_for_project(db: DbSession, *, owner_id: uuid.UUID, project_id: uuid.UUID | str) -> Any:
    """The project's current intent, for the project summary endpoints."""
    project = workflow_service.get_project(db, owner_id=owner_id, project_id=project_id)
    if project.intent_id:
        return intent_repo.get(db, owner_id=owner_id, intent_id=project.intent_id)
    return intent_repo.latest_for_project(db, owner_id=owner_id, project_id=project.id)
