"""Deterministic scene detection and per-scene quality metrics (VIDEO-PIPELINE.md §2).

Scene boundaries are measured here, in code, from frame-to-frame difference. The
model never decides where a scene starts (REFERENCE-DNA.md §3): it only captions
the scenes this module found.

OpenCV is already a dependency, so no scene-detection library is added (D-022).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Analysis stride in frames. Sampling every frame of a 3-minute video is slow
#: and buys nothing: cuts are far longer than this.
ANALYSIS_STRIDE = 6
#: Frame-difference score above which a cut is declared.
CUT_THRESHOLD = 0.32
#: Frames read per second of video, used for the quality pass.
QUALITY_FPS = 1.0


@dataclass(frozen=True, slots=True)
class SceneBoundary:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)


@dataclass(frozen=True, slots=True)
class SceneQuality:
    sharpness: float
    brightness: float
    motion: float
    score: float

    def to_dict(self) -> dict[str, float]:
        return {
            "sharpness": round(self.sharpness, 3),
            "brightness": round(self.brightness, 3),
            "motion": round(self.motion, 3),
            "score": round(self.score, 3),
        }


def detect_scenes(
    path: str | Path, duration_s: float, *, stride: int = ANALYSIS_STRIDE
) -> list[SceneBoundary] | str:
    """Return scene boundaries, or a reason string when detection cannot run.

    Returning the reason instead of raising lets the caller record an honest
    status and let the creator know analysis did not happen.
    """
    target = Path(path)
    if not target.is_file():
        return "file_not_found"
    capture = cv2.VideoCapture(str(target))
    if not capture.isOpened():
        return "video_unreadable"
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0:
            return "fps_unavailable"
        boundaries = _boundaries(capture, fps, duration_s, stride)
    finally:
        capture.release()

    scenes = _merge_short(scenes=boundaries, duration_s=duration_s)
    if not scenes:
        return "no_scenes_detected"
    return scenes[: settings.scene_max_count]


def scene_quality(path: str | Path, start_s: float, end_s: float) -> SceneQuality:
    """Sharpness, brightness and motion for one range.

    Motion is reported as `None`-safe zero when the range has a single frame.
    """
    target = Path(path)
    capture = cv2.VideoCapture(str(target))
    if not capture.isOpened():
        return SceneQuality(sharpness=0.0, brightness=0.0, motion=0.0, score=0.0)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        if fps <= 0:
            return SceneQuality(sharpness=0.0, brightness=0.0, motion=0.0, score=0.0)
        capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        step = max(1, int(fps / QUALITY_FPS))
        sharpness_values: list[float] = []
        brightness_values: list[float] = []
        motion_values: list[float] = []
        previous: np.ndarray | None = None
        index = 0
        deadline = int((end_s - start_s) * fps)
        while index <= deadline and len(sharpness_values) < 60:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            if index % step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharpness_values.append(_sharpness(gray))
                brightness_values.append(float(gray.mean()) / 255.0)
                if previous is not None:
                    motion_values.append(_motion(previous, gray))
                previous = gray
            index += 1
    finally:
        capture.release()

    if not sharpness_values:
        return SceneQuality(sharpness=0.0, brightness=0.0, motion=0.0, score=0.0)
    return SceneQuality(
        sharpness=float(np.mean(sharpness_values)),
        brightness=float(np.mean(brightness_values)),
        motion=float(np.mean(motion_values)) if motion_values else 0.0,
        score=_combined(
            sharpness=float(np.mean(sharpness_values)),
            brightness=float(np.mean(brightness_values)),
            motion=float(np.mean(motion_values)) if motion_values else 0.0,
        ),
    )


def sample_frames(
    path: str | Path, times_s: list[float], *, max_side: int = 512
) -> list[dict[str, Any]]:
    """JPEG bytes for the requested timestamps, honouring the frame cap.

    Returns only the frames it could actually read, so a caller can report the
    real count rather than the requested one.
    """
    wanted = [t for t in times_s[: settings.max_frames_analyzed] if t >= 0]
    if not wanted:
        return []
    target = Path(path)
    capture = cv2.VideoCapture(str(target))
    if not capture.isOpened():
        return []
    frames: list[dict[str, Any]] = []
    try:
        for at_s in wanted:
            capture.set(cv2.CAP_PROP_POS_MSEC, at_s * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            scale = max_side / max(height, width)
            if scale < 1.0:
                frame = cv2.resize(
                    frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
                )
            ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                continue
            frames.append(
                {
                    "t_s": round(float(at_s), 3),
                    "bytes": buffer.tobytes(),
                    "mime": "image/jpeg",
                }
            )
    finally:
        capture.release()
    return frames


def _boundaries(
    capture: cv2.VideoCapture, fps: float, duration_s: float, stride: int
) -> list[SceneBoundary]:
    scenes: list[SceneBoundary] = []
    start_s = 0.0
    previous: np.ndarray | None = None
    index = 0
    total = int(duration_s * fps)
    while index < total:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        if index % stride == 0:
            gray = cv2.resize(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA
            )
            if previous is not None:
                difference = _difference(previous, gray)
                at_s = index / fps
                if difference >= CUT_THRESHOLD and at_s - start_s >= settings.scene_min_duration_s:
                    scenes.append(SceneBoundary(round(start_s, 3), round(at_s, 3)))
                    start_s = at_s
            previous = gray
        index += 1
    scenes.append(SceneBoundary(round(start_s, 3), round(duration_s, 3)))
    return scenes


def _merge_short(*, scenes: list[SceneBoundary], duration_s: float) -> list[SceneBoundary]:
    """Fold sub-minimum scenes into their neighbour so no footage is lost."""
    if not scenes:
        return []
    merged = [scenes[0]]
    for scene in scenes[1:]:
        if scene.duration_s < settings.scene_min_duration_s and merged:
            previous = merged[-1]
            merged[-1] = SceneBoundary(previous.start_s, scene.end_s)
        else:
            merged.append(scene)
    last = merged[-1]
    if last.end_s < duration_s:
        merged[-1] = SceneBoundary(last.start_s, round(duration_s, 3))
    return merged


def _difference(left: np.ndarray, right: np.ndarray) -> float:
    """Normalised mean absolute difference in 0..1."""
    return float(np.mean(cv2.absdiff(left, right))) / 255.0


def _motion(left: np.ndarray, right: np.ndarray) -> float:
    return _difference(left, right)


def _sharpness(gray: np.ndarray) -> float:
    """Laplacian variance, log-scaled: raw variance grows with resolution."""
    variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if variance <= 0:
        return 0.0
    return min(1.0, math.log10(variance + 1.0) / 4.0)


def _combined(*, sharpness: float, brightness: float, motion: float) -> float:
    """A usable-frame heuristic, not an aesthetic judgement.

    Blur and extreme darkness hurt most; a little motion helps. Values are
    clamped so a single bright frame cannot dominate.
    """
    exposure = 1.0 - abs(brightness - 0.5) * 2.0
    score = 0.45 * min(1.0, sharpness) + 0.35 * max(0.0, exposure) + 0.20 * min(1.0, motion * 3)
    return max(0.0, min(1.0, score))
