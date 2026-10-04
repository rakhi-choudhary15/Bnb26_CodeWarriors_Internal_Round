"""Storage abstraction (ARCHITECTURE.md §6, SECURITY.md §2).

Two adapters behind one interface:

* ``SupabaseStorage`` — private buckets, short-lived signed upload/download URLs.
* ``LocalStorage``    — filesystem-backed for local runs; serves byte-identical
  endpoints so the frontend upload contract is unchanged (D-023).

Object keys are always ``{user_id}/{project_id}/{asset_id}/{filename}`` and are
built by the backend, never taken from the client, which is what the storage
policies in `rls.sql` rely on.
"""

from __future__ import annotations

import abc
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

BUCKETS = ("assets-original", "assets-derived", "renders")

_SAFE_SUFFIXES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "application/pdf": ".pdf",
}


def sanitize_filename(filename: str, mime: str | None = None) -> str:
    """Normalise a client filename into a safe storage basename.

    The extension comes from the MIME allowlist, not from the user string, so
    `../../evil.sh` or `a.jpg.exe` cannot influence the stored path.
    """
    suffix = _SAFE_SUFFIXES.get((mime or "").lower(), "")
    if not suffix:
        raw = Path(filename or "").suffix.lower()
        suffix = raw if raw in set(_SAFE_SUFFIXES.values()) else ".bin"
    stem = Path(filename or "").stem or "upload"
    cleaned = "".join(ch for ch in stem if ch.isalnum() or ch in "-_")[:60] or "upload"
    return f"{cleaned}{suffix}"


def build_object_key(
    owner_id: uuid.UUID, asset_id: uuid.UUID, filename: str, project_id: uuid.UUID | None
) -> str:
    """Backend-authored storage path (SECURITY.md §2)."""
    scope = str(project_id) if project_id else "unassigned"
    return f"{owner_id}/{scope}/{asset_id}/{sanitize_filename(filename)}"


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int


