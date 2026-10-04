"""EDL -> ffmpeg argument compiler (VIDEO-PIPELINE.md §3, AGENTS.md §13).

The EDL is the source of truth and a render is derived from it, so this compiler
is deliberately small and total: it either produces a valid argument array for a
render-capable platform, or it raises with the reason. It never guesses a range
and it never builds a shell string.

Rules enforced here so no caller has to remember them:
- FFmpeg gets an argument array with a timeout, never a shell string, so a
  filename or a caption can never become a flag;
- caption text goes into a generated subtitle file, never into `drawtext`, so it
  stays out of both argv and the logs;
- timestamps are only ever formatted, never interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import ValidationError
from app.core.media.probe import ffmpeg_available
from app.modules.skills.platform_specs import get_spec

#: Hard ceiling on a single render, matching the job timeout.
RENDER_TIMEOUT_S = 900.0
#: Captions longer than this are a data problem, not a rendering problem.
MAX_CAPTION_CHARS = 400
#: Reframe zoom is clamped: an extreme crop produces an unusable render.
MAX_ZOOM = 3.0


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """A render expressed as data. Executing it is the renderer's job."""

    platform: str
    width: int
    height: int
    aspect: str
    #: Input files in the order the filter graph references them.
    inputs: tuple[str, ...]
    filter_complex: str
    output_path: str
    duration_s: float
    has_audio: bool
    caption_cues: int

    def argv(self) -> list[str]:
        """The exact argument array for this render."""
        argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
        for source in self.inputs:
            argv += ["-i", source]
        return [
            *argv,
            "-filter_complex",
            self.filter_complex,
            "-map",
            "[outv]",
            *(["-map", "[outa]"] if self.has_audio else ["-an"]),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            *(
                ["-c:a", "aac", "-b:a", "128k"]
                if self.has_audio
                else []
            ),
            "-movflags",
            "+faststart",
            "-t",
            f"{self.duration_s:.3f}",
            self.output_path,
        ]


def compile_edl(
    edl: dict[str, Any],
    *,
    platform: str = "instagram_reels",
    output_path: str | Path = "render.mp4",
    source_root: str | Path | None = None,
    has_audio: bool = True,
    captions: list[dict[str, Any]] | None = None,
) -> RenderPlan:
    """Turn an EDL into a `RenderPlan` for one platform.

    Only platforms marked `render_capable` are accepted. Today that is Reels
    alone, and pretending otherwise is exactly the failure MVP-SCOPE forbids.
    """
    spec = get_spec(platform)
    if not spec.render_capable:
        raise ValidationError(
            "Rendering is not implemented for this platform.",
            details={
                "platform": platform,
                "render_capable_platforms": ["instagram_reels"],
                "impl_status": spec.impl_status,
            },
        )

    tracks = (edl or {}).get("tracks") or {}
    video_tracks = [t for t in (tracks.get("video") or []) if isinstance(t, dict)]
    if not video_tracks:
        raise ValidationError("EDL has no video track to render.", details={"platform": platform})

    root = Path(source_root) if source_root else Path(".")
    inputs: list[str] = []
    video_parts: list[str] = []
    audio_parts: list[str] = []
    total_s = 0.0

    for index, track in enumerate(video_tracks):
        source = _resolve_source(track, root)
        if source not in inputs:
            inputs.append(source)
        input_index = inputs.index(source)
        in_s, out_s = _range(track, index)
        video_parts.append(_video_filter(input_index, index, in_s, out_s, track, spec))
        if has_audio:
            audio_parts.append(_audio_filter(input_index, index, in_s, out_s))
        total_s += out_s - in_s

    parts = list(video_parts)
    if len(video_parts) > 1:
        parts.append(_concat(video_parts, audio_parts, has_audio))
        video_label, audio_label = "[vcat]", "[acat]"
    else:
        video_label, audio_label = "[v0]", "[a0]"

    caption_cues = _valid_captions(
        captions if captions is not None else (tracks.get("captions") or []), total_s
    )
    tail = ["null"]
    if caption_cues:
        # The subtitle file is written next to the output by the renderer.
        parts.append(f"{video_label}subtitles=filename={_escape_path('edl_captions.ass')}[vsub]")
        video_label, tail = "[vsub]", ["null"]
    parts.append(f"{video_label}{','.join(tail)}[outv]")
    if has_audio:
        parts.append(f"{audio_label}anull[outa]")

    return RenderPlan(
        platform=spec.key,
        width=spec.width,
        height=spec.height,
        aspect=spec.aspect,
        inputs=tuple(inputs),
        filter_complex=";".join(parts),
        output_path=str(output_path),
        duration_s=round(total_s, 3),
        has_audio=has_audio,
        caption_cues=caption_cues,
    )


