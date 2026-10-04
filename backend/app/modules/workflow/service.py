"""Projects, blueprints and workflows (AI-ARCHITECTURE.md §2-3).

A project is the container; the blueprint is the stage list the Intent Engine
produced; the workflow is the runnable state machine over those stages. Versions
are immutable: editing a blueprint creates version n+1 rather than overwriting.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway.base import get_gateway
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.models import (
    CreationBlueprint,
    JobType,
    Project,
    ProjectStatus,
    StepStatus,
    Workflow,
    WorkflowStep,
)
from app.modules.skills.base import SkillContext
from app.modules.skills.registry import get_module, get_spec, has_skill
from app.modules.skills.router import run_skill

#: Steps that need a worker rather than a request (AGENTS.md §8).
LONG_RUNNING_SKILLS: frozenset[str] = frozenset(
    {"video.understand", "video.transcribe", "clip.generate", "reference.analyze"}
)
#: The first runnable stage a new workflow unlocks.
FIRST_STATUS = StepStatus.ready


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def create_project(
    db: Session, *, owner_id: uuid.UUID, title: str, intent_id: uuid.UUID | None = None
) -> Project:
    project = Project(owner_id=owner_id, title=title[:200], intent_id=intent_id)
    db.add(project)
    db.flush()
    return project


def get_project(db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID | str) -> Project:
    resolved = _uuid(project_id, "project_id")
    project = db.execute(
        select(Project).where(Project.id == resolved, Project.owner_id == owner_id)
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found.", details={"project_id": str(resolved)})
    return project


def list_projects(db: Session, *, owner_id: uuid.UUID, limit: int = 50) -> list[Project]:
    return list(
        db.execute(
            select(Project)
            .where(Project.owner_id == owner_id)
            .order_by(Project.updated_at.desc())
            .limit(limit)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
def build_blueprint(
    db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID | str, intent: Any
) -> CreationBlueprint:
    """Turn a parsed intent into a stage list.

    Stage skill ids are checked against the registry here, so a blueprint can
    never reference a skill the router cannot run.
    """
    project = get_project(db, owner_id=owner_id, project_id=project_id)
    parsed = intent.parsed if hasattr(intent, "parsed") else dict(intent)
    stages = _stages_from_parsed(parsed)
    if not stages:
        raise ValidationError(
            "This intent has no usable stages yet.",
            details={"hint": "add a platform and a duration, then re-analyze"},
        )
    blueprint = CreationBlueprint(
        project_id=project.id,
        intent_id=intent.id if hasattr(intent, "id") else project.intent_id,
        template_key=str(parsed.get("content_type") or "generic")[:64],
        stages=stages,
        expected_output={"summary": parsed.get("expected_output", "")},
    )
    db.add(blueprint)
    db.flush()
    project.blueprint_id = blueprint.id
    project.intent_id = blueprint.intent_id
    db.add(project)
    return blueprint


def get_blueprint(
    db: Session, *, owner_id: uuid.UUID, blueprint_id: uuid.UUID | str
) -> CreationBlueprint:
    resolved = _uuid(blueprint_id, "blueprint_id")
    blueprint = _owned_blueprint(db, owner_id=owner_id, blueprint_id=resolved)
    if blueprint is None:
        raise NotFoundError("Blueprint not found.", details={"blueprint_id": str(resolved)})
    return blueprint


def update_blueprint(
    db: Session,
    *,
    owner_id: uuid.UUID,
    blueprint_id: uuid.UUID | str,
    stages: Sequence[Any],
) -> CreationBlueprint:
    """Reorder/add/remove stages by writing a new immutable version."""
    blueprint = get_blueprint(db, owner_id=owner_id, blueprint_id=blueprint_id)
    if not stages:
        raise ValidationError("A blueprint needs at least one stage.")
    for stage in stages:
        for skill_id in _stage_skill_ids(stage):
            if not has_skill(str(skill_id)):
                raise ValidationError(
                    "That stage uses a skill this deployment does not have.",
                    details={"skill_id": str(skill_id)[:64]},
                )
    blueprint.stages = _normalise_stages(stages)
    blueprint.version += 1
    db.add(blueprint)
    db.flush()
    return blueprint


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------
def start_workflow(
    db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID | str, blueprint_id: uuid.UUID | str
) -> Workflow:
    """Materialise a blueprint into runnable steps."""
    project = get_project(db, owner_id=owner_id, project_id=project_id)
    blueprint = get_blueprint(db, owner_id=owner_id, blueprint_id=blueprint_id)
    if blueprint.project_id != project.id:
        raise ValidationError("That blueprint belongs to a different project.")

    workflow = Workflow(project_id=project.id, blueprint_id=blueprint.id, status="active")
    db.add(workflow)
    db.flush()

    steps = _steps_from_stages(blueprint.stages)
    for position, stage in enumerate(steps):
        workflow.steps.append(
            WorkflowStep(
                position=position,
                key=stage["key"],
                title=stage["title"],
                goal=stage.get("goal"),
                skill_ids=stage["skill_ids"],
                needs=stage.get("needs", []),
                optional=bool(stage.get("optional")),
                manual=bool(stage.get("manual")),
                impl_status=stage.get("impl_status", "real"),
                status=FIRST_STATUS if position == 0 else StepStatus.locked,
            )
        )
    project.workflow_id = workflow.id
    project.status = ProjectStatus.producing
    db.add(project)
    db.flush()
    _unlock_next(db, workflow)
    return workflow


def get_workflow(
    db: Session, *, owner_id: uuid.UUID, workflow_id: uuid.UUID | str
) -> Workflow:
    resolved = _uuid(workflow_id, "workflow_id")
    workflow = db.execute(
        select(Workflow)
        .join(Project, Project.id == Workflow.project_id)
        .where(Workflow.id == resolved, Project.owner_id == owner_id)
    ).scalar_one_or_none()
    if workflow is None:
        raise NotFoundError("Workflow not found.", details={"workflow_id": str(resolved)})
    return workflow


def get_step(
    db: Session, *, owner_id: uuid.UUID, workflow_id: uuid.UUID | str, step_id: uuid.UUID | str
) -> WorkflowStep:
    workflow = get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
    resolved = _uuid(step_id, "step_id")
    step = next((s for s in workflow.steps if s.id == resolved), None)
    if step is None:
        raise NotFoundError("Workflow step not found.", details={"step_id": str(resolved)})
    return step


def set_step_status(
    db: Session,
    *,
    owner_id: uuid.UUID,
    workflow_id: uuid.UUID | str,
    step_id: uuid.UUID | str,
    status: str,
) -> WorkflowStep:
    """Accept or skip a step, then advance the workflow."""
    step = get_step(db, owner_id=owner_id, workflow_id=workflow_id, step_id=step_id)
    target = StepStatus(status)
    if target not in (StepStatus.done, StepStatus.skipped):
        raise ValidationError(
            "A step can only be marked done or skipped.",
            details={"allowed": ["done", "skipped"], "received": status},
        )
    step.status = target
    step.error = None
    db.add(step)
    workflow = get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
    _unlock_next(db, workflow)
    db.flush()
    return step


def resolve_skills(step: WorkflowStep) -> list[str]:
    """The skills a step will run, in order, skipping unknown ids."""
    return [str(s) for s in (step.skill_ids or []) if has_skill(str(s))]


def requires_job(step: WorkflowStep) -> bool:
    """Whether a step is too slow for a request (AGENTS.md §8: > 5s)."""
    return any(skill in LONG_RUNNING_SKILLS for skill in resolve_skills(step))


def job_type_for(step: WorkflowStep) -> str:
    """Map the step's slowest skill onto a `JobType` a worker handles."""
    mapping = {
        "video.understand": JobType.video_analyze,
        "clip.generate": JobType.clips_generate,
        "reference.analyze": JobType.reference_analyze,
        "archaeology.scan": JobType.archaeology_scan,
        "genome.propagate": JobType.genome_propagate,
        "dna.learn": JobType.dna_learn,
    }
    for skill_id in reversed(resolve_skills(step)):
        if skill_id in mapping:
            return mapping[skill_id].value
    raise ValidationError(
        "This step has no background job type.",
        details={"skill_ids": step.skill_ids or []},
    )


