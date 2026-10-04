"""`ffprobe` wrapper (VIDEO-PIPELINE.md §1, AGENTS.md §13).

Rules enforced here so no caller has to remember them:
- argument arrays only, never a shell string, so a filename cannot inject a flag;
- a `timeout` on every subprocess;
- absence of the binary is reported, not raised, so a stage can degrade honestly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Never let a probe hang a worker slot.
PROBE_TIMEOUT_S = 30.0
#: Defensive cap: a malformed file should not return megabytes of JSON.
MAX_PROBE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """The measured facts about a media file."""

    duration_s: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def aspect(self) -> str | None:
        if not self.width or not self.height:
            return None
        ratio = self.width / self.height
        for name, target in (("9:16", 9 / 16), ("16:9", 16 / 9), ("1:1", 1.0)):
            if abs(ratio - target) < 0.02:
                return name
        return f"{self.width}:{self.height}"

    @property
    def is_portrait(self) -> bool:
        return bool(self.width and self.height and self.height > self.width)


@dataclass(frozen=True, slots=True)
class ProbeUnavailable:
    """Returned instead of raising when the binary or the file cannot be read."""

    reason: str
    command: str = ""

    @property
    def available(self) -> bool:
        return False


@lru_cache(maxsize=1)
def ffmpeg_available() -> bool:
    """Whether ffmpeg can actually run, checked once per process."""
    return _which(settings.ffmpeg_bin) is not None


@lru_cache(maxsize=1)
def ffprobe_available() -> bool:
    return _which(settings.ffprobe_bin) is not None


def probe(path: str | Path) -> MediaInfo | ProbeUnavailable:
    """Measure duration, dimensions and codecs. Never raises for a media problem."""
    binary = _which(settings.ffprobe_bin)
    if binary is None:
        return ProbeUnavailable(reason="ffprobe_not_installed", command=settings.ffprobe_bin)
    target = Path(path)
    if not target.is_file():
        return ProbeUnavailable(reason="file_not_found", command=str(target))

    argv = [
        binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(target),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - argument array, no shell
            argv,
            capture_output=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out for %s", target.name)
        return ProbeUnavailable(reason="ffprobe_timeout", command=" ".join(argv[:2]))
    except OSError as exc:
        logger.warning("ffprobe could not run: %s", exc)
        return ProbeUnavailable(reason="ffprobe_not_executable", command=settings.ffprobe_bin)

    if completed.returncode != 0:
        # The stderr text can echo the file path; log only the exit code.
        logger.warning("ffprobe exited %s for %s", completed.returncode, target.name)
        return ProbeUnavailable(reason="unreadable_media", command=" ".join(argv[:2]))
    if len(completed.stdout) > MAX_PROBE_BYTES:
        return ProbeUnavailable(reason="probe_output_too_large", command=" ".join(argv[:2]))

    try:
        payload = json.loads(completed.stdout or b"{}")
    except json.JSONDecodeError:
        return ProbeUnavailable(reason="probe_output_unparseable", command=" ".join(argv[:2]))

    duration = _duration_from(payload)
    if duration <= 0:
        return ProbeUnavailable(reason="no_duration_reported", command=" ".join(argv[:2]))
    return _to_info(payload, duration)


def _to_info(payload: dict[str, Any], duration: float) -> MediaInfo:
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return MediaInfo(
        duration_s=round(float(duration), 3),
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=_parse_rate(video.get("avg_frame_rate") if video else None),
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name")) if video else None,
        audio_codec=str(audio.get("codec_name")) if audio else None,
        raw=payload,
    )


def _duration_from(payload: dict[str, Any]) -> float:
    raw = (payload.get("format") or {}).get("duration")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _parse_rate(value: Any) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, _, denominator = value.partition("/")
    try:
        divisor = float(denominator)
        return round(float(numerator) / divisor, 3) if divisor else None
    except ValueError:
        return None


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def unavailable_reason() -> str:
    """A single string for the UI when media tooling is missing."""
    if not ffprobe_available():
        return "ffprobe_not_installed"
    if not ffmpeg_available():
        return "ffmpeg_not_installed"
    return ""
