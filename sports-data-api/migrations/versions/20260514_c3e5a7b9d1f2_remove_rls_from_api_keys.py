"""remove_rls_from_api_keys

Saca Row-Level Security de la tabla ``api_keys`` (S0.4-D).

Motivación
----------
La autenticación por API key (``Authorization: Bearer``) tiene que resolver
el ``tenant_id`` ANTES de que exista contexto de tenant — es justamente el
lookup del key lo que *establece* ese contexto. Si ``api_keys`` tuviera RLS,
el ``SELECT ... WHERE key_hash = ...`` correría con la GUC
``app.current_tenant_id`` sin setear, ``current_tenant_id()`` daría NULL y la
policy filtraría TODAS las filas: la autenticación nunca encontraría el key.

Por eso ``api_keys`` queda fuera de RLS. El lookup está protegido por la
unicidad e imposibilidad de invertir ``key_hash`` (SHA-256): sólo se puede
encontrar una fila si se conoce el key crudo. El scoping por tenant de los
endpoints de gestión (``/v1/admin/api-keys``) se hace a nivel app, con un
filtro ``WHERE tenant_id = ...`` explícito — el mismo patrón que ``tenants``,
que tampoco tiene RLS por ser una tabla de administración.

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-05-14 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f2'
down_revision: Union[str, None] = 'b2d4f6a8c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "api_keys"')
    op.execute('ALTER TABLE "api_keys" NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "api_keys" DISABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.execute('ALTER TABLE "api_keys" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "api_keys" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "api_keys" '
        'USING (tenant_id = current_tenant_id()) '
        'WITH CHECK (tenant_id = current_tenant_id())'
    )
