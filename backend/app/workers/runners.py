"""Job handlers (ARCHITECTURE.md §7).

This is the only module the queue calls. Handlers are named `job:<JobType>` to
match what `enqueue_job` enqueues, and every handler:

- reports progress through `JobContext`, never by writing the job row directly;
- returns a JSON-serialisable result that becomes `jobs.result`;
- degrades honestly: when a capability is missing the result says so and the
  stored status reflects reality instead of a false success.

Media and AI stages run here rather than in a request because they exceed the
5 s budget (AGENTS.md §8).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.core.db import session_scope
from app.core.errors import ValidationError
from app.core.jobs import (
    JobContext,
    JobFailedError,
    JobHandler,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from app.core.logging import get_logger
from app.core.media import probe as probe_module
from app.core.media.scenes import detect_scenes, scene_quality
from app.core.models import (
    Asset,
    AssetStatus,
    Clip,
    ClipStatus,
    Scene,
    TranscriptSegment,
)
from app.core.storage import cleanup_temp_dir, ensure_temp_dir

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Entry point used by both queue backends
# ---------------------------------------------------------------------------
def run_handler(job_id: str, handler_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one job to completion. This is the RQ entrypoint and the thread path."""
    resolved_id = uuid.UUID(str(job_id))
    handler = HANDLERS.get(handler_name)
    if handler is None:
        mark_job_failed(resolved_id, f"No handler registered for {handler_name!r}.")
        raise JobFailedError(
            "No handler registered for this job type.", details={"handler": handler_name}
        )
    mark_job_running(resolved_id)
    try:
        record = _job_row(resolved_id)
        context = JobContext(
            job_id=resolved_id,
            owner_id=record["owner_id"],
            project_id=record["project_id"],
            type=record["type"],
            payload=payload or {},
        )
        result = handler(context) or {}
        mark_job_succeeded(resolved_id, result)
        return result
    except Exception as exc:  # noqa: BLE001 - the queue must see a settled job
        message = str(exc)[:500] or exc.__class__.__name__
        logger.warning("Job %s (%s) failed: %s", job_id, handler_name, message)
        mark_job_failed(resolved_id, message)
        raise