def ensure_ffmpeg() -> None:
    """Raise the documented capability error when rendering cannot run."""
    if not ffmpeg_available():
        raise ValidationError(
            "FFmpeg is not installed, so this render cannot run.",
            details={"code": "FFMPEG_UNAVAILABLE"},
        )


def write_caption_file(captions: list[dict[str, Any]], path: str | Path) -> int:
    """Write an ASS subtitle file. Returns the number of cues written.

    The file is the only place caption text lands, which keeps it out of argv and
    out of the logs.
    """
    target = Path(path)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    written = 0
    for caption in _valid_captions(captions, float("inf")):
        start = _ass_time(float(caption["start_s"]))
        end = _ass_time(max(float(caption["end_s"]), start + 0.5))
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{_escape(str(caption['text']))}")
        written += 1
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def _video_filter(
    input_index: int, label: int, in_s: float, out_s: float, track: dict[str, Any], spec: Any
) -> str:
    """Trim the range, crop to the target aspect, scale, place the crop window.

    Only `center` placement is real. `follow` needs a subject tracker that is not
    implemented, so a request for it is honoured as centre rather than pretended.
    """
    reframe = track.get("reframe") or {}
    zoom = _clamp(_number(reframe.get("zoom"), 1.0, "reframe.zoom"), 1.0, MAX_ZOOM)
    x = _clamp(_number(reframe.get("x"), 0.5, "reframe.x"), 0.0, 1.0)
    y = _clamp(_number(reframe.get("y"), 0.5, "reframe.y"), 0.0, 1.0)
    crop_h = f"ih/{zoom:.4f}"
    return (
        f"[{input_index}:v]trim=start={in_s:.3f}:end={out_s:.3f},setpts=PTS-STARTPTS,"
        f"crop=iw*{crop_h}:{crop_h},"
        f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=increase,"
        f"crop={spec.width}:{spec.height}:(iw-{spec.width})*{x:.4f}:(ih-{spec.height})*{y:.4f},"
        f"setsar=1[v{label}]"
    )


def _audio_filter(input_index: int, label: int, in_s: float, out_s: float) -> str:
    return (
        f"[{input_index}:a]atrim=start={in_s:.3f}:end={out_s:.3f},"
        f"asetpts=PTS-STARTPTS[a{label}]"
    )


def _concat(video_parts: list[str], audio_parts: list[str], has_audio: bool) -> str:
    """Join segments; `concat` needs every stream to be continuous."""
    inputs = "".join(f"[v{i}][a{i}]" if has_audio else f"[v{i}]" for i in range(len(video_parts)))
    outputs = "[vcat][acat]" if has_audio else "[vcat]"
    return f"{inputs}concat=n={len(video_parts)}:v=1:a={1 if has_audio else 0}{outputs}"


def _valid_captions(captions: list[Any], duration_s: float) -> list[dict[str, Any]]:
    """Cues that are on screen long enough to read and inside the timeline."""
    usable: list[dict[str, Any]] = []
    for caption in captions or []:
        if not isinstance(caption, dict):
            continue
        text = str(caption.get("text") or "").strip()
        if not text or len(text) > MAX_CAPTION_CHARS:
            continue
        try:
            start = float(caption.get("start_s", 0.0))
            end = float(caption.get("end_s", 0.0))
        except (TypeError, ValueError):
            continue
        if start < 0 or start >= duration_s or end - start < 0.5:
            continue
        usable.append({"start_s": round(start, 3), "end_s": round(min(end, duration_s), 3), "text": text})
    return usable


def _range(track: dict[str, Any], index: int) -> tuple[float, float]:
    in_s = _number(track.get("in_s"), None, f"video[{index}].in_s")
    out_s = _number(track.get("out_s"), None, f"video[{index}].out_s")
    if out_s <= in_s:
        raise ValidationError(
            "EDL video range is not a forward interval.",
            details={"index": index, "in_s": in_s, "out_s": out_s},
        )
    return in_s, out_s


def _resolve_source(track: dict[str, Any], root: Path) -> str:
    asset = str(track.get("src_asset") or "").strip()
    if not asset:
        raise ValidationError("EDL video track has no src_asset.")
    if asset.startswith("/") or "://" in asset:
        # Already resolved by the caller (absolute path or signed URL).
        return asset
    return (root / asset).as_posix()


def _number(value: Any, default: float | None, field: str) -> float:
    if value is None and default is not None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("EDL field is not numeric.", details={"field": field}) from exc


def _escape_path(path: str) -> str:
    """Escape the characters the filter parser treats specially."""
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _escape(text: str) -> str:
    """ASS escaping: a brace would otherwise start an override block."""
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):d}:{int(minutes):02d}:{secs:05.2f}"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
