"""Provider selection.

The application never branches on a vendor name; it asks for a provider and
receives an `AIProvider` (mission §34). Adding OpenAI/Anthropic/Google later is
a subclass in this package plus one line here.
"""

from __future__ import annotations

from app.ai.gateway.base import AIProvider
from app.ai.gateway.providers.dev_provider import DevProvider
from app.ai.gateway.providers.openai_compatible import (
    OpenAICompatibleProvider,
    cosine_similarity,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_provider() -> AIProvider:
    """Resolve the configured provider.

    A configured vendor that lacks credentials degrades to the dev provider with
    a warning rather than crashing the process at import time, so the API still
    boots and `/api/health` can report the real reason.
    """
    choice = settings.ai_provider
    if choice == "grok":
        from app.ai.gateway.providers.grok import GrokProvider

        provider = GrokProvider()
        if provider.available():
            return provider
        logger.warning("AI_PROVIDER=grok but LLM_API_KEY is empty; using dev provider.")
        return DevProvider()
    if choice == "openai_compatible":
        if settings.llm_api_key:
            return OpenAICompatibleProvider(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
            )
        logger.warning("AI_PROVIDER=openai_compatible but LLM_API_KEY is empty; using dev provider.")
        return DevProvider()
    return DevProvider()


__all__ = [
    "AIProvider",
    "DevProvider",
    "OpenAICompatibleProvider",
    "build_provider",
    "cosine_similarity",
]