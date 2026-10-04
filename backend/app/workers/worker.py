"""Dedicated worker entrypoint (ARCHITECTURE.md §7).

    python -m app.workers.worker

The API process only enqueues; this process consumes. With Redis configured it
runs a real RQ worker; without it, the in-process thread pool drains queued work,
which keeps a local demo honest about being single-process.
"""

from __future__ import annotations

import sys

from app.core.config import settings
from app.core.jobs import get_queue
from app.core.logging import get_logger
from app.workers.runners import HANDLERS, media_tooling_missing

logger = get_logger(__name__)


def main() -> int:
    queue = get_queue()
    missing = media_tooling_missing()
    if missing:
        # Loud, once, at startup: analysis and rendering will report this reason.
        logger.warning(
            "Media tooling incomplete (%s). Scene detection and rendering will "
            "report the missing capability rather than pretend to succeed.",
            missing,
        )
    logger.info(
        "Worker starting: queue=%s handlers=%d ai_provider=%s auth_mode=%s",
        queue.name,
        len(HANDLERS),
        settings.ai_provider,
        settings.auth_mode,
    )
    try:
        queue.start_worker()
    except KeyboardInterrupt:
        logger.info("Worker interrupted; shutting down.")
    except RuntimeError as exc:
        logger.error("Worker cannot start: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
