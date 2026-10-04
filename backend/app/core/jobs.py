"""Job queue abstraction (ARCHITECTURE.md §7).

RQ over Redis is the documented production backend. When no Redis server is
reachable the same interface is served by a small threaded worker pool that
writes identical progress into the `jobs` table, so the polling API, the
retry/resume semantics and the UI behave identically (D-021).

Contract for every backend:
    enqueue(job_id, type, payload) -> None
    get(job_id) -> JobSnapshot
Jobs progress through the DB, which is the single source of truth
(AGENTS.md §15); the queue only decides *when* work runs.
"""

from __future__ import annotations

import abc
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import session_scope
from app.core.errors import ConflictError, JobFailedError, NotFoundError
from app.core.logging import get_logger, log_event
from app.core.models import Job, JobStatus, JobType

logger = get_logger(__name__)

JobHandler = Callable[["JobContext"], dict[str, Any] | None]

#: Total stage count used to convert `stage_index` into a percentage.
STAGE_WEIGHTS: dict[str, int] = {
    JobType.asset_process.value: 2,
    JobType.video_analyze.value: 11,
    JobType.clips_generate.value: 2,
    JobType.edit_render.value: 3,
    JobType.reference_analyze.value: 6,
    JobType.archaeology_scan.value: 3,
    JobType.genome_propagate.value: 1,
    JobType.dna_learn.value: 1,
}


@dataclass(slots=True)
class JobContext:
    """Passed to every handler. Handlers never touch the queue directly."""

    job_id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None
    type: str
    payload: dict[str, Any]

    def progress(self, stage: str, fraction: float | None = None) -> None:
        """Report progress. `fraction` is 0..1 within the overall job."""
        update_job_progress(
            self.job_id,
            stage=stage,
            progress=fraction if fraction is not None else None,
            stage_weight_total=STAGE_WEIGHTS.get(self.type, 1),
        )

    def log(self, event: str, **fields: Any) -> None:
        log_event(logger, event, job_id=str(self.job_id), job_type=self.type, **fields)


# ---------------------------------------------------------------------------
# Job record helpers (shared by every backend)
# ---------------------------------------------------------------------------
def create_job(
    *,
    owner_id: uuid.UUID,
    job_type: JobType | str,
    payload: dict[str, Any],
    project_id: uuid.UUID | None = None,
    input_hash: str = "",
    db: Session | None = None,
) -> uuid.UUID:
    """Insert a `queued` job row and return its id.

    Returns the id rather than the ORM instance: the row is detached once the
    session closes, so handing the object back invites a `DetachedInstanceError`
    in every caller that touches it afterwards.

    `db` lets a caller that already has a transaction write the row inside it.
    Without it a second connection is opened, which deadlocks against SQLite and
    splits a request's work across two transactions.
    """
    from app.core.ids import stable_hash

    resolved_type = job_type.value if isinstance(job_type, JobType) else str(job_type)
    payload_hash = input_hash or stable_hash({"type": resolved_type, "payload": payload})
    job_id = uuid.uuid4()
    row = Job(
        id=job_id,
        owner_id=owner_id,
        project_id=project_id,
        type=resolved_type,  # type: ignore[arg-type]
        status=JobStatus.queued,
        stage="queued",
        progress=0.0,
        input_hash=payload_hash,
        payload=payload,
    )
    if db is not None:
        db.add(row)
        db.flush()
    else:
        with session_scope() as own_db:
            own_db.add(row)
    log_event(
        logger,
        "job.created",
        job_id=str(job_id),
        job_type=resolved_type,
        owner=str(owner_id),
    )
    return job_id


def get_job_record(job_id: uuid.UUID | str) -> Job:
    with session_scope() as db:
        job = db.get(Job, uuid.UUID(str(job_id)))
        if job is None:
            raise NotFoundError("Job not found.", details={"job_id": str(job_id)})
        db.expunge(job)
        return job


