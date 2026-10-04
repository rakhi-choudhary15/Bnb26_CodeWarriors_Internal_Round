"""SQLAlchemy models mirroring `DATA-MODEL.md` §2 exactly.

Naming, ownership columns and enums follow the data model so a reviewer can
diff the two files. RLS policies are in `app/core/rls.sql` and applied by the
Alembic migration on Postgres only.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import (
    Base,
    JSONBType,
    TimestampMixin,
    VectorType,
    utcnow,
)

UUID = uuid.UUID


# ---------------------------------------------------------------------------
# Enums (lowercase values per AGENTS.md §6)
# ---------------------------------------------------------------------------
class AssetKind(str, enum.Enum):
    video = "video"
    image = "image"
    audio = "audio"
    script = "script"
    reference = "reference"
    creator = "creator"
    brand = "brand"


class AssetStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    rejected = "rejected"
    failed = "failed"


class StepStatus(str, enum.Enum):
    locked = "locked"
    ready = "ready"
    running = "running"
    needs_review = "needs_review"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class ImplStatus(str, enum.Enum):
    real = "real"
    mocked = "mocked"
    stubbed = "stubbed"
    future = "future"


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    planning = "planning"
    producing = "producing"
    editing = "editing"
    published = "published"
    archived = "archived"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class JobType(str, enum.Enum):
    asset_process = "asset.process"
    video_analyze = "video.analyze"
    clips_generate = "clips.generate"
    edit_render = "edit.render"
    archaeology_scan = "archaeology.scan"
    genome_propagate = "genome.propagate"
    dna_learn = "dna.learn"
    reference_analyze = "reference.analyze"


class NodeType(str, enum.Enum):
    idea = "idea"
    script = "script"
    hook = "hook"
    claim = "claim"
    topic = "topic"
    footage = "footage"
    scene = "scene"
    broll = "broll"
    audio = "audio"
    asset = "asset"
    clip = "clip"
    edit = "edit"
    variant = "variant"
    published = "published"


class NodeState(str, enum.Enum):
    current = "current"
    stale = "stale"
    archived = "archived"


class EdgeRelation(str, enum.Enum):
    derived_from = "derived_from"
    contains = "contains"
    uses = "uses"
    adapts = "adapts"
    quotes = "quotes"
    matches = "matches"


class ImpactLevel(str, enum.Enum):
    affected = "affected"
    text_affected = "text_affected"
    possibly_affected = "possibly_affected"


class Platform(str, enum.Enum):
    instagram_reels = "instagram_reels"
    youtube_shorts = "youtube_shorts"
    tiktok = "tiktok"
    youtube = "youtube"
    linkedin = "linkedin"
    other = "other"


class ClipStatus(str, enum.Enum):
    candidate = "candidate"
    accepted = "accepted"
    rejected = "rejected"


class MatchMethod(str, enum.Enum):
    semantic = "semantic"
    visual = "visual"
    beat = "beat"
    manual = "manual"


class OpportunityKind(str, enum.Enum):
    short_form = "short_form"
    educational_clip = "educational_clip"
    social_post = "social_post"
    carousel = "carousel"
    new_idea = "new_idea"
    gap = "gap"


class EffortLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class OpportunityStatus(str, enum.Enum):
    new = "new"
    accepted = "accepted"
    dismissed = "dismissed"


class Resolution(str, enum.Enum):
    pending = "pending"
    updated = "updated"
    ignored = "ignored"
    reviewed = "reviewed"


def _enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """Enum column using the lowercase *values* as the DB representation."""
    return SAEnum(
        py_enum,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(120))


class CreatorDNA(Base, TimestampMixin):
    __tablename__ = "creator_dna"
    __table_args__ = (Index("ix_creator_dna_owner_version", "owner_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    profile: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_owner_status", "owner_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus, "project_status"), nullable=False, default=ProjectStatus.draft
    )
    intent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    blueprint_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class CreationIntent(Base, TimestampMixin):
    __tablename__ = "creation_intents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    primary_text: Mapped[str] = mapped_column(String(500), nullable=False)
    details_text: Mapped[str | None] = mapped_column(Text)
    parsed: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    confidence: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CreationBlueprint(Base, TimestampMixin):
    __tablename__ = "creation_blueprints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    intent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stages: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    expected_output: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("creation_blueprints.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    current_step_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    steps: Mapped[list[WorkflowStep]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.position"
    )


class WorkflowStep(Base, TimestampMixin):
    __tablename__ = "workflow_steps"
    __table_args__ = (Index("ix_workflow_steps_workflow_position", "workflow_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text)
    skill_ids: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    needs: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    status: Mapped[StepStatus] = mapped_column(
        _enum(StepStatus, "step_status"), nullable=False, default=StepStatus.locked
    )
    input: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    output_ref: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impl_status: Mapped[ImplStatus] = mapped_column(
        _enum(ImplStatus, "impl_status"), nullable=False, default=ImplStatus.real
    )
    error: Mapped[str | None] = mapped_column(Text)

    workflow: Mapped[Workflow] = relationship(back_populates="steps")


class AISkill(Base, TimestampMixin):
    __tablename__ = "ai_skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ImplStatus] = mapped_column(
        _enum(ImplStatus, "impl_status"), nullable=False, default=ImplStatus.real
    )
    spec: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SkillRun(Base):
    __tablename__ = "skill_runs"
    __table_args__ = (Index("ix_skill_runs_project_created", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    step_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ok")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Assets & media
# ---------------------------------------------------------------------------
class Asset(Base, TimestampMixin):
    __tablename__ = "assets"
    __table_args__ = (Index("ix_assets_owner_kind_status", "owner_id", "kind", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind, "asset_kind"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[AssetStatus] = mapped_column(
        _enum(AssetStatus, "asset_status"), nullable=False, default=AssetStatus.pending
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssetEmbedding(Base):
    __tablename__ = "asset_embeddings"
    __table_args__ = (Index("ix_asset_embeddings_asset_scope", "asset_id", "scope"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="asset")
    ref_start_s: Mapped[float | None] = mapped_column(Float)
    ref_end_s: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list] = mapped_column(VectorType, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Scripts & hooks
# ---------------------------------------------------------------------------
class Script(Base, TimestampMixin):
    __tablename__ = "scripts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled script")


class ScriptVersion(Base):
    __tablename__ = "script_versions"
    __table_args__ = (
        UniqueConstraint("script_id", "version", name="uq_script_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    script_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    lines: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Hook(Base, TimestampMixin):
    __tablename__ = "hooks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    script_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(String(40), nullable=False, default="bold_claim")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


# ---------------------------------------------------------------------------
# References & shots
# ---------------------------------------------------------------------------
class Reference(Base, TimestampMixin):
    __tablename__ = "references"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Reference")
    creator_attribution: Mapped[str | None] = mapped_column(String(200))
    license_note: Mapped[str | None] = mapped_column(Text)
    rights_attested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


class ReferenceDNA(Base):
    __tablename__ = "reference_dna"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("references.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    dna: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ShotPlan(Base, TimestampMixin):
    __tablename__ = "shot_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    total_duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shots: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    checklist: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# ---------------------------------------------------------------------------
# Video understanding
# ---------------------------------------------------------------------------
class VideoAnalysis(Base, TimestampMixin):
    __tablename__ = "video_analyses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stages: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    language: Mapped[str | None] = mapped_column(String(16))
    transcript_json: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (Index("ix_transcript_segments_asset_idx", "asset_id", "idx"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list | None] = mapped_column(VectorType, nullable=True)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (Index("ix_scenes_asset_idx", "asset_id", "idx"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    keyframe_path: Mapped[str | None] = mapped_column(String(512))
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    quality: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    embedding: Mapped[list | None] = mapped_column(VectorType, nullable=True)


class ScriptFootageMatch(Base):
    __tablename__ = "script_footage_matches"
    __table_args__ = (
        Index("ix_matches_version_line", "script_version_id", "line_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    script_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("script_versions.id", ondelete="CASCADE"), nullable=False
    )
    line_id: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[MatchMethod] = mapped_column(
        _enum(MatchMethod, "match_method"), nullable=False, default=MatchMethod.semantic
    )
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Clips, edits, variants
# ---------------------------------------------------------------------------
class Clip(Base, TimestampMixin):
    __tablename__ = "clips"
    __table_args__ = (Index("ix_clips_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    target_platform: Mapped[Platform] = mapped_column(
        _enum(Platform, "platform"), nullable=False, default=Platform.instagram_reels
    )
    status: Mapped[ClipStatus] = mapped_column(
        _enum(ClipStatus, "clip_status"), nullable=False, default=ClipStatus.candidate
    )
    score_breakdown: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class Edit(Base, TimestampMixin):
    __tablename__ = "edits"
    __table_args__ = (
        UniqueConstraint("clip_id", "version", name="uq_edit_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    edl: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    suggestions: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    render_asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")


class PlatformVariant(Base, TimestampMixin):
    __tablename__ = "platform_variants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"), nullable=False)
    aspect: Mapped[str] = mapped_column(String(16), nullable=False, default="9:16")
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hashtags: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    adaptation_notes: Mapped[str | None] = mapped_column(Text)
    render_asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    impl_status: Mapped[ImplStatus] = mapped_column(
        _enum(ImplStatus, "impl_status"), nullable=False, default=ImplStatus.real
    )


class PublishingJob(Base, TimestampMixin):
    __tablename__ = "publishing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_variants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="stubbed")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_url: Mapped[str | None] = mapped_column(String(512))
    impl_status: Mapped[ImplStatus] = mapped_column(
        _enum(ImplStatus, "impl_status"), nullable=False, default=ImplStatus.stubbed
    )
    export_package: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class AnalyticsRecord(Base):
    __tablename__ = "analytics"
    __table_args__ = (
        UniqueConstraint("variant_id", "metric_date", name="uq_analytics_variant_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_variants.id", ondelete="CASCADE"), nullable=False
    )
    metric_date: Mapped[str] = mapped_column(String(10), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")


# ---------------------------------------------------------------------------
# Content Genome
# ---------------------------------------------------------------------------
class ContentNode(Base, TimestampMixin):
    __tablename__ = "content_nodes"
    __table_args__ = (
        Index("ix_content_nodes_owner_project", "owner_id", "project_id"),
        Index("ix_content_nodes_ref", "ref_table", "ref_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[NodeType] = mapped_column(_enum(NodeType, "node_type"), nullable=False)
    ref_table: Mapped[str | None] = mapped_column(String(48))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[NodeState] = mapped_column(
        _enum(NodeState, "node_state"), nullable=False, default=NodeState.current
    )
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class ContentEdge(Base, TimestampMixin):
    __tablename__ = "content_edges"
    __table_args__ = (
        UniqueConstraint("from_node", "to_node", "relation", name="uq_edge_triple"),
        Index("ix_content_edges_from", "from_node"),
        Index("ix_content_edges_to", "to_node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    from_node: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_nodes.id", ondelete="CASCADE"), nullable=False
    )
    to_node: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_nodes.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[EdgeRelation] = mapped_column(
        _enum(EdgeRelation, "edge_relation"), nullable=False
    )
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class ImpactEvent(Base, TimestampMixin):
    __tablename__ = "impact_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trigger_node_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    change: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ImpactItem(Base, TimestampMixin):
    __tablename__ = "impact_items"
    __table_args__ = (Index("ix_impact_items_event", "impact_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    impact_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("impact_events.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_nodes.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[ImpactLevel] = mapped_column(
        _enum(ImpactLevel, "impact_level"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_change: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    resolution: Mapped[Resolution] = mapped_column(
        _enum(Resolution, "resolution"), nullable=False, default=Resolution.pending
    )


class ContentOpportunity(Base, TimestampMixin):
    __tablename__ = "content_opportunities"
    __table_args__ = (Index("ix_opportunities_owner_status", "owner_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[OpportunityKind] = mapped_column(
        _enum(OpportunityKind, "opportunity_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_asset_ids: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    source_ranges: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    effort: Mapped[EffortLevel] = mapped_column(
        _enum(EffortLevel, "effort_level"), nullable=False, default=EffortLevel.medium
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[OpportunityStatus] = mapped_column(
        _enum(OpportunityStatus, "opportunity_status"), nullable=False, default=OpportunityStatus.new
    )
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="archaeology")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_owner_status", "owner_id", "status"),
        Index("ix_jobs_input_hash", "input_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    type: Mapped[JobType] = mapped_column(_enum(JobType, "job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), nullable=False, default=JobStatus.queued
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))