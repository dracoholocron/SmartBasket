"""pipeline_runs_status_to_enum

Convierte ``pipeline_runs.status`` de ``VARCHAR`` al ENUM ``pipelinestatus``.

Va después de ``64e3da622950`` (que añade los valores ``running`` y
``succeeded`` al ENUM) porque Postgres exige que los valores nuevos estén
committed antes de poder usarlos en un cast (``status::pipelinestatus``).
La separación funciona gracias a ``transaction_per_migration=True`` en
``env.py``.

Revision ID: 5d6e7f8a9b0c
Revises: 64e3da622950
Create Date: 2026-05-13 04:30:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers, used by Alembic.
revision: str = '5d6e7f8a9b0c'
down_revision: Union[str, None] = '64e3da622950'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'pipeline_runs',
        'status',
        existing_type=sa.VARCHAR(),
        type_=postgresql.ENUM(
            'pending', 'running', 'processing', 'ready', 'succeeded', 'failed',
            name='pipelinestatus',
            create_type=False,
        ),
        existing_nullable=False,
        postgresql_using='status::pipelinestatus',
    )


def downgrade() -> None:
    op.alter_column(
        'pipeline_runs',
        'status',
        existing_type=postgresql.ENUM(
            'pending', 'running', 'processing', 'ready', 'succeeded', 'failed',
            name='pipelinestatus',
            create_type=False,
        ),
        type_=sa.VARCHAR(),
        existing_nullable=False,
    )