def run_step_inline(
    db: Session,
    *,
    owner_id: uuid.UUID,
    workflow: Workflow,
    step: WorkflowStep,
    skill_ids: list[str],
    gateway_context: dict[str, Any],
) -> dict[str, Any]:
    """Run a fast skill inside the request and store its output on the step.

    Every output goes through `validate` + rule validation first: a step's stored
    output is treated as durable data, so an invalid model response is an error
    rather than something a later stage will read (AGENTS.md §23).
    """
    ctx = SkillContext(
        owner_id=owner_id,
        project_id=workflow.project_id,
        step_id=step.id,
        skill_id=skill_ids[0],
        gateway=get_gateway(),
        context=gateway_context,
    )
    output: dict[str, Any] = {}
    for skill_id in skill_ids:
        if get_module(skill_id) is None:
            continue
        ctx = replace(ctx, skill_id=skill_id)
        payload = _step_input(
            db, workflow=workflow, step=step, owner_id=owner_id, skill_id=skill_id
        )
        # `run_skill` parses the typed input, runs the validators and records the
        # run; a step's stored output is durable data, so nothing skips it.
        result = run_skill(skill_id, payload, ctx, db)
        if result.status != "ok":
            raise ValidationError(
                "That step could not be completed.",
                details={"skill_id": skill_id, "warnings": result.warnings or [result.error]},
            )
        output = {
            "skill_id": skill_id,
            "output": result.output or {},
            "warnings": result.warnings,
        }

    step.status = StepStatus.needs_review
    step.output_ref = {"skill_id": output.get("skill_id"), "warnings": output.get("warnings", [])}
    step.error = None
    db.add(step)
    _unlock_next(db, workflow)
    db.flush()
    return output.get("output", {})


