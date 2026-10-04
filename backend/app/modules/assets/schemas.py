"""Asset request/response schemas (API-SPECIFICATION.md §Assets)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import AssetKind


class RequestUploadRequest(BaseModel):
    """The client declares what it is about to send. The server verifies it later."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    mime: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0)
    kind: AssetKind
    project_id: str | None = Field(default=None, max_length=36)


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(max_length=36)


class PatchAssetRequest(BaseModel):
    """Only the descriptive fields; bytes and probe results are immutable."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] | None = Field(default=None, max_length=20)
    kind: AssetKind | None = None


class UploadTicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    upload_url: str
    expires_in: int
    method: str = "PUT"
    bucket: str
    key: str
    headers: dict[str, str] = Field(default_factory=dict)
