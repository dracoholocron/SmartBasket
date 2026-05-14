"""enable_row_level_security

Activa Row-Level Security (RLS) de Postgres en todas las tablas de negocio
con columna ``tenant_id`` (S0.4-B).

Motivación
----------
S0.4-A scopea por ``tenant_id`` en cada query a nivel aplicación. Eso es
correcto, pero es una sola capa: un bug en un router (un ``WHERE`` que se
olvida, un join mal escrito) deja escapar datos cross-tenant. RLS mueve la
garantía de aislamiento al motor de la base de datos — aunque el código de
la app tenga un bug, Postgres no devuelve filas de otro tenant.

Mecanismo
---------
* ``current_tenant_id()`` — función ``STABLE`` que lee la GUC de sesión
  ``app.current_tenant_id``. El segundo argumento ``true`` de
  ``current_setting`` hace que devuelva ``NULL`` (en vez de error) si la
  GUC no está seteada. ``NULL`` => ninguna fila matchea => *fail closed*.
* Por cada tabla: ``ENABLE`` + ``FORCE ROW LEVEL SECURITY``. El ``FORCE``
  es clave: sin él, el dueño de la tabla (que suele ser el rol con el que
  se conecta la app) se saltea las policies. Con ``FORCE``, la policy
  aplica también al owner.
* ``CREATE POLICY tenant_isolation`` — ``USING`` filtra lecturas/updates,
  ``WITH CHECK`` impide insertar/actualizar filas con un ``tenant_id``
  distinto al de la sesión.

La GUC se setea por request en ``get_tenant_db`` con
``SELECT set_config('app.current_tenant_id', <uuid>, true)`` (is_local =
true => equivale a ``SET LOCAL``, vive sólo dentro de la transacción).

Nota: ``tenants`` NO recibe RLS — es una tabla de administración que se
gestiona con endpoints admin-level (se gateará en S0.4-D). Las migraciones
no se ven afectadas por RLS porque RLS sólo aplica a DML, no a DDL.

Revision ID: 9f3c1d7e2a48
Revises: 7c9e2f1a3b4d
Create Date: 2026-05-14 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = '9f3c1d7e2a48'
down_revision: Union[str, None] = '7c9e2f1a3b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tablas de negocio con columna ``tenant_id``. ``tenants`` queda fuera.
_TENANT_TABLES: list[str] = [
    "seasons",
    "teams",
    "players",
    "player_team_memberships",
    "games",
    "pipeline_runs",
    "events",
    "event_tags",
    "clips",
    "scouting_reports",
    "api_keys",
]


def upgrade() -> None:
    # Helper que lee la GUC de sesión. STABLE: el valor no cambia dentro
    # de una misma query. Devuelve NULL si la GUC no está seteada.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        $$
        """
    )

    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f'USING (tenant_id = current_tenant_id()) '
            f'WITH CHECK (tenant_id = current_tenant_id())'
        )


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    op.execute("DROP FUNCTION IF EXISTS current_tenant_id()")
