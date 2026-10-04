"""Asset routes (API-SPECIFICATION.md §Assets).

Upload is three calls: reserve a destination, PUT the bytes to storage, confirm.
The bytes normally never pass through this process; the `/content` PUT exists only
for the local filesystem backend and validates every byte before writing it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentOwner, DbSession, IdempotencyKey, UploadRateLimit
from app.api.serializers import asset_out
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.media_validation import UnsupportedMediaError, sniff_mime
from app.core.models import AssetKind
from app.core.storage import get_storage
from app.modules.assets import service as asset_service
from app.modules.assets.schemas import (
    CompleteUploadRequest,
    PatchAssetRequest,
    RequestUploadRequest,
)
from app.modules.jobs import service as job_service

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/upload-url", status_code=status.HTTP_201_CREATED)
@router.post("/upload_url", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_upload_url(
    db: DbSession,
    owner_id: CurrentOwner,
    body: RequestUploadRequest,
    _: UploadRateLimit,
) -> dict[str, Any]:
    """Validate the declaration and return a short-lived signed PUT."""
    ticket = asset_service.request_upload(
        db,
        owner_id=owner_id,
        filename=body.filename,
        mime=body.mime,
        size_bytes=body.size_bytes,
        kind=body.kind,
        project_id=body.project_id,
    )
    db.commit()
    return ticket


@router.post("/complete")
def complete_upload(
    db: DbSession,
    owner_id: CurrentOwner,
    body: CompleteUploadRequest,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    """Verify the bytes landed, then queue probing as a job.

    Returns 202 + `job_id` per the spec: sniffing plus ffprobe is real work and
    must not hold the connection open. A repeated `Idempotency-Key` returns the
    original job with 200 instead of queueing a second probe.
    """
    asset = asset_service.complete_upload(db, owner_id=owner_id, asset_id=body.asset_id)
    # Commit before queueing: a worker can pick the job up immediately, and it
    # must not be able to read an asset row that is still uncommitted.
    db.commit()
    job_id, reused = job_service.submit(
        db,
        owner_id=owner_id,
        job_type="asset.process",
        payload={"asset_id": str(asset.id)},
        project_id=asset.project_id,
        idempotency_key=idempotency_key,
    )
    db.commit()
    response.status_code = status.HTTP_200_OK if reused else status.HTTP_202_ACCEPTED
    return {
        "job_id": str(job_id),
        "asset_id": str(asset.id),
        "asset_status": asset.status.value if hasattr(asset.status, "value") else asset.status,
        "reused": reused,
    }


@router.get("")
def list_assets(
    db: DbSession,
    owner_id: CurrentOwner,
    kind: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    assets = asset_service.list_assets(
        db, owner_id=owner_id, kind=kind, project_id=project_id, limit=limit
    )
    return {
        "items": [
            asset_out(a, url=asset_service.signed_url(a), include_url=True) for a in assets
        ]
    }


@router.get("/{asset_id}")
def read_asset(db: DbSession, owner_id: CurrentOwner, asset_id: str) -> dict[str, Any]:
    asset = asset_service.get_asset(db, owner_id=owner_id, asset_id=asset_id)
    return asset_out(asset, url=asset_service.signed_url(asset), include_url=True)


@router.patch("/{asset_id}")
def patch_asset(
    db: DbSession, owner_id: CurrentOwner, asset_id: str, body: PatchAssetRequest
) -> dict[str, Any]:
    """Only metadata is editable; the bytes and the probe results are not."""
    asset = asset_service.get_asset(db, owner_id=owner_id, asset_id=asset_id)
    if body.tags is not None:
        asset.tags = body.tags
    if body.kind is not None:
        asset.kind = AssetKind(body.kind)
    db.add(asset)
    db.commit()
    return asset_out(asset, url=asset_service.signed_url(asset), include_url=True)


@router.put("/{asset_id}/content", status_code=status.HTTP_204_NO_CONTENT)
async def put_local_content(
    request: Request,
    db: DbSession,
    owner_id: CurrentOwner,
    asset_id: str,
    content_type: Annotated[str | None, Header()] = None,
) -> Response:
    """Local-backend upload target.

    Used when the deployment has no object storage: the signed PUT points here
    instead. Everything is validated before the write, because at this point the
    only thing we have is the client's word about what the bytes are.
    """
    bucket, key = asset_service.bucket_and_key(db, owner_id=owner_id, asset_id=asset_id)
    data = await request.body()
    if len(data) == 0:
        raise ValidationError("The file looks empty.")
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(
            "That file is larger than the upload limit.",
            details={"max_bytes": settings.max_upload_bytes},
        )
    try:
        verified = sniff_mime(data, declared_mime=content_type)
    except UnsupportedMediaError as exc:
        raise ValidationError(str(exc)) from exc
    get_storage().write(bucket, key, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"x-verified-mime": verified})


@router.get("/{asset_id}/content")
def read_local_content(db: DbSession, owner_id: CurrentOwner, asset_id: str) -> Any:
    """Serve a stored file from local disk. Production uses signed URLs instead."""
    asset = asset_service.get_asset(db, owner_id=owner_id, asset_id=asset_id)
    bucket, key = asset_service.bucket_and_key(db, owner_id=owner_id, asset_id=asset.id)
    local = get_storage().local_path(bucket, key)
    if local is None:
        raise NotFoundError("This asset has no local copy to serve.")
    return FileResponse(local, media_type=asset.mime, filename=asset.filename)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(db: DbSession, owner_id: CurrentOwner, asset_id: str) -> Response:
    """Destructive, so it is explicit and never implied by another action."""
    asset_service.delete_asset(db, owner_id=owner_id, asset_id=asset_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
