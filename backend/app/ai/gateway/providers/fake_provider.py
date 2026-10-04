"""Fake provider for tests (AGENTS.md §14).

Tests must never touch the network. `FakeProvider` returns scripted responses
per task and records every call so a test can assert the gateway's retry,
fallback, cache and circuit-breaker behaviour.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.gateway.base import (
    AIProvider,
    EmbeddingResult,
    GenerateResult,
    Message,
    TranscriptResult,
)
from app.ai.gateway.providers.dev_provider import extract_task, unit_vector


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        *,
        fail_times: int = 0,
        embed_dim: int = 32,
    ) -> None:
        self.responses = responses or {}
        self.fail_times = fail_times
        self.calls: list[dict[str, Any]] = []
        self._embed_dim = embed_dim

    def available(self) -> bool:
        return True

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
        task = extract_task(messages) or "unknown"
        self.calls.append({"task": task, "model": model, "json_mode": json_mode})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("FakeProvider failure")
        payload = self.responses.get(task, {})
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return GenerateResult(
            text=text,
            model=model,
            provider=self.name,
            tokens_in=10,
            tokens_out=20,
        )

    def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        self.calls.append({"task": "embed", "count": len(texts)})
        return EmbeddingResult(
            vectors=[unit_vector(abs(hash(t)), self._embed_dim) for t in texts],
            model=model,
            provider=self.name,
        )

    def transcribe(self, audio_path, *, model: str) -> TranscriptResult:  # type: ignore[no-untyped-def]
        self.calls.append({"task": "transcribe"})
        return TranscriptResult(
            segments=[
                {"start_s": 0.0, "end_s": 1.5, "text": "hello", "speaker": None, "words": []},
                {"start_s": 1.5, "end_s": 3.0, "text": "world", "speaker": None, "words": []},
            ],
            language="en",
            model=model,
            provider=self.name,
        )

    def describe_images(
        self,
        images: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str,
        json_mode: bool = False,
    ) -> GenerateResult:
        self.calls.append({"task": "vision", "images": len(images)})
        payload = self.responses.get("vision", {})
        return GenerateResult(
            text=payload if isinstance(payload, str) else json.dumps(payload),
            model=model,
            provider=self.name,
        )