"""Structured JSON logging with secret redaction (SECURITY.md §8, §11).

Observability events required by AGENTS.md §23 (`intent.created`,
`blueprint.generated`, `workflow.started`, ...) are emitted through `log_event`.
Values are passed as explicit kwargs rather than interpolated into message
strings so the redactor can inspect them structurally.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from typing import Any

# Request correlation id, set by the HTTP middleware for the duration of a call.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_REDACT_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "apikey_header",
        "cookie",
        "password",
        "secret",
        "service_key",
        "supabase_service_key",
        "llm_api_key",
        "signed_url",
        "upload_url",
        "refresh_token",
        "access_token",
        "token",
        "transcript",
        "raw_transcript",
    }
)

_REDACTED = "[redacted]"


def redact(value: Any, *, key_hint: str = "") -> Any:
    """Remove anything that must never reach a log sink."""
    if key_hint.lower() in _REDACT_KEYS:
        return _REDACTED
    if isinstance(value, dict):
        return {k: redact(v, key_hint=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key_hint=key_hint) for v in value]
    if isinstance(value, str) and len(value) > 2000:
        # Long free text can carry user media/transcripts; truncate rather than log.
        return value[:2000] + "…[truncated]"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        extras = getattr(record, "event_fields", None)
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            # Exception type only: stack traces stay out of logs (AGENTS.md §16).
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Third-party libraries are noisy and can echo payloads; quiet them down.
    for noisy in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any
) -> None:
    """Emit a named observability event.

    >>> log_event(log, "intent.created", project_id=str(pid), owner=owner)
    """
    logger.log(level, event, extra={"event_fields": {"event": event, **fields}})


configure_logging()