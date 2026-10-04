"""Deterministic media measurement: probe, scene detection, EDL compilation.

The submodules are exported rather than their same-named functions: a package
attribute called `probe` must stay the module, otherwise `from app.core.media
import probe` silently changes meaning depending on import order.
"""

from app.core.media import edl_compiler, probe, render, scenes
from app.core.media.probe import MediaInfo, ProbeUnavailable
from app.core.media.probe import probe as probe_media
from app.core.media.scenes import SceneBoundary, SceneQuality

__all__ = [
    "MediaInfo",
    "ProbeUnavailable",
    "SceneBoundary",
    "SceneQuality",
    "detect_scenes",
    "edl_compiler",
    "ffmpeg_available",
    "ffprobe_available",
    "probe",
    "probe_media",
    "render",
    "sample_frames",
    "scenes",
    "scene_quality",
    "unavailable_reason",
]


def __getattr__(name: str):
    """Delegate the convenience names to the submodules that own them."""
    if name in {
        "detect_scenes",
        "sample_frames",
        "scene_quality",
    }:
        return getattr(scenes, name)
    if name in {"ffmpeg_available", "ffprobe_available", "unavailable_reason"}:
        return getattr(probe, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
