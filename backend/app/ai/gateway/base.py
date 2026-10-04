"""Provider-neutral AI gateway (AI-ARCHITECTURE.md §5, mission §8/§34).

The application depends on `AIProvider`, never on a vendor SDK. Providers are
adapters; the gateway owns the behaviour the docs require of it:

  * timeout, retry with exponential backoff, fallback model
  * response cache keyed by hash(prompt + model + inputs), TTL 24 h
  * token and cost accounting per call
  * circuit breaker after N consecutive provider failures (D-024)
  * never raises raw provider errors: `AIUnavailableError` / `AIOutputInvalidError`

Provider selection is configuration only (`AI_PROVIDER`):

  * ``grok``              -> xAI, OpenAI-compatible wire format, real key required
  * ``openai_compatible``-> any OpenAI-compatible endpoint (Together, Groq, vLLM…)
  * ``dev``               -> deterministic offline provider so every flow runs
                             with no key. Output is schema-valid and labelled
                             MOCKED in the UI (AGENTS.md §21, D-018).
"""

from __future__ import annotations

import abc
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from app.core.config import settings
from app.core.errors import AIOutputInvalidError, AIUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

Capability = Literal["text", "vision", "embedding", "stt", "structured"]


# ---------------------------------------------------------------------------
# Request / response value objects
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    # Images are sent as OpenAI-style content parts for vision calls.
    images: list[bytes] = field(default_factory=list)
    image_mimes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GenerateResult:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cached: bool = False
    structured: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider: str
    tokens_in: int = 0
    cost_usd: float = 0.0
    cached: bool = False


@dataclass(slots=True)
class TranscriptResult:
    segments: list[dict[str, Any]]
    language: str | None
    model: str
    provider: str
    warnings: list[str] = field(default_factory=list)


