"""`edit.suggest` schemas — the EDL is the source of truth (VIDEO-PIPELINE.md §3).

The shape here is the documented EDL verbatim, because `edits/render.py`
compiles this exact structure into ffmpeg arguments. Drift between this schema
and the compiler would silently corrupt renders.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SuggestionType = Literal["trim", "caption", "reframe", "transition", "broll", "music"]

#: PRD §5: trim/caption/reframe are REAL; the rest are suggestion text only.
REAL_SUGGESTION_TYPES = frozenset({"trim", "caption", "reframe"})
MOCKED_SUGGESTION_TYPES = frozenset({"transition", "broll", "music"})

REFRAME_MODES = ("center", "follow")


class Reframe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["center", "follow"] = "center"
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)
    zoom: float = Field(default=1.0, ge=1.0, le=4.0)


class VideoTrackItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src_asset: str = Field(min_length=1, max_length=200)
    #: Seconds into the *original source asset*, never timeline-relative
    #: (VIDEO-PIPELINE.md §7: preserve source timestamps on clips).
    in_s: float = Field(ge=0.0)
    out_s: float = Field(gt=0.0)
    reframe: Reframe = Field(default_factory=Reframe)

    @model_validator(mode="after")
    def _ordered(self) -> VideoTrackItem:
        if self.out_s <= self.in_s:
            raise ValueError("out_s must be greater than in_s")
        return self


class CaptionTrackItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_s: float = Field(ge=0.0)
    end_s: float = Field(gt=0.0)
    text: str = Field(min_length=1, max_length=200)
    style: str = Field(default="bold_center", max_length=40)


class Marker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: float = Field(ge=0.0)
    type: str = Field(default="transition", max_length=40)
    name: str = Field(default="hard_cut", max_length=60)


class EDL(BaseModel):
    """Edit Decision List. `version` increments on every edit (undo support)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    aspect: str = Field(default="9:16", max_length=10)
    clip_id: str = Field(default="", max_length=200)
    tracks: dict[str, list[dict]] = Field(default_factory=dict)
    suggestions: list[dict] = Field(default_factory=list)


class EditSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=60)
    type: SuggestionType
    detail: str = Field(min_length=1, max_length=600)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    applied: bool = False
    #: Optional source range for trim/reframe suggestions.
    start_s: float | None = Field(default=None, ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)
    #: Real when this suggestion is executed by the render compiler; MOCKED when
    #: it is advisory text only (PRD §5). Derived from `type` and never taken
    #: from the model: an LLM must not be able to promote its own suggestion.
    impl_status: Literal["real", "mocked"] = "mocked"
    #: Per-suggestion notes, e.g. `advisory_only_not_rendered` for MOCKED types.
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _derive_status(cls, data: Any) -> Any:
        if isinstance(data, dict) and "type" in data:
            kind = str(data["type"])
            data = {**data, "impl_status": "real" if kind in REAL_SUGGESTION_TYPES else "mocked"}
            if data["impl_status"] == "mocked":
                # A MOCKED suggestion is never applied: nothing applied it.
                data["applied"] = False
        return data

    @model_validator(mode="after")
    def _applied_only_when_real(self) -> EditSuggestion:
        if self.impl_status == "mocked" and self.applied:
            raise ValueError("a mocked suggestion cannot be marked applied")
        return self


class EditSuggestOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edl: EDL
    suggestions: list[EditSuggestion] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