# ---------------------------------------------------------------------------
# asset.process
# ---------------------------------------------------------------------------
def handle_asset_process(ctx: JobContext) -> dict[str, Any]:
    """Validate and probe an uploaded asset, then mark it ready or rejected."""
    asset_id = _uuid(ctx.payload.get("asset_id"), "asset_id")
    with session_scope() as db:
        asset = db.get(Asset, asset_id)
        # Ownership is checked in the handler as well as the router: a job payload
        # is stored data, so it must never be trusted to name someone else's asset.
        if asset is None or asset.owner_id != ctx.owner_id:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        path = asset.storage_path
        kind = asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind)
        asset.status = AssetStatus.processing
        db.add(asset)

    ctx.progress("probe", 0.2)
    info = probe_module.probe(path)
    if isinstance(info, probe_module.ProbeUnavailable):
        with session_scope() as db:
            asset = db.get(Asset, asset_id)
            if asset is not None:
                asset.status = AssetStatus.ready if kind != "video" else AssetStatus.pending
                asset.status_reason = info.reason
                asset.meta = {**(asset.meta or {}), "probe": {"available": False, "reason": info.reason}}
                db.add(asset)
        return {
            "asset_id": str(asset_id),
            "probed": False,
            "reason": info.reason,
            "warnings": [info.reason],
        }

    ctx.progress("index", 0.8)
    with session_scope() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        asset.duration_s = info.duration_s
        asset.width = info.width
        asset.height = info.height
        asset.status = AssetStatus.ready
        asset.status_reason = None
        asset.meta = {
            **(asset.meta or {}),
            "probe": {
                "available": True,
                "duration_s": info.duration_s,
                "aspect": info.aspect,
                "fps": info.fps,
                "has_audio": info.has_audio,
                "video_codec": info.video_codec,
            },
        }
        db.add(asset)
    return {
        "asset_id": str(asset_id),
        "probed": True,
        "duration_s": info.duration_s,
        "aspect": info.aspect,
        "has_audio": info.has_audio,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# video.analyze
# ---------------------------------------------------------------------------
def handle_video_analyze(ctx: JobContext) -> dict[str, Any]:
    """Detect scenes, measure quality and transcribe.

    Scene detection is deterministic and always attempted; the transcript needs a
    speech-to-text provider, so its absence is reported rather than faked.
    """
    asset_id = _uuid(ctx.payload.get("asset_id"), "asset_id")
    with session_scope() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        path = asset.storage_path
        duration_s = float(asset.duration_s or 0.0)
    if duration_s <= 0:
        raise JobFailedError(
            "Asset has no measured duration; run asset.process first.",
            details={"asset_id": str(asset_id)},
        )

    warnings: list[str] = []
    ctx.progress("scenes", 0.1)
    detected = detect_scenes(path, duration_s)
    if isinstance(detected, str):
        return {
            "asset_id": str(asset_id),
            "scenes": 0,
            "transcript_segments": 0,
            "warnings": [detected],
            "reason": detected,
        }

    ctx.progress("quality", 0.4)
    with session_scope() as db:
        db.query(Scene).filter(Scene.asset_id == asset_id).delete()
        for index, boundary in enumerate(detected):
            quality = scene_quality(path, boundary.start_s, boundary.end_s)
            db.add(
                Scene(
                    asset_id=asset_id,
                    idx=index,
                    start_s=boundary.start_s,
                    end_s=boundary.end_s,
                    quality=quality.to_dict(),
                )
            )

    ctx.progress("transcript", 0.7)
    transcript, transcript_warnings = _transcribe(ctx, asset_id, path)
    warnings.extend(transcript_warnings)

    ctx.progress("captions", 0.9)
    return {
        "asset_id": str(asset_id),
        "scenes": len(detected),
        "transcript_segments": transcript,
        "frames_sampled": 0,
        "warnings": warnings,
    }


def _transcribe(ctx: JobContext, asset_id: uuid.UUID, path: str) -> tuple[int, list[str]]:
    """Speech-to-text through the gateway, if a provider is configured."""
    from app.ai.gateway.base import get_gateway

    try:
        segments = get_gateway().transcribe(path)
    except Exception as exc:  # noqa: BLE001 - no STT provider is a normal state
        logger.info("Transcription unavailable for asset %s: %s", asset_id, exc)
        return 0, ["transcription_unavailable"]
    if not segments:
        return 0, ["no_speech_detected"]

    written = 0
    with session_scope() as db:
        db.query(TranscriptSegment).filter(TranscriptSegment.asset_id == asset_id).delete()
        for index, segment in enumerate(segments):
            start = max(0.0, round(float(segment.get("start_s", 0.0)), 3))
            end = round(float(segment.get("end_s", start)), 3)
            text = str(segment.get("text") or "").strip()
            if not text or end <= start:
                continue
            db.add(
                TranscriptSegment(
                    asset_id=asset_id, idx=index, start_s=start, end_s=end, text=text[:2000]
                )
            )
            written += 1
    return written, []


# ---------------------------------------------------------------------------
# clips.generate
# ---------------------------------------------------------------------------
def handle_clips_generate(ctx: JobContext) -> dict[str, Any]:
    """Run `clip.generate` and persist candidates as reviewable clip rows."""
    from app.ai.gateway.base import get_gateway
    from app.modules.skills.base import SkillContext
    from app.modules.skills.registry import get_module

    asset_id = _uuid(ctx.payload.get("asset_id"), "asset_id")
    project_id = _optional_uuid(ctx.payload.get("project_id"), "project_id")
    platform = str(ctx.payload.get("platform") or "instagram_reels")

    with session_scope() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        duration_s = float(asset.duration_s or 0.0)
        scenes = [
            {
                "start_s": scene.start_s,
                "end_s": scene.end_s,
                "caption": scene.caption,
                "tags": scene.tags or [],
                "quality": scene.quality or {},
            }
            for scene in db.query(Scene)
            .filter(Scene.asset_id == asset_id)
            .order_by(Scene.idx)
            .all()
        ]
        transcript = [
            {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in db.query(TranscriptSegment)
            .filter(TranscriptSegment.asset_id == asset_id)
            .order_by(TranscriptSegment.idx)
            .all()
        ]

    ctx.progress("score", 0.3)
    skill = get_module("clip.generate")
    if skill is None:
        raise JobFailedError("clip.generate is not registered.")
    skill_ctx = SkillContext(
        owner_id=ctx.owner_id,
        project_id=project_id,
        step_id=None,
        skill_id="clip.generate",
        gateway=get_gateway(),
        context={
            "asset": {"id": str(asset_id), "duration_s": duration_s},
            "duration_s": duration_s,
            "intent": str(ctx.payload.get("intent") or ""),
        },
    )
    result = skill.run(
        {
            "asset_id": str(asset_id),
            "duration_s": duration_s,
            "platform": platform,
            "scenes": scenes,
            "transcript": transcript,
            "intent": str(ctx.payload.get("intent") or ""),
        },
        skill_ctx,
    )
    if result.status != "ok" or not result.output:
        raise JobFailedError("Clip generation failed.", details={"warnings": result.warnings})

    ctx.progress("persist", 0.8)
    clips = result.output.get("clips") or []
    if project_id is None:
        return {
            "asset_id": str(asset_id),
            "clips": len(clips),
            "persisted": False,
            "reason": "project_id_required_to_persist_clips",
            "warnings": result.warnings,
        }
    with session_scope() as db:
        for clip in clips:
            db.add(
                Clip(
                    project_id=project_id,
                    owner_id=ctx.owner_id,
                    source_asset_id=asset_id,
                    start_s=float(clip["start_s"]),
                    end_s=float(clip["end_s"]),
                    reason=str(clip.get("reason") or ""),
                    confidence=float(clip.get("confidence") or 0.0),
                    target_platform=platform,
                    status=ClipStatus.candidate,
                    score_breakdown=clip.get("score_breakdown") or {},
                )
            )
    return {
        "asset_id": str(asset_id),
        "clips": len(clips),
        "persisted": True,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# edit.render
# ---------------------------------------------------------------------------
def handle_edit_render(ctx: JobContext) -> dict[str, Any]:
    """Compile an EDL and render it, or report the missing capability."""
    from app.core.media.edl_compiler import (
        compile_edl,
        ensure_ffmpeg,
        write_caption_file,
    )

    edl = dict(ctx.payload.get("edl") or {})
    platform = str(ctx.payload.get("platform") or "instagram_reels")
    if not edl:
        raise ValidationError("Render requested without an EDL.")

    job_dir = ensure_temp_dir(f"job-{ctx.job_id}")
    try:
        ctx.progress("compile", 0.2)
        with session_scope() as db:
            source = _clip_source(db, ctx)
        # Compile before requiring FFmpeg: "this platform has no renderer" is a
        # more useful answer than "ffmpeg is missing", and both are cheap to check.
        plan = compile_edl(
            edl,
            platform=platform,
            output_path="render.mp4",
            has_audio=source["has_audio"],
        )
        ensure_ffmpeg()
        # Local paths address the asset directly; remote storage is staged later.
        plan = _with_sources(plan, source["paths"])
        cues = write_caption_file(
            (edl.get("tracks") or {}).get("captions") or [], job_dir / "edl_captions.ass"
        )
        if cues != plan.caption_cues:
            logger.info(
                "Caption cues differ between plan (%s) and subtitle file (%s)",
                plan.caption_cues,
                cues,
            )

        ctx.progress("render", 0.4)
        from app.core.media.render import render_plan

        rendered = render_plan(plan, job_dir)
        ctx.progress("store", 0.95)
        return {"edl_version": edl.get("version"), "duration_s": plan.duration_s, **_store_render(ctx, rendered)}
    finally:
        cleanup_temp_dir(job_dir)


def _with_sources(plan: Any, paths: dict[str, str]) -> Any:
    """Replace EDL asset ids with real filesystem paths for the render."""
    from dataclasses import replace

    return replace(
        plan,
        inputs=tuple(paths.get(Path(source).name, source) for source in plan.inputs),
    )


def _clip_source(db: Any, ctx: JobContext) -> dict[str, Any]:
    """Resolve every asset behind a render and confirm the caller owns them."""
    from app.core.storage import get_storage

    storage = get_storage()
    references = _edl_asset_ids(ctx.payload.get("edl") or {})
    paths: dict[str, str] = {}
    has_audio = False
    for asset_id in references:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.owner_id != ctx.owner_id:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        local = storage.local_path("assets-original", f"{asset.owner_id}/{asset.id}")
        paths[str(asset.id)] = str(local or asset.storage_path)
        has_audio = has_audio or bool(
            ((asset.meta or {}).get("probe") or {}).get("has_audio")
        )
    if not paths:
        raise ValidationError("Render EDL references no known asset.")
    return {"paths": paths, "has_audio": has_audio}


def _edl_asset_ids(edl: dict[str, Any]) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []
    for track in ((edl.get("tracks") or {}).get("video") or []):
        if not isinstance(track, dict):
            continue
        try:
            found.append(uuid.UUID(str(track.get("src_asset"))))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "EDL references an asset id that is not a UUID.",
                details={"src_asset": str(track.get("src_asset"))[:64]},
            ) from exc
    return found


def _store_render(ctx: JobContext, rendered: dict[str, Any]) -> dict[str, Any]:
    """Move the render into owned storage. The path is never logged."""
    from app.core.storage import get_storage

    data = rendered.pop("bytes", b"")
    key = f"{ctx.owner_id}/{ctx.job_id}.mp4"
    stored = get_storage().write("renders", key, data)
    return {
        "render_key": stored.key,
        "size_bytes": stored.size_bytes,
        "duration_s": rendered.get("duration_s"),
    }


# ---------------------------------------------------------------------------
# Library-wide jobs
# ---------------------------------------------------------------------------
def handle_archaeology_scan(ctx: JobContext) -> dict[str, Any]:
    """Find unused footage. Seeded-only until the vector layer is populated."""
    ctx.progress("scan", 0.5)
    with session_scope() as db:
        unused = (
            db.query(Asset)
            .filter(Asset.owner_id == ctx.owner_id, Asset.status == AssetStatus.ready)
            .all()
        )
    minutes = round(sum(float(a.duration_s or 0.0) for a in unused) / 60.0, 1)
    return {"assets": len(unused), "unused_minutes": minutes, "warnings": ["seeded_scan_only"]}


def handle_dna_learn(ctx: JobContext) -> dict[str, Any]:
    """Update Creator DNA from approved outputs."""
    ctx.progress("aggregate", 0.5)
    return {"updated": False, "reason": "dna.learn_requires_approved_samples", "warnings": []}


def handle_genome_propagate(ctx: JobContext) -> dict[str, Any]:
    """Recompute impact for a content-graph change."""
    ctx.progress("traverse", 0.5)
    return {"impacted": 0, "warnings": ["genome_propagate_requires_a_change_diff"]}


def handle_reference_analyze(ctx: JobContext) -> dict[str, Any]:
    """Measure Reference DNA structure with ffprobe, then summarise with the model."""
    asset_id = _uuid(ctx.payload.get("asset_id"), "asset_id")
    with session_scope() as db:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.owner_id != ctx.owner_id:
            raise JobFailedError("Asset not found.", details={"asset_id": str(asset_id)})
        duration_s = float(asset.duration_s or 0.0)
        path = asset.storage_path
    if duration_s <= 0:
        return {"asset_id": str(asset_id), "analyzed": False, "reason": "asset_not_probed", "warnings": []}

    ctx.progress("structure", 0.5)
    detected = detect_scenes(path, duration_s)
    if isinstance(detected, str):
        return {"asset_id": str(asset_id), "analyzed": False, "reason": detected, "warnings": [detected]}
    shots = len(detected)
    average = round(duration_s / max(1, shots), 2)
    return {
        "asset_id": str(asset_id),
        "analyzed": True,
        "structure": {
            "duration_s": duration_s,
            "shots": {"count": shots, "avg_s": average},
        },
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _job_row(job_id: uuid.UUID) -> dict[str, Any]:
    from app.core.jobs import get_job_record

    job = get_job_record(job_id)
    return {
        "owner_id": job.owner_id,
        "project_id": job.project_id,
        "type": job.type.value if hasattr(job.type, "value") else str(job.type),
    }


def _uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Field must be a UUID.", details={"field": field}) from exc


def _optional_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return _uuid(value, field)


HANDLERS: dict[str, JobHandler] = {
    f"job:{name}": handler
    for name, handler in {
        "asset.process": handle_asset_process,
        "video.analyze": handle_video_analyze,
        "clips.generate": handle_clips_generate,
        "edit.render": handle_edit_render,
        "archaeology.scan": handle_archaeology_scan,
        "dna.learn": handle_dna_learn,
        "genome.propagate": handle_genome_propagate,
        "reference.analyze": handle_reference_analyze,
    }.items()
}


def available_handlers() -> list[str]:
    return sorted(HANDLERS)


def media_tooling_missing() -> str:
    """Reported by `/health` so the UI can explain a degraded stage."""
    return probe_module.unavailable_reason()
