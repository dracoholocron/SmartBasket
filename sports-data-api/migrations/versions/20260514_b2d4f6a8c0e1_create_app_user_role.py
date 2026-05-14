"""create_app_user_role

Crea el rol ``app_user`` (NOSUPERUSER, NOBYPASSRLS) que usa el runtime de la
API para conectarse a Postgres. Las migraciones siguen corriendo como el
superuser ``sportsdata``.

Motivación
----------
Las policies de RLS de S0.4-B no protegen nada si la app se conecta como
superuser: Postgres saltea RLS por completo para superusers y para roles
con BYPASSRLS, sin importar ``FORCE ROW LEVEL SECURITY``. La imagen oficial
de Postgres crea el ``POSTGRES_USER`` (``sportsdata``) como superuser, así
que hasta S0.4-B el aislamiento real venía sólo del filtro ``WHERE
tenant_id`` a nivel app (S0.4-A).

``app_user`` es un rol normal: no es superuser, no tiene BYPASSRLS y no es
dueño de las tablas. Por lo tanto SÍ está sujeto a las policies. El runtime
se conecta con este rol (``APP_DATABASE_URL``); Alembic sigue usando el
superuser (``DATABASE_URL``) porque necesita correr DDL.

Password
--------
El password es un valor de dev fijo. En prod se rota out-of-band con
``ALTER ROLE app_user PASSWORD '<secret>'`` y se inyecta ``APP_DATABASE_URL``
desde un secret manager.

Orden de arranque
-----------------
En una DB nueva, la app no puede conectarse hasta que esta migración haya
corrido (antes el rol no existe). Es el mismo requisito que ya existía con
las tablas: hay que migrar antes de usar el API.

Revision ID: b2d4f6a8c0e1
Revises: 9f3c1d7e2a48
Create Date: 2026-05-14 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e1'
down_revision: Union[str, None] = '9f3c1d7e2a48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APP_ROLE = "app_user"
# Password de dev. En prod: ALTER ROLE app_user PASSWORD '<secret>'.
_APP_PWD = "app_user_dev_pwd"


def upgrade() -> None:
    # CREATE ROLE no es idempotente — lo envolvemos en un guard para que la
    # migración se pueda re-aplicar sobre un cluster donde el rol ya existe.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE}'
            ) THEN
                CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PWD}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )

    # Privilegios sobre el schema y los objetos que ya existen.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}"
    )
    op.execute(
        f"GRANT USAGE, SELECT, UPDATE "
        f"ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}"
    )

    # Privilegios por defecto para tablas/secuencias que creen futuras
    # migraciones (que corren como el superuser actual).
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {_APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM {_APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {_APP_ROLE}")
