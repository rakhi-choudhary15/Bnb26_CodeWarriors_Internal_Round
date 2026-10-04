"""Grok provider — the primary AI vendor (mission §9).

xAI exposes an OpenAI-compatible API, so this is a thin configuration of the
shared client. Everything Grok-specific lives here; no application module
imports this file.

Capability honesty (mission §9): xAI's public API serves chat completions with
image input and does not serve a speech-to-text endpoint. `transcribe` therefore
raises `AIUnavailableError` rather than pretending, and the pipeline takes the
documented fallback route (VIDEO-PIPELINE.md §8: transcript failed -> visual-only
matching with the confidence flag).
"""

from __future__ import annotations

from app.ai.gateway.providers.openai_compatible import OpenAICompatibleProvider
from app.core.config import settings
from app.core.errors import AIUnavailableError


class GrokProvider(OpenAICompatibleProvider):
    name = "grok"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or "https://api.x.ai/v1",
        )

    def transcribe(self, audio_path, *, model: str):  # type: ignore[no-untyped-def]
        raise AIUnavailableError(
            "Grok does not provide speech-to-text.",
            details={
                "provider": self.name,
                "mitigation": "video.understand falls back to visual-only matching "
                "and caps confidence at 0.7 (D-017)",
            },
        )