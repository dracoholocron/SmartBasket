"""timestamps_to_timestamptz

Convierte todas las columnas TIMESTAMP WITHOUT TIME ZONE a TIMESTAMP WITH
TIME ZONE (``timestamptz``).

Motivación
----------
El bridge del pipeline manda timestamps en formato ISO 8601 con sufijo ``Z``
(``"2026-05-13T03:38:52Z"``), que Pydantic v2 parsea como ``datetime`` con
``tzinfo=UTC``. Las columnas estaban declaradas como naive
(``TIMESTAMP WITHOUT TIME ZONE``), así que asyncpg rechazaba la escritura con
``can't subtract offset-naive and offset-aware datetimes``.

Postgres ``timestamptz`` es lo correcto en producción multi-tenant: guarda
el instante absoluto en UTC y maneja la conversión a/desde la zona del
cliente automáticamente.

Asunción del cast
-----------------
Los datos existentes (si los hay) se guardaron como UTC, así que casteamos
con ``... AT TIME ZONE 'UTC'``. Si la DB está vacía o sólo tiene los rows
del smoke-test del bridge, esto es seguro.

Revision ID: 7c9e2f1a3b4d
Revises: 5d6e7f8a9b0c
Create Date: 2026-05-13 04:50:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = '7c9e2f1a3b4d'
down_revision: Union[str, None] = '5d6e7f8a9b0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, column_name) — todas las columnas datetime del esquema.
_TIMESTAMP_COLUMNS: list[tuple[str, str]] = [
    ("tenants", "created_at"),
    ("tenants", "updated_at"),
    ("seasons", "created_at"),
    ("teams", "created_at"),
    ("teams", "updated_at"),
    ("players", "created_at"),
    ("players", "updated_at"),
    ("games", "played_at"),
    ("games", "created_at"),
    ("games", "updated_at"),
    ("pipeline_runs", "started_at"),
    ("pipeline_runs", "finished_at"),
    ("events", "reviewed_at"),
    ("events", "created_at"),
    ("events", "updated_at"),
    ("event_tags", "tagged_at"),
    ("clips", "created_at"),
    ("scouting_reports", "generated_at"),
    ("api_keys", "last_used_at"),
    ("api_keys", "revoked_at"),
    ("api_keys", "created_at"),
    ("api_keys", "expires_at"),
]


def upgrade() -> None:
    for table, col in _TIMESTAMP_COLUMNS:
        op.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{col}" '
            f'TYPE TIMESTAMP WITH TIME ZONE '
            f'USING "{col}" AT TIME ZONE \'UTC\''
        )


def downgrade() -> None:
    # Revierte a TIMESTAMP WITHOUT TIME ZONE. El cast `AT TIME ZONE 'UTC'`
    # extrae el momento expresado en UTC (sin offset).
    for table, col in _TIMESTAMP_COLUMNS:
        op.execute(
            f'ALTER TABLE "{table}" '
            f'ALTER COLUMN "{col}" '
            f'TYPE TIMESTAMP WITHOUT TIME ZONE '
            f'USING "{col}" AT TIME ZONE \'UTC\''
        )
