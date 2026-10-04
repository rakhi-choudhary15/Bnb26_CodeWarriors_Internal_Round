"""Upload validation by allowlist *and* magic bytes (SECURITY.md §3).

The client-declared MIME type is never trusted. The declared type selects an
allowlist entry, the first bytes of the file must match that entry's signature,
and the result is what gets persisted on the asset row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core.config import settings
from app.core.errors import FileTooLargeError, UnsupportedMediaError

# Per-kind size ceilings from SECURITY.md §3.
KIND_LIMITS: dict[str, int] = {
    "video": 200 * 1024 * 1024,
    "audio": 50 * 1024 * 1024,
    "image": 10 * 1024 * 1024,
    "reference": 200 * 1024 * 1024,
    "script": 5 * 1024 * 1024,
    "brand": 10 * 1024 * 1024,
    "creator": 10 * 1024 * 1024,
}

ALLOWED_MIMES: dict[str, str] = {
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/mp4": "audio",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "text/plain": "script",
    "application/pdf": "reference",
}


@dataclass(frozen=True, slots=True)
class MagicRule:
    mime: str
    offset: int
    signature: tuple[bytes, ...]

    def matches(self, header: bytes) -> bool:
        for sig in self.signature:
            if header[self.offset : self.offset + len(sig)] == sig:
                return True
        return False


# Signatures verified by offset. `text/plain` is intentionally absent: it has no
# magic number, so it is accepted by extension plus a decode check instead.
MAGIC_RULES: tuple[MagicRule, ...] = (
    MagicRule("video/mp4", 4, (b"ftyp",)),
    MagicRule("video/quicktime", 4, (b"ftyp",)),
    MagicRule("video/webm", 0, (b"\x1a\x45\xdf\xa3",)),
    MagicRule("audio/mpeg", 0, (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    MagicRule("audio/wav", 0, (b"RIFF",)),
    MagicRule("audio/mp4", 4, (b"ftyp",)),
    MagicRule("image/jpeg", 0, (b"\xff\xd8\xff",)),
    MagicRule("image/png", 0, (b"\x89PNG\r\n\x1a\n",)),
    MagicRule("image/webp", 0, (b"RIFF",)),
    MagicRule("application/pdf", 0, (b"%PDF-",)),
)

# Distinct container formats that share a signature; resolved by declared mime.
_AMBIGUOUS: dict[str, tuple[str, ...]] = {
    "video/mp4": ("video/mp4", "audio/mp4", "video/quicktime"),
    "video/quicktime": ("video/mp4", "video/quicktime", "audio/mp4"),
    "audio/mp4": ("video/mp4", "video/quicktime", "audio/mp4"),
    "image/webp": ("image/webp", "audio/wav"),
    "audio/wav": ("audio/wav", "image/webp"),
}

HEADER_BYTES = 32


def sniff_mime(data: bytes, declared_mime: str | None = None) -> str:
    """Return the verified MIME type, or raise when it does not match.

    For formats sharing a signature (MP4/MOV/M4A, RIFF WAV/WEBP) the declared
    type disambiguates, but only within the set of types that actually match the
    bytes — a `.txt` renamed to `.mp4` still fails.
    """
    header = data[:HEADER_BYTES]
    declared = (declared_mime or "").split(";")[0].strip().lower()

    if declared == "text/plain":
        try:
            data[:2048].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedMediaError(
                "Text asset must be valid UTF-8.",
                details={"declared": declared},
            ) from exc
        return "text/plain"

    if declared and declared not in ALLOWED_MIMES:
        raise UnsupportedMediaError(
            "Unsupported file type.", details={"mime": declared}
        )

    matched: list[str] = []
    for rule in MAGIC_RULES:
        if rule.matches(header):
            matched.extend(_AMBIGUOUS.get(rule.mime, (rule.mime,)))
    matched = [m for m in dict.fromkeys(matched) if m in ALLOWED_MIMES]

    if not matched:
        raise UnsupportedMediaError(
            "File contents do not match any allowed media type.",
            details={"declared": declared or None},
        )
    if declared in matched:
        return declared
    if len(matched) == 1:
        return matched[0]
    # Declared type did not match any real signature for these bytes.
    raise UnsupportedMediaError(
        "File contents do not match the declared type.",
        details={"declared": declared, "matched": matched},
    )


def validate_upload(*, data: bytes, declared_mime: str, kind: str) -> str:
    """Full validation chain. Returns the verified MIME type.

    Raises `FileTooLargeError` / `UnsupportedMediaError` with a plain-language
    message suitable for the upload list UI (UX-SPECIFICATION.md §8).
    """
    limit = min(KIND_LIMITS.get(kind, KIND_LIMITS["video"]), settings.max_upload_bytes)
    if len(data) == 0:
        raise UnsupportedMediaError("File is empty.")
    if len(data) > limit:
        raise FileTooLargeError(
            f"File is larger than the {limit // (1024 * 1024)} MB limit for {kind} uploads.",
            details={"size_bytes": len(data), "limit_bytes": limit},
        )
    return sniff_mime(data, declared_mime)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def human_size(num_bytes: int) -> str:
    step = 1024.0
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step:
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= step
    return f"{value:.1f}TB"


def allowed_upload_summary() -> str:
    return (
        f"MP4/MOV/WebM up to {settings.max_upload_mb} MB, MP3/WAV/M4A up to 50 MB, "
        "JPG/PNG/WebP up to 10 MB, TXT/PDF up to 5 MB"
    )