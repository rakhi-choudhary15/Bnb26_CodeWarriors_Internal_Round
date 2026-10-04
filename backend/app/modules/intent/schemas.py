"""Intent Engine request/response schemas (API-SPECIFICATION.md §Creation)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_PRIMARY_TEXT = 500
MAX_DETAILS_TEXT = 1000


class CreateIntentRequest(BaseModel):
    """`POST /api/creation/intents`.

    The project is always created here (API-SPECIFICATION.md §Creation), so there
    is no `project_id` here: passing one would let a caller attach an intent to
    somebody else's project.
    """

    model_config = ConfigDict(extra="forbid")

    primary_text: str = Field(min_length=5, max_length=MAX_PRIMARY_TEXT)
    details_text: str | None = Field(default=None, max_length=MAX_DETAILS_TEXT)
    creator_dna: dict[str, Any] | None = None


class AnalyzeIntentRequest(BaseModel):
    """`POST /api/creation/intents/:id/analyze` — re-parse after an edit."""

    model_config = ConfigDict(extra="forbid")

    primary_text: str | None = Field(default=None, max_length=MAX_PRIMARY_TEXT)
    details_text: str | None = Field(default=None, max_length=MAX_DETAILS_TEXT)


class UpdateIntentRequest(BaseModel):
    """`PATCH /api/creation/intents/:id` — partial parsed fields."""

    model_config = ConfigDict(extra="forbid")

    parsed: dict[str, Any] = Field(default_factory=dict)
    primary_text: str | None = Field(default=None, max_length=MAX_PRIMARY_TEXT)
    details_text: str | None = Field(default=None, max_length=MAX_DETAILS_TEXT)


class IntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    primary_text: str
    details_text: str | None = None
    parsed: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, Any] = Field(default_factory=dict)
    parse_status: str
    user_edited: bool = False
    fallback: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None