def cancel_workflow(db: Session, *, owner_id: uuid.UUID, workflow_id: uuid.UUID | str) -> Workflow:
    """Stop a workflow. Completed steps are kept; nothing is deleted."""
    workflow = get_workflow(db, owner_id=owner_id, workflow_id=workflow_id)
    if workflow.status != "active":
        raise ConflictError(
            "That workflow is not active.", details={"workflow_id": str(workflow.id)}
        )
    workflow.status = "cancelled"
    db.add(workflow)
    project = get_project(db, owner_id=owner_id, project_id=workflow.project_id)
    project.status = ProjectStatus.draft
    db.add(project)
    db.flush()
    return workflow


def list_workflows(
    db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID | str
) -> list[Workflow]:
    project = get_project(db, owner_id=owner_id, project_id=project_id)
    return list(
        db.execute(
            select(Workflow).where(Workflow.project_id == project.id).order_by(Workflow.created_at)
        ).scalars()
    )


def _step_input(
    db: Session, *, workflow: Workflow, step: WorkflowStep, owner_id: uuid.UUID, skill_id: str
) -> dict[str, Any]:
    """Build a step's input from the project record and its predecessors.

    Only the fields the target skill actually declares are passed. Every skill
    input is `extra="forbid"`, so handing over the whole project record would be
    rejected — and widening it would let a stage depend on something the
    blueprint never ordered it after.
    """
    spec = get_spec(skill_id)
    declared = set(spec.input_schema.model_fields) if spec and spec.input_schema else set()

    payload: dict[str, Any] = dict(step.input or {})
    if declared:
        # The parsed intent is the project's creative brief; a stage that declares
        # these fields gets them, and nothing else. `project_id` is included only
        # when the skill asks for it — every input is `extra="forbid"`.
        brief = {"project_id": str(workflow.project_id), **_project_brief(db, owner_id=owner_id, workflow=workflow)}
        payload.update(_declared_subset(brief, declared))
        for key in step.needs or []:
            predecessor = next((s for s in workflow.steps if s.key == key), None)
            if predecessor is None:
                continue
            payload.update(_declared_subset(predecessor.output_ref or {}, declared))
    return payload


def _project_brief(db: Session, *, owner_id: uuid.UUID, workflow: Workflow) -> dict[str, Any]:
    """The project's intent as a flat dict, plus its title."""
    project = get_project(db, owner_id=owner_id, project_id=workflow.project_id)
    brief: dict[str, Any] = {"title": project.title}
    if project.intent_id:
        from app.modules.intent.repository import get as get_intent

        brief.update(get_intent(db, owner_id=owner_id, intent_id=project.intent_id).parsed or {})
    return brief


