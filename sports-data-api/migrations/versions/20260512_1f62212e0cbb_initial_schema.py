"""initial_schema

Revision ID: 1f62212e0cbb
Revises: 
Create Date: 2026-05-12 23:59:17.759712+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = '1f62212e0cbb'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 1. Tenants (no dependencies)
    op.create_table('tenants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )

    # 2. Players (depends on tenants)
    op.create_table('players',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('first_name', sa.String(), nullable=False),
        sa.Column('last_name', sa.String(), nullable=False),
        sa.Column('date_of_birth', sa.DATE(), nullable=True),
        sa.Column('height_cm', sa.Integer(), nullable=True),
        sa.Column('position', sa.String(), nullable=True),
        sa.Column('dominant_hand', sa.String(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'external_id')
    )
    op.create_index('idx_players_tenant', 'players', ['tenant_id'], unique=False)

    # 3. Seasons (depends on tenants)
    op.create_table('seasons',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('start_date', sa.DATE(), nullable=False),
        sa.Column('end_date', sa.DATE(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name')
    )
    op.create_index('idx_seasons_tenant', 'seasons', ['tenant_id'], unique=False)

    # 4. Teams (depends on tenants)
    op.create_table('teams',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('level', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'external_id')
    )
    op.create_index('idx_teams_name_trgm', 'teams', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_index('idx_teams_tenant', 'teams', ['tenant_id'], unique=False)

    # 5. Games (depends on tenants, seasons, teams)
    op.create_table('games',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('season_id', sa.UUID(), nullable=True),
        sa.Column('home_team_id', sa.UUID(), nullable=False),
        sa.Column('away_team_id', sa.UUID(), nullable=False),
        sa.Column('played_at', sa.DateTime(), nullable=False),
        sa.Column('venue', sa.String(), nullable=True),
        sa.Column('final_score_home', sa.Integer(), nullable=True),
        sa.Column('final_score_away', sa.Integer(), nullable=True),
        sa.Column('video_uri', sa.String(), nullable=False),
        sa.Column('video_duration_seconds', sa.Float(), nullable=False),
        sa.Column('video_width', sa.Integer(), nullable=True),
        sa.Column('video_height', sa.Integer(), nullable=True),
        sa.Column('pipeline_status', sa.Enum('pending', 'processing', 'ready', 'failed', name='pipelinestatus'), nullable=False),
        sa.Column('last_pipeline_run_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('home_team_id <> away_team_id'),
        sa.ForeignKeyConstraint(['away_team_id'], ['teams.id'], ),
        sa.ForeignKeyConstraint(['home_team_id'], ['teams.id'], ),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'external_id')
    )
    op.create_index('idx_games_tenant_played', 'games', ['tenant_id', 'played_at'], unique=False)

    # 6. Pipeline Runs (depends on tenants, games)
    op.create_table('pipeline_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('game_id', sa.UUID(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('pipeline_version', sa.String(), nullable=False),
        sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_pipeline_runs_game', 'pipeline_runs', ['game_id', 'started_at'], unique=False)
    op.create_index('idx_pipeline_runs_tenant', 'pipeline_runs', ['tenant_id'], unique=False)

    # 7. Events (without clip_id FK yet to avoid circular dependency)
    op.create_table('events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('game_id', sa.UUID(), nullable=False),
        sa.Column('pipeline_run_id', sa.UUID(), nullable=True),
        sa.Column('start_time_seconds', sa.Float(), nullable=False),
        sa.Column('end_time_seconds', sa.Float(), nullable=False),
        sa.Column('quarter', sa.Integer(), nullable=True),
        sa.Column('game_clock_seconds', sa.Float(), nullable=True),
        sa.Column('court_x', sa.Float(), nullable=True),
        sa.Column('court_y', sa.Float(), nullable=True),
        sa.Column('event_type', sa.Enum('shot_attempt', 'made_shot', 'missed_shot', 'three_pointer_attempt', 'three_pointer_made', 'rebound_offensive', 'rebound_defensive', 'assist', 'block', 'steal', 'turnover', 'foul', 'fast_break', 'screen', 'celebration', 'unknown', name='eventtype'), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=True),
        sa.Column('team_id', sa.UUID(), nullable=True),
        sa.Column('assist_player_id', sa.UUID(), nullable=True),
        sa.Column('raw_score', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reasons', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('vlm_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('review_status', sa.Enum('unreviewed', 'confirmed', 'corrected', 'rejected', name='reviewstatus'), nullable=False),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('clip_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('end_time_seconds > start_time_seconds'),
        sa.ForeignKeyConstraint(['assist_player_id'], ['players.id'], ),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_events_game', 'events', ['game_id', 'start_time_seconds'], unique=False)
    op.create_index('idx_events_tenant', 'events', ['tenant_id'], unique=False)

    # 8. Clips (depends on tenants, events, games)
    op.create_table('clips',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('event_id', sa.UUID(), nullable=True),
        sa.Column('game_id', sa.UUID(), nullable=False),
        sa.Column('storage_uri', sa.String(), nullable=False),
        sa.Column('duration_seconds', sa.Float(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('fps', sa.Float(), nullable=True),
        sa.Column('format', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.BIGINT(), nullable=True),
        sa.Column('thumbnail_uri', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_clips_event', 'clips', ['event_id'], unique=False)
    op.create_index('idx_clips_game', 'clips', ['game_id'], unique=False)
    op.create_index('idx_clips_tenant', 'clips', ['tenant_id'], unique=False)

    # 9. Add the clip_id FK to events now that clips table exists
    op.create_foreign_key('fk_events_clip', 'events', 'clips', ['clip_id'], ['id'], ondelete='SET NULL')

    # 10. API Keys
    op.create_table('api_keys',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('key_hash', sa.String(), nullable=False),
        sa.Column('key_prefix', sa.String(), nullable=False),
        sa.Column('role', sa.Enum('pipeline', 'reviewer', 'readonly', 'admin', name='apikeyrole'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash')
    )
    op.create_index('idx_api_keys_tenant', 'api_keys', ['tenant_id'], unique=False)

    # 11. Event Tags
    op.create_table('event_tags',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('event_id', sa.UUID(), nullable=False),
        sa.Column('tagger', sa.String(), nullable=False),
        sa.Column('tagged_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_event_tags_event', 'event_tags', ['event_id', 'tagged_at'], unique=False)
    op.create_index('idx_event_tags_tenant', 'event_tags', ['tenant_id'], unique=False)

    # 12. Player Team Memberships
    op.create_table('player_team_memberships',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('team_id', sa.UUID(), nullable=False),
        sa.Column('season_id', sa.UUID(), nullable=True),
        sa.Column('jersey_number', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.DATE(), nullable=False),
        sa.Column('end_date', sa.DATE(), nullable=True),
        sa.CheckConstraint('end_date IS NULL OR end_date >= start_date'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'team_id', 'season_id', 'jersey_number')
    )
    op.create_index('idx_ptm_player', 'player_team_memberships', ['player_id'], unique=False)
    op.create_index('idx_ptm_team_season', 'player_team_memberships', ['team_id', 'season_id'], unique=False)
    op.create_index('idx_ptm_tenant', 'player_team_memberships', ['tenant_id'], unique=False)

    # 13. Scouting Reports
    op.create_table('scouting_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('player_id', sa.UUID(), nullable=False),
        sa.Column('season_id', sa.UUID(), nullable=True),
        sa.Column('game_filter_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column('audience', sa.Enum('coach', 'scout', 'recruit', 'parent', name='scoutingaudience'), nullable=False),
        sa.Column('report_md', sa.Text(), nullable=False),
        sa.Column('report_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('generated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('prompt_template_version', sa.String(), nullable=False),
        sa.Column('source_event_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column('source_event_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('draft', 'published', 'archived', name='scoutingstatus'), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_reports_player_recent', 'scouting_reports', ['player_id', 'generated_at'], unique=False)
    op.create_index('idx_reports_tenant', 'scouting_reports', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_table('scouting_reports')
    op.drop_table('player_team_memberships')
    op.drop_table('event_tags')
    op.drop_table('api_keys')
    op.drop_table('clips')
    op.drop_table('events')
    op.drop_table('pipeline_runs')
    op.drop_table('games')
    op.drop_table('teams')
    op.drop_table('seasons')
    op.drop_table('players')
    op.drop_table('tenants')
    # Nota: los enums y otros objetos sa.Enum se manejan automáticamente por sa.Enum(native_enum=True)
    # pero a veces hay que borrarlos explícitamente en Postgres si fallan.