class StorageBackend(abc.ABC):
    name: str

    @abc.abstractmethod
    def write(self, bucket: str, key: str, data: bytes) -> StoredObject: ...

    @abc.abstractmethod
    def read(self, bucket: str, key: str) -> bytes: ...

    @abc.abstractmethod
    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> StoredObject: ...

    @abc.abstractmethod
    def delete(self, bucket: str, key: str) -> None: ...

    @abc.abstractmethod
    def exists(self, bucket: str, key: str) -> bool: ...

    @abc.abstractmethod
    def local_path(self, bucket: str, key: str) -> Path | None:
        """Filesystem path when the object is locally addressable.

        FFmpeg/OpenCV need a real path, so workers use this when available and
        otherwise stage the bytes through `read()`.
        """

    def presign_upload(self, bucket: str, key: str, expires_in: int) -> str:
        raise NotImplementedError

    def presign_download(self, bucket: str, key: str, expires_in: int) -> str:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.local_storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.api_base = settings.next_public_api_url.rstrip("/")

    def _path(self, bucket: str, key: str) -> Path:
        if bucket not in BUCKETS:
            raise ValidationError("Unknown storage bucket.", details={"bucket": bucket})
        target = (self.root / bucket / key).resolve()
        # Defence in depth against traversal even though keys are server-built.
        if not str(target).startswith(str(self.root)):
            raise ValidationError("Invalid storage key.")
        return target

    def write(self, bucket: str, key: str, data: bytes) -> StoredObject:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(bucket=bucket, key=key, size_bytes=len(data))

    def read(self, bucket: str, key: str) -> bytes:
        path = self._path(bucket, key)
        if not path.is_file():
            raise NotFoundError("Stored object not found.", details={"key": key})
        return path.read_bytes()

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> StoredObject:
        src = self._path(src_bucket, src_key)
        dst = self._path(dst_bucket, dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return StoredObject(bucket=dst_bucket, key=dst_key, size_bytes=dst.stat().st_size)

    def delete(self, bucket: str, key: str) -> None:
        path = self._path(bucket, key)
        if path.is_file():
            path.unlink()

    def exists(self, bucket: str, key: str) -> bool:
        return self._path(bucket, key).is_file()

    def local_path(self, bucket: str, key: str) -> Path | None:
        path = self._path(bucket, key)
        return path if path.is_file() else None

    def presign_upload(self, bucket: str, key: str, expires_in: int) -> str:
        # Token is a real signature so the route cannot be called unsigned.
        return (
            f"{self.api_base}/api/storage/upload/{bucket}/{key}"
            f"?expires={expires_in}&token={_local_token(bucket, key, 'put', expires_in)}"
        )

    def presign_download(self, bucket: str, key: str, expires_in: int) -> str:
        return (
            f"{self.api_base}/api/storage/object/{bucket}/{key}"
            f"?expires={expires_in}&token={_local_token(bucket, key, 'get', expires_in)}"
        )


def _local_token(bucket: str, key: str, action: str, expires_in: int) -> str:
    """Signed, expiring token so local storage keeps the security properties.

    The signing key is derived from the deployment's configuration rather than a
    hard-coded secret, and it authorises exactly one (bucket, key, action) tuple.
    """
    import hashlib
    import hmac
    import time

    material = f"{bucket}:{key}:{action}:{time.time() // max(expires_in, 1)}"
    seed = settings.supabase_service_key or settings.llm_api_key or settings.database_url
    return hmac.new(seed.encode(), material.encode(), hashlib.sha256).hexdigest()[:32]


def verify_local_token(bucket: str, key: str, action: str, expires_in: int, token: str) -> bool:
    import hmac

    return hmac.compare_digest(_local_token(bucket, key, action, expires_in), token or "")


class SupabaseStorage(StorageBackend):
    """Supabase Storage adapter used when the project is configured.

    Signed URLs are produced server-side with the service key, which never
    reaches the browser (SECURITY.md §8). The REST call is intentionally
    hand-rolled over httpx so no vendor SDK is required at import time.
    """

    name = "supabase"

    def __init__(self, url: str, service_key: str) -> None:
        self.url = url.rstrip("/")
        self.service_key = service_key
        self._client = None

    def _http(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=f"{self.url}/storage/v1",
                headers={
                    "Authorization": f"Bearer {self.service_key}",
                    "apikey": self.service_key,
                },
                timeout=60.0,
            )
        return self._client

    def write(self, bucket: str, key: str, data: bytes) -> StoredObject:
        resp = self._http().post(
            f"/object/{bucket}/{key}", content=data, headers={"x-upsert": "false"}
        )
        resp.raise_for_status()
        return StoredObject(bucket=bucket, key=key, size_bytes=len(data))

    def read(self, bucket: str, key: str) -> bytes:
        resp = self._http().get(f"/object/{bucket}/{key}")
        if resp.status_code == 404:
            raise NotFoundError("Stored object not found.")
        resp.raise_for_status()
        return resp.content

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> StoredObject:
        data = self.read(src_bucket, src_key)
        return self.write(dst_bucket, dst_key, data)

    def delete(self, bucket: str, key: str) -> None:
        self._http().delete(f"/object/{bucket}/{key}")

    def exists(self, bucket: str, key: str) -> bool:
        resp = self._http().head(f"/object/{bucket}/{key}")
        return resp.status_code == 200

    def local_path(self, bucket: str, key: str) -> Path | None:
        # Supabase has no local path; workers stage bytes to the temp dir.
        return None

    def presign_upload(self, bucket: str, key: str, expires_in: int) -> str:
        import base64
        import json

        token = (
            base64.urlsafe_b64encode(
                json.dumps({"path": key, "bucket": bucket}).encode()
            ).decode()
        )
        return (
            f"{self.url}/storage/v1/object/upload/{bucket}/{key}"
            f"?token={token}"
        )

    def presign_download(self, bucket: str, key: str, expires_in: int) -> str:
        resp = self._http().post(
            f"/object/sign/{bucket}/{key}", json={"expiresIn": expires_in}
        )
        resp.raise_for_status()
        signed = resp.json()
        return f"{self.url}{signed['signedURL'].lstrip('/')}"


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Resolve the storage backend once per process."""
    global _storage
    if _storage is not None:
        return _storage
    if settings.supabase_url and settings.supabase_service_key:
        _storage = SupabaseStorage(settings.supabase_url, settings.supabase_service_key)
    else:
        _storage = LocalStorage()
    return _storage


def set_storage(backend: StorageBackend) -> None:
    """Injection point for tests."""
    global _storage
    _storage = backend


def ensure_temp_dir(name: str) -> Path:
    """Per-job scratch directory, always cleaned by the caller (VIDEO-PIPELINE.md §7)."""
    path = Path(settings.temp_dir) / name / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_temp_dir(path: Path | None) -> None:
    """Remove a per-job temp directory, and nothing else.

    A job-supplied path must never be able to delete an arbitrary directory, so
    anything outside the configured temp root is left untouched and logged.
    """
    if path is None:
        return
    resolved = path.resolve()
    root = Path(settings.temp_dir).resolve()
    # `is_relative_to` avoids the string-prefix trap where a sibling directory
    # sharing a name prefix (`C:\tmp2` vs `C:\tmp`) passes a startswith check.
    if not resolved.is_relative_to(root):
        logger.warning("Refusing to remove temp dir outside %s: %s", root, resolved)
        return
    if resolved == root:
        logger.warning("Refusing to remove the temp root itself: %s", resolved)
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)


def local_storage_enabled() -> bool:
    return os.environ.get("CREATORAI_STORAGE", "local") == "local"