"""Application configuration.

All environment access is centralised here (AGENTS.md §18). Every value has a
working local default so the application boots without external infrastructure,
while remaining overridable for the documented production topology.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity -------------------------------------------------------
    app_env: Literal["local", "dev", "staging", "production"] = "local"
    debug: bool = True

    # --- Database (Postgres in production, SQLite for local runs) -------
    # D-020: the DSN is abstracted so the identical SQLAlchemy models run on
    # SQLite when no Postgres server is reachable.
    database_url: str = "sqlite+pysqlite:///./creatorai.db"
    database_echo: bool = False

    # --- Supabase (auth + storage) -------------------------------------
    # D-023: when unset, the local adapters are used instead of Supabase.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    # D-005/D-021: queue backend. "auto" uses RQ when Redis answers, otherwise
    # the threaded in-process queue.
    redis_url: str = ""
    queue_backend: Literal["auto", "rq", "thread"] = "auto"
    queue_name: str = "creatorai"
    queue_workers: int = 4
    #: Worker-loop flags for `python -m app.workers.worker`.
    queue_worker_burst: bool = False
    queue_worker_scheduler: bool = False

    # --- AI provider (D-024) -------------------------------------------
    # The application depends on AIProvider, never on a vendor SDK.
    ai_provider: Literal["grok", "openai_compatible", "dev"] = "dev"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.x.ai/v1"
    llm_model_primary: str = "grok-2-latest"
    llm_model_fallback: str = "grok-2-mini-latest"
    vision_model: str = "grok-2-vision-latest"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536
    stt_model: str = "whisper-1"
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 2
    llm_circuit_breaker_threshold: int = 5
    ai_cache_ttl_s: int = 86_400
    ai_cache_enabled: bool = True

    # --- Product limits (SECURITY.md §3, VIDEO-PIPELINE.md §1) ---------
    max_upload_mb: int = 200
    max_video_duration_s: int = 180
    max_frames_analyzed: int = 40
    signed_url_ttl_s: int = 3600
    upload_url_ttl_s: int = 300
    #: Measured average delivery rate used to convert words to seconds
    #: (AI-SKILLS.md hook budget). Measurement, not judgement: keep in config.
    speech_words_per_second: float = 2.8
    #: Suggested clear floor area for full-body vertical recording.
    recording_floor_m: float = 5.0

    # --- Clip scoring (AI-SKILLS.md `clip.generate`) ---------------------
    # The documented weights, kept in config because they are tuned on sample
    # videos rather than fixed by the algorithm.
    clip_weight_relevance: float = 0.35
    clip_weight_hook: float = 0.25
    clip_weight_visual_quality: float = 0.20
    clip_weight_completeness: float = 0.10
    clip_weight_dna_fit: float = 0.10
    #: Candidate window bounds, aligned to segment/scene boundaries.
    clip_window_min_s: float = 15.0
    clip_window_max_s: float = 45.0
    #: A candidate must clear this to be offered to the creator.
    clip_min_confidence: float = 0.35
    #: Candidates overlapping a kept candidate by more than this are suppressed.
    clip_nms_overlap: float = 0.30
    clip_max_candidates: int = 5
    #: Dance-without-speech path: confidence is capped and the result flagged.
    clip_visual_only_confidence_cap: float = 0.70
    #: Scene detection (VIDEO-PIPELINE.md §2).
    scene_min_duration_s: float = 1.0
    scene_max_count: int = 40

    # --- Media ---------------------------------------------------------
    # D-022: probed at startup; absent ffmpeg degrades stages honestly.
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    local_storage_dir: str = ".local-storage"
    temp_dir: str = ".tmp"

    # --- Rate limits (SECURITY.md §9) ----------------------------------
    rate_limit_general: int = 60
    rate_limit_ai: int = 10
    rate_limit_uploads_per_hour: int = 20
    max_concurrent_jobs_per_user: int = 2

    # --- Frontend -------------------------------------------------------
    next_public_api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Demo mode (D-013) ---------------------------------------------
    demo_mode: bool = False
    demo_owner_id: str = "00000000-0000-0000-0000-000000000001"

    # D-023: when Supabase is not configured the API accepts a signed-in
    # development identity so the product is usable without an auth project.
    auth_mode: Literal["supabase", "dev"] = "dev"

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Accept the common Postgres spellings people paste from dashboards."""
        value = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                value = value.replace(prefix, "postgresql+psycopg2://", 1)
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def use_rls(self) -> bool:
        """Row Level Security only exists on Postgres (SECURITY.md §1)."""
        return not self.is_sqlite

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def has_llm_credentials(self) -> bool:
        return bool(self.llm_api_key)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()