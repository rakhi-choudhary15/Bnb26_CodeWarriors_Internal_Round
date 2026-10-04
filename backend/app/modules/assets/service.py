"""Asset ingest service (PRD §7, SECURITY.md §3).

Uploads are two-step by design: the client asks for a target, PUTs the bytes
straight to storage, then calls `complete`. The API never proxies the bytes, and
the declared MIME is never trusted: magic bytes decide.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.media_validation import (
    ALLOWED_MIMES,
    HEADER_BYTES,
    UnsupportedMediaError,
    sniff_mime,
)
from app.core.models import Asset, AssetKind, AssetStatus, Project
from app.core.storage import BUCKETS, build_object_key, get_storage

logger = get_logger(__name__)

#: The bucket originals live in; derived media and renders use the others.
ORIGINAL_BUCKET = BUCKETS[0]

#: Extensions the sanitizer keeps; everything else is replaced.
_SAFE_SUFFIXES = {
    ".mp4", ".mov", ".m4a", ".mp3", ".wav", ".jpg", ".jpeg", ".png", ".txt", ".pdf",
}


def request_upload(
    db: Session,
    *,
    owner_id: uuid.UUID,
    filename: str,
    mime: str,
    size_bytes: int,
    kind: str,
    project_id: uuid.UUID | str | None,
) -> dict[str, Any]:
    """Reserve a destination and return a short-lived upload URL."""
    if mime not in ALLOWED_MIMES:
        raise ValidationError(
            "That file type is not supported.",
            details={"mime": mime, "allowed": sorted(ALLOWED_MIMES)},
        )
    if size_bytes <= 0:
        raise ValidationError("The file looks empty.", details={"field": "size_bytes"})
    if size_bytes > settings.max_upload_bytes:
        raise ValidationError(
            "That file is larger than the upload limit.",
            details={"size_bytes": size_bytes, "max_bytes": settings.max_upload_bytes},
        )
    if kind not in {member.value for member in AssetKind}:
        raise ValidationError(
            "Unknown asset kind.", details={"kind": kind, "allowed": [m.value for m in AssetKind]}
        )

    proj_uuid: uuid.UUID | None = None
    if project_id is not None:
        if isinstance(project_id, uuid.UUID):
            proj_uuid = project_id
        else:
            try:
                proj_uuid = uuid.UUID(str(project_id))
            except (ValueError, TypeError) as exc:
                raise ValidationError(
                    "Invalid project_id format.", details={"project_id": str(project_id)}
                ) from exc

        # Ownership verification (BUG-003): Ensure project exists and belongs to owner_id
        project = db.query(Project).filter_by(id=proj_uuid, owner_id=owner_id).first()
        if project is None:
            raise NotFoundError("Project not found.", details={"project_id": str(proj_uuid)})

    asset = Asset(
        owner_id=owner_id,
        project_id=proj_uuid,
        kind=AssetKind(kind),
        filename=_safe_name(filename),
        storage_path="",  # Filled in once the bytes land.
        mime=mime,
        size_bytes=int(size_bytes),
        status=AssetStatus.pending,
    )
    db.add(asset)
    db.flush()

    bucket, key = _bucket_and_key(
        owner_id=owner_id,
        asset_id=asset.id,
        filename=filename,
        project_id=proj_uuid,
    )
    asset.storage_path = f"{bucket}/{key}"
    db.add(asset)
    db.flush()

    storage = get_storage()
    upload_url = storage.presign_upload(bucket, key, settings.upload_url_ttl_s)
    return {
        "asset_id": str(asset.id),
        "upload_url": upload_url,
        "expires_in": settings.upload_url_ttl_s,
        "method": "PUT",
        "bucket": bucket,
        "key": key,
        "headers": {"content-type": mime},
    }


def complete_upload(db: Session, *, owner_id: uuid.UUID, asset_id: uuid.UUID | str) -> Asset:
    """Verify the uploaded bytes by magic number and mark the asset ready to probe."""
    asset = get_asset(db, owner_id=owner_id, asset_id=asset_id)
    local = get_storage().local_path(*_bucket_and_key_for(asset))
    if local is None or not Path(local).is_file():
        raise ValidationError(
            "We could not find the uploaded file yet. Try again in a moment.",
            details={"asset_id": str(asset.id)},
        )

    path = Path(local)
    size_bytes = path.stat().st_size
    if size_bytes == 0:
        return _reject(db, asset, "empty_file")
    if size_bytes > settings.max_upload_bytes:
        return _reject(db, asset, "file_too_large")

    try:
        detected = sniff_mime(path.open("rb").read(HEADER_BYTES), declared_mime=asset.mime)
    except UnsupportedMediaError:
        return _reject(db, asset, f"unsupported_signature:{asset.mime}")

    asset.mime = detected
    asset.size_bytes = size_bytes
    asset.status = AssetStatus.pending
    asset.status_reason = None
    db.add(asset)
    db.flush()
    return asset


def _reject(db: Session, asset: Asset, reason: str) -> Asset:
    """Record why an upload was refused; the row stays for the creator to delete."""
    asset.status = AssetStatus.rejected
    asset.status_reason = reason
    db.add(asset)
    db.flush()
    raise ValidationError(
        "That file could not be accepted.",
        details={"asset_id": str(asset.id), "reason": reason},
    )


def list_assets(
    db: Session,
    *,
    owner_id: uuid.UUID,
    kind: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Asset]:
    query = select(Asset).where(Asset.owner_id == owner_id)
    if kind:
        query = query.where(Asset.kind == AssetKind(kind))
    if project_id:
        query = query.where(Asset.project_id == project_id)
    return list(db.execute(query.order_by(Asset.created_at.desc()).limit(limit)).scalars())


def get_asset(db: Session, *, owner_id: uuid.UUID, asset_id: uuid.UUID | str) -> Asset:
    resolved = _uuid(asset_id, "asset_id")
    asset = db.execute(
        select(Asset).where(Asset.id == resolved, Asset.owner_id == owner_id)
    ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("Asset not found.", details={"asset_id": str(resolved)})
    return asset


def delete_asset(db: Session, *, owner_id: uuid.UUID, asset_id: uuid.UUID | str) -> None:
    """Deleting an asset is irreversible, so it is never done implicitly."""
    asset = get_asset(db, owner_id=owner_id, asset_id=asset_id)
    try:
        get_storage().delete(*_bucket_and_key_for(asset))
    except OSError as exc:
        logger.warning(
            "Could not delete stored object for asset %s (%s)", asset.id, type(exc).__name__
        )
    db.delete(asset)
    db.flush()


def signed_url(asset: Asset) -> str | None:
    """A short-lived URL for viewing. Absent rather than broken when unsupported."""
    try:
        return get_storage().presign_download(*_bucket_and_key_for(asset), settings.signed_url_ttl_s)
    except NotImplementedError:
        return None


def _bucket_and_key(
    *, owner_id: uuid.UUID, asset_id: uuid.UUID, filename: str, project_id: uuid.UUID | None
) -> tuple[str, str]:
    """Bucket plus backend-authored key. The client never supplies either."""
    return ORIGINAL_BUCKET, build_object_key(owner_id, asset_id, filename, project_id)


def bucket_and_key(db: Session, *, owner_id: uuid.UUID, asset_id: uuid.UUID | str) -> tuple[str, str]:
    """Owner-scoped `(bucket, key)` for storage calls.

    Goes through `get_asset`, so asking for someone else's id raises NotFound
    instead of handing back a path that would be read or overwritten.
    """
    asset = get_asset(db, owner_id=owner_id, asset_id=asset_id)
    return _bucket_and_key_for(asset)


def _bucket_and_key_for(asset: Asset) -> tuple[str, str]:
    """Split a stored `bucket/key` path back into the pair the backend expects."""
    bucket, _, key = (asset.storage_path or "").partition("/")
    if not bucket or not key:
        raise ValidationError(
            "Asset storage path is malformed.", details={"asset_id": str(asset.id)}
        )
    return bucket, key


def _safe_name(filename: str) -> str:
    """Strip any path component; the stored name is never attacker-controlled text."""
    name = Path(str(filename).replace("\\", "/")).name
    stem = Path(name).stem or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in _SAFE_SUFFIXES:
        suffix = ""
    cleaned = "".join(ch for ch in stem if ch.isalnum() or ch in "-_ ")[:120].strip()
    return f"{cleaned or 'upload'}{suffix}"


def _uuid(value: uuid.UUID | str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFoundError("Asset not found.", details={"field": field}) from exc