def _declared_subset(source: dict[str, Any], declared: set[str]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key in declared}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _stages_from_parsed(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the intent's skill ids into blueprint stages.

    Every stage names the skill that runs it, so a workflow can be executed
    without re-deriving anything from prose.
    """
    stages: list[dict[str, Any]] = []
    for position, skill_id in enumerate(parsed.get("stages") or []):
        if not has_skill(str(skill_id)):
            continue
        stages.append(
            {
                "key": f"stage_{position + 1}_{str(skill_id).replace('.', '_')}",
                "title": str(skill_id).replace(".", " ").replace("_", " ").title(),
                "skill_ids": [str(skill_id)],
                "goal": None,
                "optional": False,
                "impl_status": _impl_status(str(skill_id)),
            }
        )
    if parsed.get("manual_review"):
        # A creator gate, not a skill: it stays `manual` so nothing tries to run it.
        stages.append(
            {
                "key": f"stage_{len(stages) + 1}_creator_review",
                "title": "Creator Review",
                "skill_ids": [],
                "goal": "The creator checks the result before anything is rendered.",
                "optional": False,
                "manual": True,
                "impl_status": "real",
            }
        )
    return stages


def _steps_from_stages(stages: Any) -> list[dict[str, Any]]:
    """Blueprint stages become workflow steps, linked by `needs`."""
    if isinstance(stages, dict):
        stages = list(stages.values())
    steps = _normalise_stages(list(stages or []))
    keys = [step["key"] for step in steps]
    for position, step in enumerate(steps):
        # Each step needs the previous one, so ordering is enforced by the graph.
        step["needs"] = [keys[position - 1]] if position else []
    return steps


def _normalise_stages(stages: Sequence[Any]) -> list[dict[str, Any]]:
    """Flatten stages into JSON-safe dicts.

    Callers may pass Pydantic models or plain dicts, and `impl_status` may still
    be an enum here; the JSON column cannot store either, so everything is
    coerced once, in one place. A stage with no skills is kept only when it is
    explicitly `manual` — otherwise it is a stage that could never run.
    """
    normalised: list[dict[str, Any]] = []
    for position, stage in enumerate(stages):
        fields = stage if isinstance(stage, dict) else stage.model_dump()
        skill_ids = [str(s) for s in (fields.get("skill_ids") or []) if has_skill(str(s))]
        manual = bool(fields.get("manual"))
        if not skill_ids and not manual:
            continue
        normalised.append(
            {
                "key": str(fields.get("key") or f"stage_{position + 1}")[:64],
                "title": str(fields.get("title") or skill_ids[0].replace(".", " ") if skill_ids else "Creator review")[:200],
                "skill_ids": skill_ids,
                "goal": fields.get("goal"),
                "optional": bool(fields.get("optional")),
                "manual": manual,
                "impl_status": _as_value(fields.get("impl_status"))
                or (_impl_status(skill_ids[0]) if skill_ids else "real"),
            }
        )
    return normalised


def _stage_skill_ids(stage: Any) -> list[Any]:
    fields = stage if isinstance(stage, dict) else stage.model_dump()
    return list(fields.get("skill_ids") or [])


def _as_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value



def _impl_status(skill_id: str) -> str:
    from app.modules.skills.registry import get_spec

    spec = get_spec(skill_id)
    return spec.status if spec is not None else "real"


def _unlock_next(db: Session, workflow: Workflow) -> None:
    """Unlock the first step whose prerequisites are satisfied."""
    done = {step.key for step in workflow.steps if step.status in (StepStatus.done, StepStatus.skipped)}
    for step in sorted(workflow.steps, key=lambda s: s.position):
        if step.status is StepStatus.locked and all(need in done for need in (step.needs or [])):
            step.status = StepStatus.ready
            workflow.current_step_id = step.id
            db.add(step)
            break
    if all(step.status in (StepStatus.done, StepStatus.skipped) for step in workflow.steps):
        workflow.status = "complete"
    db.add(workflow)


def _owned_blueprint(
    db: Session, *, owner_id: uuid.UUID, blueprint_id: uuid.UUID
) -> CreationBlueprint | None:
    return db.execute(
        select(CreationBlueprint)
        .join(Project, Project.id == CreationBlueprint.project_id)
        .where(CreationBlueprint.id == blueprint_id, Project.owner_id == owner_id)
    ).scalar_one_or_none()


def _uuid(value: uuid.UUID | str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFoundError("Not found.", details={"field": field}) from exc


def ensure_no_active_conflict(db: Session, *, owner_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Guard against two live workflows on one project (WORKFLOW-ENGINE.md §2)."""
    active = db.execute(
        select(Workflow).where(
            Workflow.project_id == project_id, Workflow.status == "active"
        )
    ).scalars().first()
    if active is not None:
        raise ConflictError(
            "This project already has an active workflow.",
            details={"workflow_id": str(active.id)},
        )
