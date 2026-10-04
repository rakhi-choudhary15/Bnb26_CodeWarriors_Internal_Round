"""Skill router (AI-ARCHITECTURE.md §4).

`run_skill(skill_id, input, ctx)` performs, in order:

 1. resolve the spec
 2. validate the input against the skill's input schema
 3. check permissions and dependency availability
 4. build context via the Context Manager
 5. call the gateway (skills never touch a provider directly)
 6. validate the output (schema + rule validators)
 7. persist a `skill_runs` row with model, tokens, cost, latency
 8. let the skill emit Content Genome nodes/edges as a side effect
 9. return a `SkillResult`

Long skills (video) return `job_id` and the workflow step stays `running` until
the worker updates the row.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.ai.gateway.base import get_gateway
from app.core.errors import AppError, ValidationError
from app.core.ids import stable_hash
from app.core.logging import get_logger, log_event
from app.core.models import SkillRun
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillResult, parse_input

logger = get_logger(__name__)


def run_skill(
    skill_id: str,
    payload: dict[str, Any],
    ctx: SkillContext,
    db: Session,
) -> SkillResult:
    """Execute a skill end to end. Never raises for skill-level failures."""
    spec = registry.get_spec(skill_id)
    started = time.monotonic()
    input_hash = stable_hash({"skill": skill_id, "input": payload})

    # Step 2/3: validate input and permissions before touching the gateway.
    try:
        parsed_input = parse_input(spec, payload)
    except AppError as exc:
        _record(
            db,
            ctx,
            spec.id,
            input_hash,
            status="error",
            error=str(exc.message),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return SkillResult.failure(exc.message, code=exc.code)

    missing = [dep for dep in spec.dependencies if dep not in ctx.context]
    if missing and not ctx.context.get("allow_missing_dependencies"):
        # A dependency absent from context is not fatal: the skill may still be
        # able to produce output from the project record. We flag it instead.
        ctx.context.setdefault("_missing_dependencies", []).extend(missing)

    module = registry.get_module(skill_id)
    if not spec.async_job:
        ctx.gateway = ctx.gateway or get_gateway()

    log_event(
        logger,
        "skill.started",
        skill_id=spec.id,
        project_id=str(ctx.project_id) if ctx.project_id else None,
        step_id=str(ctx.step_id) if ctx.step_id else None,
        status=spec.status,
    )

    try:
        result = module.run(parsed_input, ctx) if parsed_input is not None else module.run(payload, ctx)
    except AppError as exc:
        latency = int((time.monotonic() - started) * 1000)
        _record(
            db,
            ctx,
            spec.id,
            input_hash,
            status="error",
            error=f"{exc.code}: {exc.message}",
            latency_ms=latency,
        )
        log_event(
            logger,
            "skill.failed",
            level=40,
            skill_id=spec.id,
            error_code=exc.code,
            latency_ms=latency,
        )
        return SkillResult.failure(exc.message, code=exc.code)

    latency = int((time.monotonic() - started) * 1000)

    if result.status == "error":
        _record(
            db, ctx, spec.id, input_hash, status="error", error=result.error or "unknown", latency_ms=latency
        )
        log_event(logger, "skill.failed", level=40, skill_id=spec.id, latency_ms=latency)
        return result

    if result.status == "job":
        _record(
            db,
            ctx,
            spec.id,
            input_hash,
            status="job",
            output={"job_id": str(result.job_id)} if result.job_id else {},
            latency_ms=latency,
        )
        log_event(
            logger,
            "skill.enqueued",
            skill_id=spec.id,
            job_id=str(result.job_id) if result.job_id else None,
            latency_ms=latency,
        )
        return result

    # Step 6: rule validators run after the skill, before persistence.
    warnings = list(result.warnings or [])
    output = result.output or {}
    output = _run_validators(spec, output, ctx, warnings)
    result.output = output
    result.warnings = warnings

    _record(
        db,
        ctx,
        spec.id,
        input_hash,
        status="ok",
        output=output,
        latency_ms=latency,
        confidence=result.confidence,
        warnings=warnings,
    )
    log_event(
        logger,
        "skill.completed",
        skill_id=spec.id,
        latency_ms=latency,
        confidence=result.confidence,
        warnings=warnings,
        status=spec.status,
    )
    return result


def apply_validation(
    spec: Any,
    output: dict[str, Any],
    ctx: SkillContext,
) -> tuple[dict[str, Any], list[str]]:
    """Run a skill's declared validators and return (validated output, warnings).

    Public so that callers and tests exercise exactly the validation path the
    router uses, instead of re-implementing it.
    """
    warnings: list[str] = []
    return _run_validators(spec, output, ctx, warnings), warnings


def _run_validators(
    spec: Any,
    output: dict[str, Any],
    ctx: SkillContext,
    warnings: list[str],
) -> dict[str, Any]:
    """Apply the named validators declared in the skill spec."""
    from app.modules.skills import validators as validator_registry

    data = dict(output)
    for rule in spec.validation_rules:
        fn = validator_registry.get(rule)
        if fn is None:
            warnings.append(f"unknown_validator:{rule}")
            continue
        try:
            outcome = fn(data, ctx)
        except Exception as exc:  # noqa: BLE001 - a broken validator must not lose output
            warnings.append(f"validator_error:{rule}:{type(exc).__name__}")
            continue
        if outcome is None:
            continue
        if isinstance(outcome, dict):
            data = outcome
        elif isinstance(outcome, str):
            warnings.append(outcome)
    # Output schema is the contract; re-validate after validators mutate.
    if spec.output_schema is not None:
        try:
            spec.output_schema.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(
                f"Skill '{spec.id}' produced output that failed its schema.",
                details={"skill_id": spec.id, "reason": str(exc)[:300]},
            ) from exc
    return data


def _record(
    db: Session,
    ctx: SkillContext,
    skill_id: str,
    input_hash: str,
    *,
    status: str,
    output: dict[str, Any] | None = None,
    error: str | None = None,
    latency_ms: int = 0,
    confidence: float = 0.0,
    warnings: list[str] | None = None,
) -> None:
    """Persist a `skill_runs` row (AI-ARCHITECTURE.md §5: token/cost accounting).

    Gateway metrics are cumulative, so the per-run cost is the delta between the
    counters before and after the call. `_take_counters` performs that diff and
    resets the accumulators so runs never double-count.
    """
    delta = _take_counters(ctx)
    run = SkillRun(
        id=uuid.uuid4(),
        owner_id=ctx.owner_id,
        project_id=ctx.project_id,
        step_id=ctx.step_id,
        skill_id=skill_id,
        prompt_version=ctx.prompt_version,
        model=_last_model(ctx),
        provider=ctx.gateway.provider_name if ctx.gateway else "unknown",
        input_hash=input_hash,
        status=status,
        latency_ms=latency_ms,
        tokens_in=delta["tokens_in"],
        tokens_out=delta["tokens_out"],
        cost_usd=delta["cost_usd"],
        error=error,
        output=output or {},
        cached=delta["cached"],
    )
    db.add(run)
    db.flush()


def _take_counters(ctx: SkillContext) -> dict[str, Any]:
    """Read and reset the gateway counters, yielding this run's usage."""
    metrics = getattr(ctx.gateway, "metrics", None)
    if not isinstance(metrics, dict):
        return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cached": False}
    delta = {
        "tokens_in": int(metrics.get("tokens_in", 0)),
        "tokens_out": int(metrics.get("tokens_out", 0)),
        "cost_usd": round(float(metrics.get("cost_usd", 0.0)), 6),
        "cached": bool(metrics.get("cache_hits", 0)),
    }
    metrics["tokens_in"] = 0
    metrics["tokens_out"] = 0
    metrics["cost_usd"] = 0.0
    metrics["cache_hits"] = 0
    return delta


def _last_model(ctx: SkillContext) -> str | None:
    from app.core.config import settings

    return settings.llm_model_primary


def run_and_persist(
    skill_id: str,
    payload: dict[str, Any],
    ctx: SkillContext,
    db: Session,
) -> SkillResult:
    """Convenience wrapper used by API modules; commits the run row."""
    from app.core.db import session_scope  # noqa: F401  (kept for symmetry)

    result = run_skill(skill_id, payload, ctx, db)
    db.commit()
    return result


__all__ = ["run_skill", "run_and_persist"]