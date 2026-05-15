"""
Pydantic DTOs para sports-data-api.

Cada entidad de negocio expone tres formas:
- ``XCreate``  : payload de POST, sin campos derivados del server (id, timestamps).
- ``XUpdate``  : payload de PATCH, todos los campos opcionales; tenant_id e id NO se cambian.
- ``XRead``    : respuesta de GET; incluye id, tenant_id (cuando aplica) y timestamps.

Los DTOs usan los Enums declarados en ``db/models`` directamente, así Pydantic
valida los valores contra los mismos símbolos que SQLAlchemy persiste.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sports_data_api.db.models import (
    APIKeyRole,
    EventType,
    PipelineStatus,
    ReviewStatus,
)


# =============================================================================
# Tenant
# =============================================================================

class TenantBase(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1)
    status: str = "active"
    # NOTA: no usamos alias="metadata" porque `DeclarativeBase` (SQLAlchemy)
    # define un atributo de clase `metadata` (el MetaData registry). Si Pydantic
    # lo lee por alias termina obteniendo el MetaData() en lugar de nuestro
    # JSONB. El wire format usa `metadata_json` para evitar la colisión.
    metadata_json: dict = Field(default_factory=dict)


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    display_name: str | None = None
    status: str | None = None
    metadata_json: dict | None = None


class TenantRead(TenantBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Season
# =============================================================================

class SeasonBase(BaseModel):
    name: str = Field(min_length=1)
    start_date: date
    end_date: date


class SeasonCreate(SeasonBase):
    # tenant_id se inyecta server-side desde X-Tenant-ID (S0.4-A).
    pass


class SeasonUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class SeasonRead(SeasonBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Team
# =============================================================================

class TeamBase(BaseModel):
    external_id: str | None = None
    name: str
    level: str | None = None
    city: str | None = None
    country: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class TeamCreate(TeamBase):
    # tenant_id se inyecta server-side desde X-Tenant-ID (S0.4-A).
    pass


class TeamUpdate(BaseModel):
    name: str | None = None
    level: str | None = None
    city: str | None = None
    country: str | None = None
    metadata_json: dict | None = None


class TeamRead(TeamBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Player
# =============================================================================

class PlayerBase(BaseModel):
    external_id: str | None = None
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    height_cm: int | None = None
    position: str | None = None
    dominant_hand: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class PlayerCreate(PlayerBase):
    # tenant_id se inyecta server-side desde X-Tenant-ID (S0.4-A).
    pass


class PlayerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    height_cm: int | None = None
    position: str | None = None
    dominant_hand: str | None = None
    metadata_json: dict | None = None


class PlayerRead(PlayerBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Game
# =============================================================================

class GameBase(BaseModel):
    external_id: str | None = None
    season_id: UUID | None = None
    home_team_id: UUID
    away_team_id: UUID
    played_at: datetime
    venue: str | None = None
    final_score_home: int | None = None
    final_score_away: int | None = None
    video_uri: str
    video_duration_seconds: float
    video_width: int | None = None
    video_height: int | None = None


class GameCreate(GameBase):
    # tenant_id se inyecta server-side desde X-Tenant-ID (S0.4-A).
    # pipeline_status default ``pending`` lo pone el ORM.
    pass


class GameUpdate(BaseModel):
    season_id: UUID | None = None
    played_at: datetime | None = None
    venue: str | None = None
    final_score_home: int | None = None
    final_score_away: int | None = None
    video_uri: str | None = None
    video_duration_seconds: float | None = None
    video_width: int | None = None
    video_height: int | None = None
    pipeline_status: PipelineStatus | None = None
    last_pipeline_run_id: UUID | None = None


class GameRead(GameBase):
    id: UUID
    tenant_id: UUID
    pipeline_status: PipelineStatus
    last_pipeline_run_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# PipelineRun
# =============================================================================
# Nota: tenant_id NO se acepta en el payload; se hereda desde el game.

class PipelineRunCreate(BaseModel):
    game_id: UUID
    pipeline_version: str
    config_snapshot: dict
    status: PipelineStatus = PipelineStatus.running


class PipelineRunUpdate(BaseModel):
    status: PipelineStatus | None = None
    metrics: dict | None = None
    error: str | None = None
    finished_at: datetime | None = None


class PipelineRunRead(BaseModel):
    id: UUID
    tenant_id: UUID
    game_id: UUID
    pipeline_version: str
    status: PipelineStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    metrics: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Event
# =============================================================================
# Nota: tenant_id NO se acepta en el payload; se hereda desde el game.

class EventCreate(BaseModel):
    game_id: UUID
    pipeline_run_id: UUID | None = None
    start_time_seconds: float
    end_time_seconds: float
    quarter: int | None = None
    game_clock_seconds: float | None = None
    court_x: float | None = None
    court_y: float | None = None
    event_type: EventType = EventType.unknown
    player_id: UUID | None = None
    team_id: UUID | None = None
    assist_player_id: UUID | None = None
    raw_score: float = 0.0
    confidence: float = 1.0
    signals: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    vlm_metadata: dict | None = None


class EventRead(BaseModel):
    id: UUID
    tenant_id: UUID
    game_id: UUID
    pipeline_run_id: UUID | None = None
    start_time_seconds: float
    end_time_seconds: float
    event_type: EventType
    player_id: UUID | None = None
    team_id: UUID | None = None
    assist_player_id: UUID | None = None
    raw_score: float
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    # Revisión humana (S1-A)
    review_status: ReviewStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    clip_id: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# APIKey (S0.4-D)
# =============================================================================
# El key crudo se devuelve UNA sola vez, en APIKeyCreateResponse. Después la
# API sólo expone metadata: nunca el hash ni el token completo.

class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, description="Etiqueta legible del key.")
    role: APIKeyRole
    expires_at: datetime | None = Field(
        default=None, description="Si se omite, el key no expira."
    )
    # Sólo lo usa el flujo de root token (mintear para cualquier tenant). Con
    # un admin-key se ignora: el tenant sale del contexto del caller.
    tenant_id: UUID | None = Field(
        default=None,
        description="Tenant destino. Obligatorio con root token; ignorado con admin-key.",
    )


class APIKeyRead(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    key_prefix: str
    role: APIKeyRole
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreateResponse(APIKeyRead):
    # El token completo — se muestra SÓLO en la respuesta del POST. Guardalo:
    # no se puede volver a recuperar.
    api_key: str


# =============================================================================
# Event review / tagging (S1-A)
# =============================================================================
# El pipeline crea eventos con EventCreate; un revisor humano los corrige con
# EventReviewUpdate (PATCH) o en lote con BulkEventReview. Cada revisión deja
# una fila de auditoría en event_tags (EventTagRead).

class EventReviewUpdate(BaseModel):
    """Payload del PATCH de revisión humana de un evento.

    Todos los campos de revisión son opcionales: lo que no venga, no se toca
    (se aplica con ``exclude_unset=True``). ``reviewed_by`` es obligatorio —
    identifica quién hizo la revisión.
    """

    reviewed_by: str = Field(min_length=1, description="Quién revisa/taggea.")
    event_type: EventType | None = None
    player_id: UUID | None = None
    team_id: UUID | None = None
    assist_player_id: UUID | None = None
    review_status: ReviewStatus | None = None
    review_notes: str | None = None
    clip_id: UUID | None = None


class BulkEventReviewItem(BaseModel):
    """Una corrección dentro de un BulkEventReview."""

    event_id: UUID
    event_type: EventType | None = None
    player_id: UUID | None = None
    team_id: UUID | None = None
    assist_player_id: UUID | None = None
    review_status: ReviewStatus | None = None
    review_notes: str | None = None
    clip_id: UUID | None = None


class BulkEventReview(BaseModel):
    """Tagging masivo desde la UI: un revisor, varios eventos, una transacción."""

    reviewed_by: str = Field(min_length=1, description="Quién revisa/taggea.")
    items: list[BulkEventReviewItem] = Field(min_length=1)


class EventTagRead(BaseModel):
    """Fila de auditoría: el antes/después de una revisión."""

    id: UUID
    tenant_id: UUID
    event_id: UUID
    tagger: str
    tagged_at: datetime
    before_json: dict | None = None
    after_json: dict | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Clip (S1-A)
# =============================================================================
# Un clip es un recorte de video ya subido al storage. La API sólo guarda
# metadata + el URI; no sirve los bytes (eso lo hace nginx/CDN).

class ClipCreate(BaseModel):
    game_id: UUID
    event_id: UUID | None = None
    storage_uri: str = Field(min_length=1)
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    format: str | None = None
    size_bytes: int | None = None
    thumbnail_uri: str | None = None
    # tenant_id se hereda del game (S0.4-A).


class ClipRead(BaseModel):
    id: UUID
    tenant_id: UUID
    game_id: UUID
    event_id: UUID | None = None
    storage_uri: str
    duration_seconds: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    format: str | None = None
    size_bytes: int | None = None
    thumbnail_uri: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
