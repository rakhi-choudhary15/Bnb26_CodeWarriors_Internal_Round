"""Project and workflow routes (API-SPECIFICATION.md §Projects / Workflows).

`POST /api/workflows/:id/steps/:stepId/run` is the hinge of the whole system: a
fast skill answers 200 inline, a long-running one hands back 202 + a job the UI
polls. Which one it is comes from the skill registry, never from a route.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AiRateLimit, CurrentOwner, DbSession, IdempotencyKey
from app.api.serializers import blueprint_out, intent_out, project_out, workflow_out
from app.core.errors import ConflictError, ValidationError
from app.modules.intent import repository as intent_repo
from app.modules.jobs import service as job_service
from app.modules.workflow import service as workflow_service
from app.modules.workflow.schemas import StartWorkflowRequest, UpdateStepRequest

router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
def list_projects(
    db: DbSession,
    owner_id: CurrentOwner,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    projects = workflow_service.list_projects(db, owner_id=owner_id, limit=limit)
    return {"items": [project_out(p) for p in projects]}


@router.get("/projects/{project_id}")
def read_project(db: DbSession, owner_id: CurrentOwner, project_id: str) -> dict[str, Any]:
    """Project with its intent, blueprint and workflow summary in one call."""
    project = workflow_service.get_project(db, owner_id=owner_id, project_id=project_id)
    payload = project_out(project)
    if project.intent_id:
        payload["intent"] = intent_out(
            intent_repo.get(db, owner_id=owner_id, intent_id=project.intent_id)
        )
    if project.blueprint_id:
        payload["blueprint"] = blueprint_out(
            workflow_service.get_blueprint(db, owner_id=owner_id, blueprint_id=project.blueprint_id)
        )
    if project.workflow_id:
        workflow = workflow_service.get_workflow(
            db, owner_id=owner_id, workflow_id=project.workflow_id
        )
        payload["workflow"] = {
            "id": str(workflow.id),
            "status": workflow.status.value if hasattr(workflow.status, "value") else workflow.status,
            "current_step_id": str(workflow.current_step_id) if workflow.current_step_id else None,
            "steps_total": len(workflow.steps),
        }
    return payload


@router.post("/projects/{project_id}/workflows", status_code=status.HTTP_201_CREATED)
def start_workflow(
    db: DbSession, owner_id: CurrentOwner, project_id: str, body: StartWorkflowRequest
) -> dict[str, Any]:
    """Materialise a blueprint into ordered steps."""
    project = workflow_service.get_project(db, owner_id=owner_id, project_id=project_id)
    blueprint_id = body.blueprint_id or project.blueprint_id
    if not blueprint_id:
        raise ValidationError(
            "This project has no blueprint yet.",
            details={"hint": "POST /api/creation/blueprints first"},
        )
    workflow_service.ensure_no_active_conflict(db, owner_id=owner_id, project_id=project.id)
    workflow = workflow_service.start_workflow(
        db, owner_id=owner_id, project_id=project.id, blueprint_id=blueprint_id
    )
    db.commit()
    return {"workflow": workflow_out(workflow)}


@router.get("/projects/{project_id}/workflows")
def list_workflows(db: DbSession, owner_id: CurrentOwner, project_id: str) -> dict[str, Any]:
    project = workflow_service.get_project(db, owner_id=owner_id, project_id=project_id)
    workflows = workflow_service.list_workflows(db, owner_id=owner_id, project_id=project.id)
    return {"items": [workflow_out(w) for w in workflows]}


@router.get("/workflows/{workflow_id}")
def read_workflow(db: DbSession, owner_id: CurrentOwner, workflow_id: str) -> dict[str, Any]:
    return {
        "workflow": workflow_out(
            workflow_service.get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
        )
    }


@router.post("/workflows/{workflow_id}/steps/{step_id}/run")
def run_step(
    db: DbSession,
    owner_id: CurrentOwner,
    workflow_id: str,
    step_id: str,
    response: Response,
    idempotency_key: IdempotencyKey,
    _: AiRateLimit,
) -> dict[str, Any]:
    """Run one step: 200 with the result, or 202 with a job to poll."""
    step = workflow_service.get_step(
        db, owner_id=owner_id, workflow_id=workflow_id, step_id=step_id
    )
    _require_runnable(step)
    workflow = workflow_service.get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
    skills = workflow_service.resolve_skills(step)
    if not skills:
        # A manual stage is a gate, not a job: it is accepted or skipped.
        raise ConflictError(
            "This step is yours to accept or skip.",
            details={"step_id": str(step.id), "manual": True},
        )

    if workflow_service.requires_job(step):
        # Commit first: a worker may start the moment the job is queued, and it
        # must not read a step or project that is still uncommitted.
        db.commit()
        job_id, reused = job_service.submit(
            db,
            owner_id=owner_id,
            job_type=workflow_service.job_type_for(step),
            payload={"workflow_id": str(workflow.id), "step_id": str(step.id), "skill_ids": skills},
            project_id=workflow.project_id,
            idempotency_key=idempotency_key,
        )
        db.commit()
        response.status_code = status.HTTP_200_OK if reused else status.HTTP_202_ACCEPTED
        payload: dict[str, Any] = {"job_id": str(job_id), "step_id": str(step.id)}
        if reused:
            payload["reused"] = True
        return payload

    result = workflow_service.run_step_inline(
        db,
        owner_id=owner_id,
        workflow=workflow,
        step=step,
        skill_ids=skills,
        gateway_context={"workflow_id": str(workflow.id), "step_id": str(step.id)},
    )
    db.commit()
    return {"step_id": str(step.id), "result": result}


@router.patch("/workflows/{workflow_id}/steps/{step_id}")
def update_step(
    db: DbSession, owner_id: CurrentOwner, workflow_id: str, step_id: str, body: UpdateStepRequest
) -> dict[str, Any]:
    """Accept (`done`) or skip (`skipped`) a step, then advance the workflow."""
    step = workflow_service.set_step_status(
        db, owner_id=owner_id, workflow_id=workflow_id, step_id=step_id, status=body.status
    )
    db.commit()
    return {"step_id": str(step.id), "status": step.status.value}


@router.post("/workflows/{workflow_id}/cancel")
def cancel_workflow(
    db: DbSession, owner_id: CurrentOwner, workflow_id: str
) -> dict[str, Any]:
    workflow = workflow_service.get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
    if workflow.status != "active":
        raise ConflictError(
            "That workflow is not active.",
            details={"workflow_id": str(workflow.id), "status": workflow.status},
        )
    for job in job_service.list_for_project(db, owner_id=owner_id, project_id=workflow.project_id):
        if job.status == "queued":
            try:
                job_service.cancel(db, owner_id=owner_id, job_id=job.id)
            except ConflictError:
                # Already picked up by a worker; the workflow stop is still honoured.
                continue
    workflow_service.cancel_workflow(db, owner_id=owner_id, workflow_id=workflow.id)
    db.commit()
    return {"workflow_id": str(workflow.id), "status": "cancelled"}


#: States from which a step may be run (WORKFLOW-ENGINE.md §2). `locked` is
#: deliberately excluded: its prerequisites are unmet, so running it would skip
#: the graph the blueprint defines.
RUNNABLE_STATUSES: frozenset[str] = frozenset({"ready", "needs_review", "failed"})


def _require_runnable(step: Any) -> None:
    """Guard the workflow state machine: a locked step cannot jump the queue."""
    current = step.status.value if hasattr(step.status, "value") else str(step.status)
    if current not in RUNNABLE_STATUSES:
        raise ConflictError(
            "That step cannot run right now.",
            details={"step_id": str(step.id), "status": current},
        )
