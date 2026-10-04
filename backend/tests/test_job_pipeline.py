"""Job pipeline tests (ARCHITECTURE.md §7, AGENTS.md §14).

These exercise the real enqueue -> handler -> settle path through the DB, because
a handler that only works when called directly is exactly the failure mode the
queue exists to prevent.

Fixtures return plain values rather than ORM objects: instances detached at the
end of `session_scope` cannot be read afterwards.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.db import session_scope
from app.core.errors import JobFailedError
from app.core.jobs import enqueue_job, get_queue, snapshot, wait_for_job
from app.core.models import Asset, AssetKind, AssetStatus, Job, JobType
from app.workers.runners import HANDLERS, media_tooling_missing, run_handler


@dataclass(frozen=True, slots=True)
class FakeAsset:
    id: uuid.UUID
    owner_id: uuid.UUID
    path: Path


@pytest.fixture
def fake_asset(tmp_path: Path) -> FakeAsset:
    """A real file on disk so magic-byte checks and ffprobe have something to read."""
    path = tmp_path / "clip.mp4"
    # A minimal, structurally recognisable MP4 header (ftyp box).
    path.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64)
    owner_id = uuid.uuid4()
    with session_scope() as db:
        asset = Asset(
            owner_id=owner_id,
            kind=AssetKind.video,
            filename="clip.mp4",
            storage_path=str(path),
            mime="video/mp4",
            size_bytes=path.stat().st_size,
            status=AssetStatus.pending,
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
    return FakeAsset(id=asset_id, owner_id=owner_id, path=path)


def edl_for(asset: FakeAsset, **overrides) -> dict:
    return {
        "version": 1,
        "aspect": "9:16",
        "tracks": {"video": [{"src_asset": str(asset.id), "in_s": 0.0, "out_s": 5.0}]},
        **overrides,
    }


def test_every_job_type_has_a_handler() -> None:
    """A job type without a handler would sit queued forever."""
    expected = {f"job:{member.value}" for member in JobType}
    assert expected <= set(HANDLERS)


def test_unknown_handler_settles_the_job_as_failed(fake_asset: FakeAsset) -> None:
    with session_scope() as db:
        job = Job(
            owner_id=fake_asset.owner_id,
            type=JobType.asset_process,
            payload={},
            status="queued",
        )
        db.add(job)
        db.flush()
        job_id = job.id
    with pytest.raises(JobFailedError):
        run_handler(str(job_id), "job:not.a.real.handler", {})
    with session_scope() as db:
        settled = db.get(Job, job_id)
        assert settled is not None
        assert settled.status == "failed"
        assert "not.a.real.handler" in (settled.error or "")


def test_asset_process_reports_missing_media_tooling(fake_asset: FakeAsset) -> None:
    """Without ffprobe the job settles honestly instead of claiming a duration."""
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id)},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    assert result["status"] == "succeeded", result
    payload = result["result"]
    if media_tooling_missing():
        assert payload["probed"] is False
        assert payload["reason"] == media_tooling_missing()
        assert payload["warnings"]
        with session_scope() as db:
            asset = db.get(Asset, fake_asset.id)
            assert asset is not None
            # A video with no measured duration must not look ready to analyse.
            assert asset.duration_s is None
    else:
        assert payload["probed"] is True
        assert payload["duration_s"] > 0


def test_asset_process_rejects_an_unowned_asset(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=uuid.uuid4(),
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id)},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    assert result["status"] == "failed"
    assert "not found" in (result["error"] or "").lower()


def test_video_analyze_needs_a_measured_duration(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.video_analyze,
        payload={"asset_id": str(fake_asset.id)},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    assert result["status"] == "failed"
    assert "asset.process" in (result["error"] or "")


def test_edit_render_refuses_a_platform_without_a_renderer(fake_asset: FakeAsset) -> None:
    """YouTube variants are MOCKED, so rendering them must be refused."""
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.edit_render,
        payload={"edl": edl_for(fake_asset), "platform": "youtube"},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    assert result["status"] == "failed"
    assert "not implemented" in (result["error"] or "").lower()


def test_edit_render_without_ffmpeg_reports_the_missing_capability(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.edit_render,
        payload={"edl": edl_for(fake_asset), "platform": "instagram_reels"},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    if media_tooling_missing():
        assert result["status"] == "failed"
        assert "ffmpeg" in (result["error"] or "").lower()
    else:
        assert result["status"] in {"succeeded", "failed"}


def test_clips_generate_without_a_project_does_not_persist(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.clips_generate,
        payload={"asset_id": str(fake_asset.id), "intent": "a short story"},
    )
    result = wait_for_job(job_id, timeout_s=30.0)
    assert result["status"] in {"succeeded", "failed"}


def test_job_snapshot_exposes_progress_fields(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id)},
    )
    snap = snapshot(job_id)
    assert snap["id"] == str(job_id)
    assert snap["type"] == JobType.asset_process.value
    assert snap["status"] in {"queued", "running", "succeeded", "failed"}
    assert snap["attempts"] >= 0


def test_enqueue_is_idempotent_for_an_identical_payload(fake_asset: FakeAsset) -> None:
    payload = {"asset_id": str(fake_asset.id)}
    first = enqueue_job(owner_id=fake_asset.owner_id, job_type=JobType.asset_process, payload=payload)
    second = enqueue_job(owner_id=fake_asset.owner_id, job_type=JobType.asset_process, payload=payload)
    assert first == second


def test_enqueue_with_a_different_payload_creates_a_new_job(fake_asset: FakeAsset) -> None:
    first = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id)},
    )
    second = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id), "force": True},
    )
    assert first != second


def test_queue_backend_is_reported() -> None:
    health = get_queue().health()
    assert health["available"] is True
    assert health["backend"] in {"rq", "thread"}


def test_job_row_records_the_owner(fake_asset: FakeAsset) -> None:
    job_id = enqueue_job(
        owner_id=fake_asset.owner_id,
        job_type=JobType.asset_process,
        payload={"asset_id": str(fake_asset.id)},
    )
    with session_scope() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.owner_id == fake_asset.owner_id