def update_job_progress(
    job_id: uuid.UUID,
    *,
    stage: str | None = None,
    progress: float | None = None,
    stage_weight_total: int = 1,
    result: dict[str, Any] | None = None,
) -> None:
    """Update job status/progress. Safe to call from any thread."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        elif stage is not None:
            job.progress = max(job.progress, 0.05)
        if result is not None:
            job.result = result
        db.add(job)


def mark_job_running(job_id: uuid.UUID) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.running
            job.stage = "running"
            job.started_at = datetime.now(UTC)
            job.attempts += 1
            db.add(job)


def mark_job_succeeded(job_id: uuid.UUID, result: dict[str, Any] | None = None) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.succeeded
        job.stage = "done"
        job.progress = 1.0
        job.finished_at = datetime.now(UTC)
        if result is not None:
            job.result = result
        db.add(job)
    log_event(logger, "job.succeeded", job_id=str(job_id))


def cancel_job(job_id: uuid.UUID) -> None:
    """Cancel a queued job.

    Only a job the worker has not picked up can be cancelled: once it is running
    the worker owns it, and pretending otherwise would leave the row claiming
    `cancelled` while the work keeps going (AGENTS.md §15).
    """
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise NotFoundError("Job not found.", details={"job_id": str(job_id)})
        if job.status is JobStatus.running:
            raise ConflictError(
                "That job is already running.",
                details={"job_id": str(job_id), "status": job.status.value},
            )
        if job.status in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
            raise ConflictError(
                "That job has already finished.",
                details={"job_id": str(job_id), "status": job.status.value},
            )
        job.status = JobStatus.cancelled
        job.stage = "cancelled"
        job.finished_at = datetime.now(UTC)
        db.add(job)
    log_event(logger, "job.cancelled", job_id=str(job_id))


def mark_job_failed(job_id: uuid.UUID, error: str) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.failed
        job.stage = "failed"
        job.error = error[:4000]
        job.finished_at = datetime.now(UTC)
        db.add(job)
    log_event(logger, "job.failed", job_id=str(job_id), level_name="error")


def snapshot(job_id: uuid.UUID) -> dict[str, Any]:
    job = get_job_record(job_id)
    return {
        "id": str(job.id),
        "type": job.type if isinstance(job.type, str) else job.type.value,
        "status": job.status.value,
        "stage": job.stage,
        "progress": job.progress,
        "error": job.error,
        "result": job.result,
        "attempts": job.attempts,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@dataclass(frozen=True, slots=True)
class JobRef:
    """The identifying fields of a job, safe to use after its session closes."""

    id: uuid.UUID
    status: JobStatus


def find_job_by_hash(input_hash: str, *, db: Session | None = None) -> JobRef | None:
    """Idempotency lookup (API-SPECIFICATION.md Idempotency section).

    Reads only the two columns it needs, so the returned `JobRef` stays valid
    after the session closes. Pass `db` to read inside a caller's transaction.
    """
    if not input_hash:
        return None

    def _query(session: Session) -> Any:
        return session.execute(
            select(Job.id, Job.status)
            .where(Job.input_hash == input_hash)
            .order_by(Job.created_at.desc())
        ).first()

    if db is not None:
        row = _query(db)
    else:
        with session_scope() as own_db:
            row = _query(own_db)
    if row is None:
        return None
    return JobRef(id=row[0], status=row[1])


# ---------------------------------------------------------------------------
# Queue backends
# ---------------------------------------------------------------------------
class JobQueue(abc.ABC):
    name: str

    @abc.abstractmethod
    def enqueue(self, job_id: uuid.UUID, handler_name: str, payload: dict[str, Any]) -> None: ...

    @abc.abstractmethod
    def start_worker(self) -> None:
        """Begin consuming (used by the dedicated worker entrypoint)."""

    def health(self) -> dict[str, Any]:
        return {"backend": self.name, "available": True}


class ThreadedQueue(JobQueue):
    """In-process worker pool (D-021).

    Each job runs on a daemon thread with its own DB session. This keeps the
    documented async semantics — the API returns 202 immediately and the UI polls
    `GET /api/jobs/:id` — without requiring a Redis server.
    """

    name = "thread"

    def __init__(self, workers: int = 4) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._executor: ThreadPoolExecutorLike | None = None
        self._workers = workers
        self._started = False
        self._lock = threading.Lock()
        self._pending: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    def register(self, name: str, handler: JobHandler) -> None:
        self._handlers[name] = handler

    def enqueue(self, job_id: uuid.UUID, handler_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._pending.append((job_id, handler_name, payload))
            should_start = not self._started
        if should_start:
            self.start_worker()
        else:
            self._drain()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                job_id, handler_name, payload = self._pending.pop(0)
            executor = self._executor
            if executor is None:
                return
            executor.submit(self._run, job_id, handler_name, payload)

    def _run(self, job_id: uuid.UUID, handler_name: str, payload: dict[str, Any]) -> None:
        handler = self._handlers.get(handler_name)
        if handler is None:
            mark_job_failed(job_id, f"No handler registered for '{handler_name}'.")
            return
        job = get_job_record(job_id)
        if job.status is JobStatus.cancelled:
            # Cancelled while it sat in the pool; nothing should have run.
            logger.info("Skipping cancelled job %s", job_id)
            return
        mark_job_running(job_id)
        ctx = JobContext(
            job_id=job.id,
            owner_id=job.owner_id,
            project_id=job.project_id,
            type=job.type if isinstance(job.type, str) else job.type.value,
            payload={**job.payload, **(payload or {})},
        )
        try:
            result = handler(ctx) or {}
            mark_job_succeeded(job_id, result)
        except Exception as exc:  # noqa: BLE001 - surfaced as job failure
            logger.error("Job handler raised: %s", type(exc).__name__, exc_info=False)
            traceback.print_exc()
            mark_job_failed(job_id, f"{type(exc).__name__}: {exc}")
        finally:
            self._drain()

    def start_worker(self) -> None:
        if self._started:
            return
        self._executor = ThreadPoolExecutorLike(max_workers=self._workers, name="job")
        self._started = True
        self._drain()

    def drain_for_tests(self, timeout: float = 30.0) -> None:
        """Block until every enqueued job settles. Test-only convenience."""
        executor = self._executor
        if executor is None:
            return
        executor.wait_for(timeout)


class ThreadPoolExecutorLike:
    """Minimal thread pool; avoids importing concurrent.futures in the API path."""

    def __init__(self, max_workers: int, name: str) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
        self._futures: list[Any] = []

    def submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        fut = self._pool.submit(fn, *args)
        self._futures.append(fut)
        return fut

    def wait_for(self, timeout: float) -> None:
        from concurrent.futures import wait as _wait

        _wait(list(self._futures), timeout=timeout)


class RQQueue(JobQueue):
    """Redis + RQ backend used when `REDIS_URL` is configured."""

    name = "rq"

    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.redis_url = redis_url
        self.queue_name = queue_name
        self._queue: Any | None = None

    def _get_queue(self) -> Any | None:
        if self._queue is None:
            try:
                from redis import Redis
                from rq import Queue

                conn = Redis.from_url(self.redis_url)
                conn.ping()
                self._queue = Queue(self.queue_name, connection=conn)
            except Exception as exc:  # noqa: BLE001
                logger.warning("RQ unavailable, falling back to thread queue: %s", exc)
                self._queue = None
        return self._queue

    def enqueue(self, job_id: uuid.UUID, handler_name: str, payload: dict[str, Any]) -> None:
        queue = self._get_queue()
        if queue is None:
            # Redis went away after startup. Hand the job to the in-process pool
            # rather than dropping it: the job row is already queued in the DB.
            logger.warning("RQ lost connection; enqueueing %s on the thread queue", handler_name)
            get_thread_queue().enqueue(job_id, handler_name, payload)
            return
        queue.enqueue(
            "app.workers.runners.run_handler",
            kwargs={"job_id": str(job_id), "handler_name": handler_name, "payload": payload},
            job_timeout=1800,
            retry=[10, 60, 300],
        )

    def start_worker(self) -> None:
        """Block consuming this queue with a real RQ worker.

        Run via `python -m app.workers.worker`; the API process never calls this,
        so a missing worker surfaces as queued jobs rather than silent no-ops.
        """
        queue = self._get_queue()
        if queue is None:
            raise RuntimeError("Cannot start an RQ worker without a reachable Redis.")
        from app.core.config import settings

        logger.info("RQ worker listening on queue %r", self.queue_name)
        queue.run(
            burst=settings.queue_worker_burst,
            with_scheduler=settings.queue_worker_scheduler,
        )

    def health(self) -> dict[str, Any]:
        return {"backend": self.name, "available": self._get_queue() is not None}


_queue: JobQueue | None = None
_thread_queue: ThreadedQueue | None = None


def get_queue() -> JobQueue:
    """Resolve the queue backend once per process (D-021)."""
    global _queue
    if _queue is not None:
        return _queue
    if settings.queue_backend == "thread":
        _queue = _make_thread_queue()
        return _queue
    if settings.queue_backend == "rq" and settings.redis_url:
        rq_queue = RQQueue(settings.redis_url, settings.queue_name)
        if rq_queue.health()["available"]:
            _queue = rq_queue
            return _queue
        logger.warning("RQ requested but unavailable; using thread queue.")
    elif settings.redis_url:
        # 'auto': prefer Redis only if it actually answers, otherwise stay local.
        rq_queue = RQQueue(settings.redis_url, settings.queue_name)
        if rq_queue.health()["available"]:
            _queue = rq_queue
            return _queue
    _queue = _make_thread_queue()
    return _queue


def get_thread_queue() -> ThreadedQueue:
    """The in-process pool, created on first use.

    Also the fallback target for RQQueue when Redis disappears at runtime.
    """
    return _make_thread_queue()


def _make_thread_queue() -> ThreadedQueue:
    global _thread_queue
    if _thread_queue is None:
        from app.workers.runners import HANDLERS

        _thread_queue = ThreadedQueue(workers=settings.queue_workers)
        for name, handler in HANDLERS.items():
            _thread_queue.register(name, handler)
    return _thread_queue


def _queue_fallback():  # type: ignore[no-untyped-def]
    """Indirect hook so RQQueue can delegate without a circular import."""
    return get_queue()


def set_queue(queue: JobQueue) -> None:
    """Injection point for tests."""
    global _queue, _thread_queue
    _queue = queue
    _thread_queue = None


def enqueue_job(
    *,
    owner_id: uuid.UUID,
    job_type: JobType | str,
    payload: dict[str, Any],
    project_id: uuid.UUID | None = None,
    input_hash: str = "",
    db: Session | None = None,
) -> uuid.UUID:
    """Create the job row and hand it to the queue.

    Returns the existing job id when the same `input_hash` already completed or
    is in flight, which is how `Idempotency-Key` is honoured without a second
    store. Pass `db` when the caller already has a session: the row then joins
    that transaction instead of racing it on a second connection.
    """
    from app.core.ids import stable_hash

    resolved = job_type.value if isinstance(job_type, JobType) else str(job_type)
    payload_hash = input_hash or stable_hash({"type": resolved, "payload": payload})

    if db is not None:
        existing = find_job_by_hash(payload_hash, db=db)
    else:
        existing = find_job_by_hash(payload_hash)
    if existing is not None and existing.status in (JobStatus.queued, JobStatus.running):
        # An identical request is already in flight: reuse it rather than
        # running the same stage twice. A completed job is never reused, because
        # a re-run is a new version of the output (AGENTS.md §15).
        return existing.id

    job_id = create_job(
        owner_id=owner_id,
        job_type=resolved,  # type: ignore[arg-type]
        payload=payload,
        project_id=project_id,
        input_hash=payload_hash,
        db=db,
    )
    get_queue().enqueue(job_id, f"job:{resolved}", payload)
    return job_id


def wait_for_job(job_id: uuid.UUID, timeout_s: float = 60.0) -> dict[str, Any]:
    """Block until a job settles. Used by the synchronous API paths and tests."""
    import time as _time

    deadline = _time.monotonic() + timeout_s
    while _time.monotonic() < deadline:
        snap = snapshot(job_id)
        if snap["status"] in ("succeeded", "failed", "cancelled"):
            return snap
        _time.sleep(0.05)
    raise JobFailedError(
        "Job did not finish in time.", details={"job_id": str(job_id), "timeout_s": timeout_s}
    )


def raise_if_failed(job_id: uuid.UUID) -> None:
    snap = snapshot(job_id)
    if snap["status"] == "failed":
        raise JobFailedError(
            snap.get("error") or "Job failed.", details={"job_id": str(job_id)}
        )


__all__ = [
    "JobContext",
    "JobQueue",
    "ThreadedQueue",
    "create_job",
    "enqueue_job",
    "find_job_by_hash",
    "get_job_record",
    "get_queue",
    "mark_job_failed",
    "mark_job_running",
    "mark_job_succeeded",
    "raise_if_failed",
    "set_queue",
    "snapshot",
    "update_job_progress",
    "wait_for_job",
    "StageStatus",
]


class StageStatus:
    """Named stage states mirrored by the UI checklist (DESIGN-SYSTEM §5)."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"