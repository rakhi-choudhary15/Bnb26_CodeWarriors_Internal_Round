"""Job routes (API-SPECIFICATION.md §Intelligence).

One polling endpoint. It reports `status`, `stage`, `progress`, `error?` and
`result?`, and it is owner-scoped: another creator's job id is simply not found.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentOwner, DbSession
from app.api.serializers import job_out
from app.core.jobs import JobStatus
from app.modules.jobs import service as job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def read_job(db: DbSession, owner_id: CurrentOwner, job_id: str) -> dict[str, Any]:
    """Poll a job. The UI should treat `progress` as advisory, not a percentage."""
    job = job_service.get_owned(db, owner_id=owner_id, job_id=job_id)
    payload: dict[str, Any] = {
        "id": str(job.id),
        "status": job.status.value,
        "stage": job.stage,
        "progress": job.progress,
        "attempts": job.attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
    if job.status is JobStatus.failed and job.error:
        payload["error"] = {"code": "JOB_FAILED", "message": job.error[:500]}
    if job.status is JobStatus.succeeded:
        payload["result"] = job.result or {}
    return payload


@router.get("")
def list_jobs(
    db: DbSession,
    owner_id: CurrentOwner,
    project_id: Annotated[str, Query(description="Jobs are always scoped to a project.")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    jobs = job_service.list_for_project(db, owner_id=owner_id, project_id=project_id, limit=limit)
    return {"items": [job_out(job) for job in jobs]}


@router.post("/{job_id}/cancel")
def cancel_job(db: DbSession, owner_id: CurrentOwner, job_id: str) -> dict[str, Any]:
    """Only a queued job can be cancelled; a running one is owned by its worker."""
    job = job_service.cancel(db, owner_id=owner_id, job_id=job_id)
    db.commit()
    return {"id": str(job.id), "status": job.status.value}
