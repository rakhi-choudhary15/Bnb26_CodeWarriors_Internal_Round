"""FFmpeg execution for a compiled render (VIDEO-PIPELINE.md §3, AGENTS.md §13).

Kept separate from the compiler so the compiler stays pure and testable: this
module is the only place a subprocess is started for rendering.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.core.errors import JobFailedError
from app.core.logging import get_logger
from app.core.media.edl_compiler import RENDER_TIMEOUT_S, RenderPlan, ensure_ffmpeg

logger = get_logger(__name__)

#: A render that produces nothing usable is a failure, not a success.
MIN_OUTPUT_BYTES = 1024


def render_plan(plan: RenderPlan, work_dir: str | Path) -> dict[str, Any]:
    """Run one render and return its bytes plus measured duration.

    Raises `JobFailedError` with a short reason when FFmpeg fails, so the job row
    never claims a render that does not exist.
    """
    ensure_ffmpeg()
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    output = Path(plan.output_path)
    if not output.is_absolute():
        output = directory / output.name

    argv = plan.argv()
    # The plan was built for the job's directory; keep the output path in sync.
    argv[-1] = str(output)

    logger.info("Rendering %s to a %dx%d %s clip", plan.platform, plan.width, plan.height, plan.aspect)
    try:
        completed = subprocess.run(  # noqa: S603 - argument array, never a shell string
            argv,
            capture_output=True,
            timeout=RENDER_TIMEOUT_S,
            cwd=str(directory),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise JobFailedError(
            "Render timed out.", details={"timeout_s": RENDER_TIMEOUT_S}
        ) from exc
    except OSError as exc:
        raise JobFailedError("FFmpeg could not be started.", details={"reason": type(exc).__name__}) from exc

    if completed.returncode != 0 or not output.is_file():
        # FFmpeg's stderr can contain the full command line; log only the code.
        logger.warning("FFmpeg exited %s while rendering", completed.returncode)
        raise JobFailedError(
            "FFmpeg could not render this EDL.",
            details={"exit_code": completed.returncode},
        )

    size = output.stat().st_size
    if size < MIN_OUTPUT_BYTES:
        raise JobFailedError(
            "Render produced an unusably small file.", details={"size_bytes": size}
        )
    data = output.read_bytes()
    output.unlink(missing_ok=True)
    return {"bytes": data, "size_bytes": size, "duration_s": plan.duration_s, "path": str(output)}
