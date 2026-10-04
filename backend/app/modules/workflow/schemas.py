"""Workflow and blueprint request/response schemas (API-SPECIFICATION.md §Creation)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import ImplStatus


class ProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: str
    intent_id: str | None = None
    blueprint_id: str | None = None
    workflow_id: str | None = None
    cover_asset_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BlueprintStage(BaseModel):
    """One stage of a blueprint. `skill_ids` must exist in the registry.

    A `manual` stage may have no skills: that is a creator gate, and it is
    accepted or skipped rather than run.
    """

    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    goal: str | None = Field(default=None, max_length=500)
    skill_ids: list[str] = Field(default_factory=list, max_length=6)
    optional: bool = False
    manual: bool = False
    impl_status: ImplStatus | None = None

    @model_validator(mode="after")
    def _has_something_to_do(self) -> BlueprintStage:
        if not self.skill_ids and not self.manual:
            raise ValueError("a stage needs skill_ids, or must be marked manual")
        return self


class CreateBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(max_length=36)


class UpdateBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[BlueprintStage] = Field(min_length=1, max_length=12)


class StartWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str | None = None


class UpdateStepRequest(BaseModel):
    """Accept or skip. `run` is the only other transition, and it has its own route."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["done", "skipped"]
