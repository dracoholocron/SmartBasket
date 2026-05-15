"""
mint_api_key.py — mintea un API key desde la CLI (S0.4-D).

Bootstrap: sirve para crear el PRIMER key de un tenant, cuando todavía no hay
ningún admin-key con el cual llamar a ``POST /v1/admin/api-keys``.

Uso (desde el contenedor de la API):
    docker compose exec api python scripts/mint_api_key.py \\
        --tenant-id 00000000-0000-0000-0000-000000000001 \\
        --name "pipeline-bridge" \\
        --role pipeline

El token completo se imprime UNA sola vez. Guardalo: no se puede recuperar.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sports_data_api.config import get_settings
from sports_data_api.db.models import APIKey, APIKeyRole, Tenant
from sports_data_api.security import generate_api_key


async def _mint(
    tenant_id: UUID, name: str, role: APIKeyRole, expires_at: datetime | None
) -> None:
    settings = get_settings()
    # Script de operador: usamos la URL superuser, que siempre existe (incluso
    # antes de que el rol app_user esté creado).
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            ).scalar_one_or_none()
            if tenant is None:
                print(f"ERROR: tenant {tenant_id} no existe", file=sys.stderr)
                sys.exit(1)

            full_key, key_prefix, key_hash = generate_api_key()
            db_key = APIKey(
                tenant_id=tenant_id,
                name=name,
                role=role,
                key_hash=key_hash,
                key_prefix=key_prefix,
                expires_at=expires_at,
            )
            session.add(db_key)
            await session.commit()
            await session.refresh(db_key)

        print("API key creado. Guardá el token — no se puede recuperar:\n")
        print(f"  api_key   : {full_key}")
        print(f"  id        : {db_key.id}")
        print(f"  tenant_id : {db_key.tenant_id}")
        print(f"  name      : {db_key.name}")
        print(f"  role      : {db_key.role.value}")
        print(f"  prefix    : {db_key.key_prefix}")
        print(f"  expires_at: {db_key.expires_at or 'never'}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mintea un API key para un tenant.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--name", required=True, help="Etiqueta legible del key.")
    parser.add_argument(
        "--role", required=True, choices=[r.value for r in APIKeyRole]
    )
    parser.add_argument(
        "--expires-at",
        default=None,
        help="ISO 8601, ej: 2027-01-01T00:00:00Z. Si se omite, no expira.",
    )
    args = parser.parse_args()

    expires_at: datetime | None = None
    if args.expires_at:
        expires_at = datetime.fromisoformat(args.expires_at.replace("Z", "+00:00"))

    asyncio.run(_mint(args.tenant_id, args.name, APIKeyRole(args.role), expires_at))


if __name__ == "__main__":
    main()