class AIProvider(abc.ABC):
    """The one interface the application programs against."""

    name: str

    @abc.abstractmethod
    def available(self) -> bool:
        """True when this provider can serve requests right now."""

    @abc.abstractmethod
    def generate(
        self,
        messages: list[Message],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
    ) -> GenerateResult: ...

    @abc.abstractmethod
    def embed(self, texts: list[str], *, model: str) -> EmbeddingResult: ...

    def transcribe(
        self, audio_path: Path, *, model: str
    ) -> TranscriptResult:  # pragma: no cover - provider dependent
        raise AIUnavailableError(
            f"Provider '{self.name}' does not implement speech-to-text.",
            details={"model": model},
        )

    def describe_images(
        self,
        images: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str,
        json_mode: bool = False,
    ) -> GenerateResult:
        """Vision convenience wrapper over `generate`."""
        messages = [
            Message(role="system", content=prompt),
            Message(
                role="user",
                content="Describe the attached frames.",
                images=[img for img, _ in images],
                image_mimes=[mime for _, mime in images],
            ),
        ]
        return self.generate(messages, model=model, json_mode=json_mode, temperature=0.2)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class ResponseCache:
    """Disk-backed response cache (D-013).

    A filesystem cache keeps the demo resilient without Redis and survives
    process restarts, which is what DEMO_MODE needs.
    """

    def __init__(self, root: Path, ttl_s: int) -> None:
        self.root = root
        self.ttl_s = ttl_s
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(namespace: str, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return f"{namespace}-{hashlib.sha256(raw.encode()).hexdigest()}"

    def _path(self, key: str) -> Path:
        """Cache keys contain `:` (skill id namespaces), which is not a legal
        character in a Windows filename. Hash the key so the cache works on every
        platform the project targets.
        """
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not settings.ai_cache_enabled:
            return None
        path = self._path(key)
        if not path.is_file():
            return None
        if self.ttl_s > 0 and (time.time() - path.stat().st_mtime) > self.ttl_s:
            path.unlink(missing_ok=True)
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not settings.ai_cache_enabled:
            return
        try:
            self._path(key).write_text(json.dumps(value, default=str), "utf-8")
        except OSError:
            # A cache write failure must never fail the request.
            logger.warning("AI cache write failed for key %s", key)


# ---------------------------------------------------------------------------
# Circuit breaker (AI-ARCHITECTURE.md §9)
# ---------------------------------------------------------------------------
class CircuitBreaker:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.consecutive_failures = 0
        self.open_until = 0.0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.open_until = time.monotonic() + 30.0
            logger.error("AI circuit breaker opened after %d failures", self.consecutive_failures)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self.open_until


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------
class ModelGateway:
    """Single entry point for every AI capability in the application."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider
        self._breaker = CircuitBreaker(settings.llm_circuit_breaker_threshold)
        self._cache = ResponseCache(Path(settings.temp_dir) / "ai-cache", settings.ai_cache_ttl_s)
        self.metrics: dict[str, Any] = {
            "calls": 0,
            "cache_hits": 0,
            "failures": 0,
            "retries": 0,
            "fallbacks": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "by_provider": {},
        }

    # -- provider ---------------------------------------------------------
    @property
    def provider(self) -> AIProvider:
        if self._provider is None:
            from app.ai.gateway.providers import build_provider

            self._provider = build_provider()
        return self._provider

    def set_provider(self, provider: AIProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": self.provider.available(),
            "demo_mode": settings.demo_mode,
            **self.metrics,
        }

    # -- text / structured ------------------------------------------------
    def generate(
        self,
        messages: list[Message],
        *,
        capability: Capability = "text",
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
        namespace: str | None = None,
        use_cache: bool = True,
    ) -> GenerateResult:
        models = self._models_for(capability)
        cache_key = None
        if namespace and use_cache:
            cache_key = ResponseCache.key(
                namespace,
                {
                    "messages": [
                        {"r": m.role, "c": m.content, "img": len(m.images)} for m in messages
                    ],
                    "model": models[0],
                    "json": json_mode,
                    "temp": temperature,
                    "schema": schema_hint,
                },
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                self.metrics["cache_hits"] += 1
                return GenerateResult(
                    text=cached["text"],
                    model=cached["model"],
                    provider=cached.get("provider", self.provider_name),
                    tokens_in=0,
                    tokens_out=0,
                    cached=True,
                    structured=cached.get("structured"),
                )

        if self._breaker.is_open:
            raise AIUnavailableError(
                "AI provider is temporarily unavailable after repeated failures.",
                details={"provider": self.provider_name},
            )

        last_error: Exception | None = None
        for attempt, model in enumerate(models):
            is_fallback = attempt > 0
            if is_fallback:
                self.metrics["fallbacks"] += 1
            try:
                result = self._call_with_retry(
                    messages,
                    model=model,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    schema_hint=schema_hint,
                )
                result.model = model
                result.provider = self.provider_name
                self._breaker.record_success()
                self._record(result)
                if cache_key:
                    self._cache.set(
                        cache_key,
                        {
                            "text": result.text,
                            "model": model,
                            "provider": self.provider_name,
                            "structured": result.structured,
                        },
                    )
                return result
            except AIOutputInvalidError as exc:
                # Schema problems are not transient; a fallback model can still help.
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._breaker.record_failure()
            if attempt < len(models) - 1:
                self.metrics["retries"] += 1

        self.metrics["failures"] += 1
        raise AIUnavailableError(
            "AI provider is unavailable.",
            details={
                "provider": self.provider_name,
                "tried_models": models,
                "reason": type(last_error).__name__ if last_error else "unknown",
            },
        ) from last_error

    def _call_with_retry(
        self,
        messages: list[Message],
        *,
        model: str,
        json_mode: bool,
        temperature: float,
        max_tokens: int | None,
        schema_hint: str | None,
    ) -> GenerateResult:
        attempts = max(1, settings.llm_max_retries + 1)
        delay = 0.6
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return self.provider.generate(
                    messages,
                    model=model,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    schema_hint=schema_hint,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < attempts - 1:
                    self.metrics["retries"] += 1
                    logger.warning(
                        "AI call failed (attempt %d/%d): %s",
                        attempt + 1,
                        attempts,
                        type(exc).__name__,
                    )
                    time.sleep(delay)
                    delay *= 2
        raise last_exc if last_exc else AIUnavailableError("AI call failed.")

    def generate_structured(
        self,
        messages: list[Message],
        *,
        schema: type,
        namespace: str | None = None,
        temperature: float = 0.4,
        use_cache: bool = True,
        hint: str | None = None,
    ) -> tuple[Any, GenerateResult]:
        """Generate JSON conforming to `schema`, retrying once with a repair prompt.

        Returns the validated model plus the raw generation result so the caller
        can record tokens, model and prompt version on `skill_runs`.
        """
        schema_hint = hint or _schema_hint(schema)
        result = self.generate(
            messages,
            capability="structured",
            json_mode=True,
            temperature=temperature,
            schema_hint=schema_hint,
            namespace=namespace,
            use_cache=use_cache,
        )
        payload = _parse_json(result.text)
        # Python unbinds an `except ... as name` target at block exit, so the
        # repair prompt must capture the message inside the handler.
        first_error_message = ""
        try:
            parsed = schema.model_validate(payload)
            result.structured = payload
            return parsed, result
        except ValidationError as first_error:
            first_error_message = _format_validation_error(first_error)
            logger.warning(
                "Structured output failed validation (%s); requesting repair",
                type(first_error).__name__,
            )

        repair = [
            *messages,
            Message(
                role="user",
                content=(
                    "Your previous reply was not valid for the required schema.\n"
                    f"Validation error: {first_error_message[:600]}\n"
                    f"Schema: {schema_hint}\n"
                    "Return ONLY corrected JSON. No prose, no markdown fences."
                ),
            ),
        ]
        repaired = self.generate(
            repair,
            capability="structured",
            json_mode=True,
            temperature=0.0,
            schema_hint=schema_hint,
            namespace=None,
            use_cache=False,
        )
        payload = _parse_json(repaired.text)
        try:
            parsed = schema.model_validate(payload)
        except ValidationError as final_error:
            raise AIOutputInvalidError(
                "The AI response did not match the required schema.",
                details={
                    "schema": schema.__name__,
                    "reason": _format_validation_error(final_error)[:400],
                },
            ) from final_error
        repaired.structured = payload
        repaired.warnings.append("output_repaired")
        return parsed, repaired

    # -- embeddings -------------------------------------------------------
    def embed(self, texts: list[str], *, namespace: str | None = None) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=settings.embed_model, provider=self.provider_name)
        if namespace:
            cached = self._cache.get(ResponseCache.key(f"embed:{namespace}", {"t": texts}))
            if cached is not None:
                self.metrics["cache_hits"] += 1
                return EmbeddingResult(
                    vectors=cached["vectors"],
                    model=cached["model"],
                    provider=self.provider_name,
                    cached=True,
                )
        result = self.provider.embed(texts, model=settings.embed_model)
        self.metrics["calls"] += 1
        self.metrics["tokens_in"] += result.tokens_in
        self.metrics["cost_usd"] += result.cost_usd
        if namespace:
            self._cache.set(
                ResponseCache.key(f"embed:{namespace}", {"t": texts}),
                {"vectors": result.vectors, "model": result.model},
            )
        return result

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text]).vectors[0]

    # -- vision / stt -----------------------------------------------------
    def describe_images(
        self,
        images: list[tuple[bytes, str]],
        prompt: str,
        *,
        namespace: str | None = None,
        json_mode: bool = False,
    ) -> GenerateResult:
        if not images:
            return GenerateResult(text="", model=settings.vision_model, provider=self.provider_name)
        if namespace:
            cached = self._cache.get(
                ResponseCache.key(f"vision:{namespace}", {"n": len(images), "p": prompt})
            )
            if cached is not None:
                self.metrics["cache_hits"] += 1
                return GenerateResult(
                    text=cached["text"],
                    model=cached["model"],
                    provider=self.provider_name,
                    cached=True,
                )
        result = self.provider.describe_images(
            images, prompt, model=settings.vision_model, json_mode=json_mode
        )
        self.metrics["calls"] += 1
        self._record(result)
        if namespace:
            self._cache.set(
                ResponseCache.key(f"vision:{namespace}", {"n": len(images), "p": prompt}),
                {"text": result.text, "model": result.model},
            )
        return result

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        result = self.provider.transcribe(audio_path, model=settings.stt_model)
        self.metrics["calls"] += 1
        return result

    # -- internals --------------------------------------------------------
    def _models_for(self, capability: Capability) -> list[str]:
        if capability == "vision":
            primary, fallback = settings.vision_model, settings.llm_model_fallback
        else:
            primary, fallback = settings.llm_model_primary, settings.llm_model_fallback
        return [m for m in (primary, fallback) if m]

    def _record(self, result: GenerateResult) -> None:
        self.metrics["calls"] += 1
        self.metrics["tokens_in"] += result.tokens_in
        self.metrics["tokens_out"] += result.tokens_out
        self.metrics["cost_usd"] += result.cost_usd
        bucket = self.metrics["by_provider"].setdefault(result.provider, {"calls": 0})
        bucket["calls"] += 1


def _format_validation_error(error: ValidationError) -> str:
    """Compact, model-readable list of schema violations for the repair prompt."""
    lines: list[str] = []
    for item in error.errors()[:8]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "(root)"
        lines.append(f"- {location}: {item.get('msg', 'invalid')}")
    return "\n".join(lines)


def _schema_hint(schema: type) -> str:
    """JSON-schema fragment handed to json_mode providers."""
    try:
        return json.dumps(schema.model_json_schema(), separators=(",", ":"))[:4000]
    except Exception:  # noqa: BLE001
        return schema.__name__


def _parse_json(text: str) -> dict[str, Any]:
    """Extract JSON from a model reply, tolerating markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if "```" in cleaned:
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start_candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
        if not start_candidates:
            raise AIOutputInvalidError(
                "The AI response was not JSON.", details={"preview": cleaned[:200]}
            ) from exc
        start = min(start_candidates)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end <= start:
            raise AIOutputInvalidError(
                "The AI response was not valid JSON.", details={"preview": cleaned[:200]}
            ) from exc
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIOutputInvalidError(
                "The AI response was not valid JSON.", details={"preview": cleaned[:200]}
            ) from exc
    if not isinstance(parsed, dict):
        raise AIOutputInvalidError(
            "The AI response must be a JSON object.", details={"type": type(parsed).__name__}
        )
    return parsed


_gateway: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway()
    return _gateway


def set_gateway(gateway: ModelGateway | None) -> None:
    """Injection point for tests (`FakeProvider`)."""
    global _gateway
    _gateway = gateway