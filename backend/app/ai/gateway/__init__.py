"""Model gateway package."""

from app.ai.gateway.base import (
    AIProvider,
    EmbeddingResult,
    GenerateResult,
    Message,
    ModelGateway,
    TranscriptResult,
    get_gateway,
    set_gateway,
)
from app.ai.gateway.providers import build_provider, cosine_similarity

__all__ = [
    "AIProvider",
    "EmbeddingResult",
    "GenerateResult",
    "Message",
    "ModelGateway",
    "TranscriptResult",
    "build_provider",
    "cosine_similarity",
    "get_gateway",
    "set_gateway",
]
