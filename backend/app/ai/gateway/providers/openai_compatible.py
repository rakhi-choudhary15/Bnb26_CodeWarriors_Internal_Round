"""Shared OpenAI-compatible wire-format client (Grok + any compatible endpoint).

xAI's API (`https://api.x.ai/v1`) and the other compatible providers differ only
by base URL and key, so the HTTP mechanics live here once. Nothing outside
`app/ai/gateway` imports an SDK (AGENTS.md §23).
"""

from __future__ import annotations

import base64
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.ai.gateway.base import (
    AIProvider,
    EmbeddingResult,
    GenerateResult,
    Message,
    TranscriptResult,
)
from app.core.config import settings
from app.core.errors import AIUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Rough per-1M-token pricing used for cost logging (AI-ARCHITECTURE.md §5).
# These are estimates for budgeting, not billing truth.
COST_PER_MTOK: dict[str, tuple[float, float]] = {
    "grok-2-latest": (2.00, 10.00),
    "grok-2-mini-latest": (0.20, 1.00),
    "grok-2-vision-latest": (2.00, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "whisper-1": (0.006, 0.0),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    in_rate, out_rate = COST_PER_MTOK.get(model, (1.0, 3.0))
    return round(
        (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate, 6
    )


def build_content(message: Message) -> list[dict[str, Any]]:
    """OpenAI chat content parts, including base64 image parts for vision."""
    if not message.images:
        return [{"type": "text", "text": message.content}]
    parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
    for data, mime in zip(message.images, message.image_mimes, strict=False):
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"},
            }
        )
    return parts


class OpenAICompatibleProvider(AIProvider):
    """Chat-completions + embeddings over an OpenAI-compatible endpoint.

    Instantiated for both `grok` (xAI base URL) and `openai_compatible`, which is
    the abstraction the mandate asks for: adding another vendor means adding a
    subclass that sets `name`/`base_url`, not touching the application.
    """

    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise AIUnavailableError(
                f"Provider '{self.name}' has no API key configured.",
                details={"hint": "set LLM_API_KEY or choose AI_PROVIDER=dev"},
            )
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.llm_timeout_s,
        )

    def generate(
        self,
        messages: list[Message],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
    ) -> GenerateResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": build_content(m)} for m in messages
            ],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            # xAI and OpenAI both honour a JSON response format. The schema itself
            # is carried in the prompt because neither supports strict JSON schema.
            payload["response_format"] = {"type": "json_object"}
            if schema_hint:
                payload["messages"] = [
                    *payload["messages"],
                    {
                        "role": "system",
                        "content": "Respond with a single JSON object matching this schema:\n"
                        + schema_hint,
                    },
                ]
        started = time.monotonic()
        with self._client() as client:
            resp = client.post("/chat/completions", json=payload)
        if resp.status_code >= 500:
            raise AIUnavailableError(
                "AI provider returned a server error.",
                details={"status": resp.status_code, "provider": self.name},
            )
        if resp.status_code >= 400:
            # 401/403 means bad credentials: surface immediately without retry storm.
            raise AIUnavailableError(
                "AI provider rejected the request.",
                details={
                    "status": resp.status_code,
                    "error": _safe_error(resp),
                    "provider": self.name,
                },
            )
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        return GenerateResult(
            text=text,
            model=data.get("model", model),
            provider=self.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost(data.get("model", model), tokens_in, tokens_out),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        with self._client() as client:
            resp = client.post("/embeddings", json={"model": model, "input": texts})
        if resp.status_code >= 400:
            raise AIUnavailableError(
                "Embedding provider rejected the request.",
                details={"status": resp.status_code, "error": _safe_error(resp)},
            )
        data = resp.json()
        ordered = sorted(data["data"], key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in ordered]
        tokens = int((data.get("usage") or {}).get("prompt_tokens", 0))
        return EmbeddingResult(
            vectors=vectors,
            model=data.get("model", model),
            provider=self.name,
            tokens_in=tokens,
            cost_usd=estimate_cost(model, tokens, 0),
        )

    def transcribe(self, audio_path: Path, *, model: str) -> TranscriptResult:
        with self._client() as client, audio_path.open("rb") as handle:
            resp = client.post(
                "/audio/transcriptions",
                files={"file": (audio_path.name, handle, "audio/wav")},
                data={
                    "model": model,
                    "timestamp_granularities[]": "word",
                    "response_format": "verbose_json",
                },
            )
        if resp.status_code >= 400:
            raise AIUnavailableError(
                "Speech-to-text provider rejected the request.",
                details={"status": resp.status_code, "error": _safe_error(resp)},
            )
        return _parse_whisper(resp.json(), self.name, model)


def _safe_error(resp: httpx.Response) -> str:
    """Provider error text without leaking request contents."""
    try:
        body = resp.json()
        err = body.get("error", {})
        return str(err.get("message", err))[:300]
    except (json.JSONDecodeError, AttributeError):
        return resp.text[:200]


def _parse_whisper(payload: dict[str, Any], provider: str, model: str) -> TranscriptResult:
    """Normalise a verbose transcription into our segment shape."""
    segments: list[dict[str, Any]] = []
    raw_segments = payload.get("segments") or []
    if raw_segments:
        for seg in raw_segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start_s": round(float(seg.get("start", 0.0)), 3),
                    "end_s": round(float(seg.get("end", 0.0)), 3),
                    "text": text,
                    "speaker": None,
                    "words": _words_of(seg),
                }
            )
    else:
        text = (payload.get("text") or "").strip()
        if text:
            segments.append(
                {
                    "start_s": 0.0,
                    "end_s": round(float(payload.get("duration", 0.0)), 3),
                    "text": text,
                    "speaker": None,
                    "words": _words_of(payload),
                }
            )
    return TranscriptResult(
        segments=segments,
        language=payload.get("language"),
        model=model,
        provider=provider,
        warnings=[] if segments else ["no_speech"],
    )


def _words_of(seg: dict[str, Any]) -> list[dict[str, Any]]:
    words = seg.get("words") or []
    return [
        {
            "w": w.get("word", "").strip(),
            "s": round(float(w.get("start", 0.0)), 3),
            "e": round(float(w.get("end", 0.0)), 3),
        }
        for w in words
        if w.get("word")
    ]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity with a zero guard (D-009: never trust model math)."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def unit_vector(seed: int, dim: int) -> list[float]:
    """Deterministic pseudo-embedding for the dev provider.

    Uses a seeded hash chain rather than randomness so repeated runs of the demo
    produce stable, comparable vectors. It is explicitly NOT a semantic model and
    any capability that depends on real semantics is labelled MOCKED (D-018).
    """
    vec: list[float] = []
    state = seed & 0xFFFFFFFF
    for _ in range(dim):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        vec.append(((state % 2000) - 1000) / 1000.0)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


_WORD_RE = re.compile(r"[\w']+")