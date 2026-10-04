"""Serialisation helpers shared by the routers.

Models are persisted with SQLAlchemy enums and JSON columns; the API speaks
lowercase strings and plain dicts, so the mapping lives in one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from app.core.models import (
    Asset,
    CreationBlueprint,
    CreationIntent,
    Job,
    JobStatus,
    Project,
    Workflow,
    WorkflowStep,
)


def value_of(item: Any) -> Any:
    """Enums become their value; everything else passes through."""
    return item.value if isinstance(item, Enum) else item


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def as_str(value: uuid.UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def intent_out(intent: CreationIntent, *, warnings: list[str] | None = None) -> dict[str, Any]:
    parsed = intent.parsed or {}
    return {
        "id": str(intent.id),
        "project_id": str(intent.project_id),
        "primary_text": intent.primary_text,
        "details_text": intent.details_text,
        "parsed": parsed,
        "confidence": intent.confidence or {},
        "parse_status": intent.parse_status,
        "user_edited": bool(intent.user_edited),
        "fallback": bool(intent.fallback),
        "warnings": warnings or list(parsed.get("warnings") or []),
        "created_at": iso(intent.created_at),
    }


def project_out(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "title": project.title,
        "status": value_of(project.status),
        "intent_id": as_str(project.intent_id),
        "blueprint_id": as_str(project.blueprint_id),
        "workflow_id": as_str(project.workflow_id),
        "cover_asset_id": as_str(project.cover_asset_id),
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


def blueprint_out(blueprint: CreationBlueprint) -> dict[str, Any]:
    return {
        "id": str(blueprint.id),
        "project_id": str(blueprint.project_id),
        "intent_id": as_str(blueprint.intent_id),
        "template_key": blueprint.template_key,
        "version": blueprint.version,
        "stages": blueprint.stages or [],
        "expected_output": blueprint.expected_output or {},
        "created_at": iso(blueprint.created_at),
        "updated_at": iso(blueprint.updated_at),
    }


def step_out(step: WorkflowStep) -> dict[str, Any]:
    return {
        "id": str(step.id),
        "position": step.position,
        "key": step.key,
        "title": step.title,
        "goal": step.goal,
        "skill_ids": step.skill_ids or [],
        "needs": step.needs or [],
        "status": value_of(step.status),
        "input": step.input or {},
        "output_ref": step.output_ref or {},
        "optional": bool(step.optional),
        "manual": bool(step.manual),
        "impl_status": value_of(step.impl_status),
        "error": step.error,
    }


def workflow_out(workflow: Workflow) -> dict[str, Any]:
    return {
        "id": str(workflow.id),
        "project_id": str(workflow.project_id),
        "blueprint_id": as_str(workflow.blueprint_id),
        "status": value_of(workflow.status),
        "current_step_id": as_str(workflow.current_step_id),
        "steps": [step_out(step) for step in sorted(workflow.steps, key=lambda s: s.position)],
        "created_at": iso(workflow.created_at),
        "updated_at": iso(workflow.updated_at),
    }


def asset_out(asset: Asset, *, url: str | None = None, include_url: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(asset.id),
        "project_id": as_str(asset.project_id),
        "kind": value_of(asset.kind),
        "filename": asset.filename,
        "mime": asset.mime,
        "size_bytes": asset.size_bytes,
        "duration_s": asset.duration_s,
        "width": asset.width,
        "height": asset.height,
        "status": value_of(asset.status),
        "status_reason": asset.status_reason,
        "tags": asset.tags or [],
        "created_at": iso(asset.created_at),
    }
    if include_url:
        # Signed URLs are short-lived and never logged or persisted (SECURITY.md §4).
        payload["url"] = url
    return payload


def job_out(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "type": value_of(job.type),
        "status": value_of(job.status),
        "stage": job.stage,
        "progress": job.progress,
        "project_id": as_str(job.project_id),
        "error": job.error,
        # Only a finished job exposes its result; a running one has none yet.
        "result": job.result if job.status is JobStatus.succeeded else None,
        "attempts": job.attempts,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }
