"""Job service: owner-scoped access to the queue (API-SPECIFICATION.md §Jobs).

`app.core.jobs` owns persistence and dispatch; this layer adds the two things the
API needs and the core deliberately does not know about — ownership and
`Idempotency-Key` scoping.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.ids import stable_hash
from app.core.jobs import (
    JobStatus,
    JobType,
    cancel_job,
    enqueue_job,
    wait_for_job,
)
from app.core.logging import get_logger
from app.core.models import Job

logger = get_logger(__name__)

#: Statuses a client may observe; `cancelled` is terminal but still listed.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.cancelled.value}
)


def submit(
    db: Session,
    *,
    owner_id: uuid.UUID,
    job_type: str,
    payload: dict[str, Any],
    project_id: uuid.UUID | None,
    idempotency_key: str = "",
) -> tuple[uuid.UUID, bool]:
    """Queue a job. Returns `(job_id, reused)` where `reused` means 200, not 202."""
    try:
        resolved_type = JobType(job_type)
    except ValueError as exc:
        raise ValidationError(
            "Unknown job type.",
            details={"job_type": job_type, "allowed": [t.value for t in JobType]},
        ) from exc

    if project_id is not None:
        # The caller must own the project the job writes into.
        from app.modules.workflow.service import get_project

        get_project(db, owner_id=owner_id, project_id=project_id)

    digest = hash_for(
        owner_id=owner_id, job_type=resolved_type, idempotency_key=idempotency_key, payload=payload
    )
    existing = find_by_key(db, owner_id=owner_id, digest=digest, idempotency_key=idempotency_key)
    if existing is not None:
        return existing.id, True

    job_id = enqueue_job(
        owner_id=owner_id,
        job_type=resolved_type,
        payload=payload,
        project_id=project_id,
        input_hash=digest,
        # Write the row inside the caller's transaction: a second connection would
        # race the request's own uncommitted writes.
        db=db,
    )
    return job_id, False


def get_owned(db: Session, *, owner_id: uuid.UUID, job_id: uuid.UUID | str) -> Job:
    """Read a job the caller owns. Someone else's id is simply not found."""
    resolved = _uuid(job_id)
    job = db.execute(
        select(Job).where(Job.id == resolved, Job.owner_id == owner_id)
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Job not found.", details={"job_id": str(resolved)})
    return job


def list_for_project(
    db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID, limit: int = 20
) -> list[Job]:
    return list(
        db.execute(
            select(Job)
            .where(Job.owner_id == owner_id, Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def cancel(db: Session, *, owner_id: uuid.UUID, job_id: uuid.UUID | str) -> Job:
    """Cancel a job that has not started. A running job is left alone."""
    job = get_owned(db, owner_id=owner_id, job_id=job_id)
    if job.status == JobStatus.running:
        raise ConflictError(
            "That job is already running and cannot be cancelled.",
            details={"job_id": str(job.id), "status": JobStatus.running.value},
        )
    if job.status in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
        raise ConflictError(
            "That job has already finished.",
            details={"job_id": str(job.id), "status": JobStatus(job.status).value},
        )
    cancel_job(job.id)
    db.refresh(job)
    return job


def result_of(db: Session, *, owner_id: uuid.UUID, job_id: uuid.UUID | str) -> dict[str, Any]:
    """The job's result, refusing to present an unfinished run as done."""
    job = get_owned(db, owner_id=owner_id, job_id=job_id)
    if job.status is not JobStatus.succeeded:
        raise ConflictError(
            "That job has not finished yet.",
            details={"job_id": str(job.id), "status": job.status},
        )
    return job.result or {}


def wait(job_id: uuid.UUID, *, timeout_s: float) -> dict[str, Any]:
    """Block until a job settles. Used by tests and the dev-mode inline path."""
    return wait_for_job(job_id, timeout_s=timeout_s)


def hash_for(
    *, owner_id: uuid.UUID, job_type: JobType, idempotency_key: str, payload: dict[str, Any]
) -> str:
    """De-duplication hash, always scoped to the owner.

    Two owners submitting the same request must not share a job, and a client
    that sends no key still gets de-duplication from the payload itself.
    """
    if idempotency_key:
        return stable_hash(
            {"owner": str(owner_id), "type": job_type.value, "key": idempotency_key}
        )
    return stable_hash({"owner": str(owner_id), "type": job_type.value, "payload": payload})


def find_by_key(
    db: Session, *, owner_id: uuid.UUID, digest: str, idempotency_key: str
) -> Job | None:
    """The job a repeated request should be answered with, if any.

    An explicit `Idempotency-Key` means exactly-once (API-SPECIFICATION.md
    §Conventions: the same key and body return the original response), so a job
    is reused even after it finished — a retry after a network timeout must not
    bill the creator twice. Without a key only in-flight work is de-duplicated,
    because re-running a finished stage deliberately is how a new version is made.
    """
    candidates = db.execute(
        select(Job)
        .where(Job.owner_id == owner_id, Job.input_hash == digest)
        .order_by(Job.created_at.desc())
    ).scalars()
    existing = candidates.first()
    if existing is None:
        return None
    if idempotency_key or existing.status in (JobStatus.queued, JobStatus.running):
        return existing
    return None


def _uuid(value: uuid.UUID | str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFoundError("Job not found.") from exc
