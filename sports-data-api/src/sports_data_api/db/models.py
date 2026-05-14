from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BIGINT,
    CheckConstraint,
    DATE,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sports_data_api.db.base import Base


# =============================================================================
# ENUMS
# =============================================================================

class EventType(str, enum.Enum):
    shot_attempt = "shot_attempt"
    made_shot = "made_shot"
    missed_shot = "missed_shot"
    three_pointer_attempt = "three_pointer_attempt"
    three_pointer_made = "three_pointer_made"
    rebound_offensive = "rebound_offensive"
    rebound_defensive = "rebound_defensive"
    assist = "assist"
    block = "block"
    steal = "steal"
    turnover = "turnover"
    foul = "foul"
    fast_break = "fast_break"
    screen = "screen"
    celebration = "celebration"
    unknown = "unknown"


class ReviewStatus(str, enum.Enum):
    unreviewed = "unreviewed"
    confirmed = "confirmed"
    corrected = "corrected"
    rejected = "rejected"


class PipelineStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    processing = "processing"
    ready = "ready"
    succeeded = "succeeded"
    failed = "failed"


class APIKeyRole(str, enum.Enum):
    pipeline = "pipeline"
    reviewer = "reviewer"
    readonly = "readonly"
    admin = "admin"


class ScoutingAudience(str, enum.Enum):
    coach = "coach"
    scout = "scout"
    recruit = "recruit"
    parent = "parent"


class ScoutingStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


# =============================================================================
# MODELS
# =============================================================================

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[date] = mapped_column(DATE, nullable=False)
    end_date: Mapped[date] = mapped_column(DATE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_seasons_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "name"),
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_teams_tenant", "tenant_id"),
        # Index GIN para fuzzy search requiere pg_trgm
        Index("idx_teams_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        UniqueConstraint("tenant_id", "external_id"),
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(DATE)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[str | None] = mapped_column(String)
    dominant_hand: Mapped[str | None] = mapped_column(String, CheckConstraint("dominant_hand IN ('L','R','B')"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_players_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "external_id"),
    )


class PlayerTeamMembership(Base):
    __tablename__ = "player_team_memberships"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[UUID | None] = mapped_column(ForeignKey("seasons.id"))
    jersey_number: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(DATE, nullable=False)
    end_date: Mapped[date | None] = mapped_column(DATE)

    __table_args__ = (
        Index("idx_ptm_tenant", "tenant_id"),
        Index("idx_ptm_player", "player_id"),
        Index("idx_ptm_team_season", "team_id", "season_id"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date"),
        UniqueConstraint("tenant_id", "team_id", "season_id", "jersey_number"),
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    season_id: Mapped[UUID | None] = mapped_column(ForeignKey("seasons.id"))
    home_team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    venue: Mapped[str | None] = mapped_column(String)
    final_score_home: Mapped[int | None] = mapped_column(Integer)
    final_score_away: Mapped[int | None] = mapped_column(Integer)
    
    video_uri: Mapped[str] = mapped_column(String, nullable=False)
    video_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    video_width: Mapped[int | None] = mapped_column(Integer)
    video_height: Mapped[int | None] = mapped_column(Integer)
    pipeline_status: Mapped[PipelineStatus] = mapped_column(Enum(PipelineStatus), nullable=False, default=PipelineStatus.pending)
    last_pipeline_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_games_tenant_played", "tenant_id", "played_at"),
        CheckConstraint("home_team_id <> away_team_id"),
        UniqueConstraint("tenant_id", "external_id"),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pipeline_version: Mapped[str] = mapped_column(String, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[PipelineStatus] = mapped_column(Enum(PipelineStatus), nullable=False, default=PipelineStatus.processing)
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_pipeline_runs_game", "game_id", "started_at"),
        Index("idx_pipeline_runs_tenant", "tenant_id"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    pipeline_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))

    start_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    quarter: Mapped[int | None] = mapped_column(CheckConstraint("quarter BETWEEN 1 AND 8"))
    game_clock_seconds: Mapped[float | None] = mapped_column(Float)

    court_x: Mapped[float | None] = mapped_column(Float, CheckConstraint("court_x BETWEEN 0 AND 1"))
    court_y: Mapped[float | None] = mapped_column(Float, CheckConstraint("court_y BETWEEN 0 AND 1"))

    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False, default=EventType.unknown)
    player_id: Mapped[UUID | None] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"))
    assist_player_id: Mapped[UUID | None] = mapped_column(ForeignKey("players.id"))

    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    vlm_metadata: Mapped[dict | None] = mapped_column(JSONB)

    review_status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), nullable=False, default=ReviewStatus.unreviewed)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    clip_id: Mapped[UUID | None] = mapped_column(ForeignKey("clips.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_events_tenant", "tenant_id"),
        Index("idx_events_game", "game_id", "start_time_seconds"),
        CheckConstraint("end_time_seconds > start_time_seconds"),
    )


class EventTag(Base):
    __tablename__ = "event_tags"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    tagger: Mapped[str] = mapped_column(String, nullable=False)
    tagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    before_json: Mapped[dict | None] = mapped_column("before", JSONB)
    after_json: Mapped[dict | None] = mapped_column("after", JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_event_tags_event", "event_id", "tagged_at"),
        Index("idx_event_tags_tenant", "tenant_id"),
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    format: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(BIGINT)
    thumbnail_uri: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_clips_tenant", "tenant_id"),
        Index("idx_clips_game", "game_id"),
        Index("idx_clips_event", "event_id"),
    )


class ScoutingReport(Base):
    __tablename__ = "scouting_reports"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[UUID | None] = mapped_column(ForeignKey("seasons.id"))
    game_filter_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    audience: Mapped[ScoutingAudience] = mapped_column(Enum(ScoutingAudience), nullable=False)
    
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String, nullable=False)
    source_event_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False)
    source_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    status: Mapped[ScoutingStatus] = mapped_column(Enum(ScoutingStatus), nullable=False, default=ScoutingStatus.draft)

    __table_args__ = (
        Index("idx_reports_player_recent", "player_id", "generated_at"),
        Index("idx_reports_tenant", "tenant_id"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[APIKeyRole] = mapped_column(Enum(APIKeyRole), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_api_keys_tenant", "tenant_id"),
    )
