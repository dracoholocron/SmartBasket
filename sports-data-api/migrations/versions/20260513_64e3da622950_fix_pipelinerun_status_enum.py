"""add_running_succeeded_to_pipelinestatus

Amplía el ENUM ``pipelinestatus`` con dos valores nuevos: ``running`` y
``succeeded``. La migration ORIGINAL intentaba además convertir la columna
``pipeline_runs.status`` de VARCHAR a este ENUM en la misma transacción,
pero Postgres rechaza eso con::

    UnsafeNewEnumValueUsageError: New enum values must be committed before
    they can be used.

Por eso se separó en dos migrations: ésta sólo amplía el tipo (y commitea
gracias a ``transaction_per_migration=True`` en ``env.py``), y la siguiente
hace el ``ALTER COLUMN`` ya con los valores disponibles.

Revision ID: 64e3da622950
Revises: 1f62212e0cbb
Create Date: 2026-05-13 04:00:50.253879+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = '64e3da622950'
down_revision: Union[str, None] = '1f62212e0cbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE pipelinestatus ADD VALUE IF NOT EXISTS 'running' BEFORE 'processing'"
    )
    op.execute(
        "ALTER TYPE pipelinestatus ADD VALUE IF NOT EXISTS 'succeeded' BEFORE 'failed'"
    )


def downgrade() -> None:
    # Postgres no permite quitar valores de un ENUM existente; el downgrade
    # tendría que reconstruir el tipo completo. Como `running` y `succeeded`
    # no estorban a las apps anteriores, dejamos el downgrade como no-op.
    pass
