"""
Autenticación por API key (S0.4-D).

``Authorization: Bearer <api_key>`` es el mecanismo real de auth: el lookup
del key resuelve ``tenant_id`` + ``role``. El header ``X-Tenant-ID`` sigue
funcionando SÓLO como fallback de dev, y SÓLO si
``settings.allow_header_tenant_auth`` está en true — útil para el bridge del
pipeline y el smoke test mientras se migran a API keys.

El lookup se hace contra ``api_keys``, que NO tiene RLS (la quita la
migración ``c3e5a7b9d1f2``): la autenticación tiene que correr ANTES de que
exista contexto de tenant, así que no puede depender de la GUC
``app.current_tenant_id``. La unicidad e irreversibilidad de ``key_hash``
(SHA-256) es lo que protege el lookup.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.config import get_settings
from sports_data_api.db.models import APIKey, APIKeyRole
from sports_data_api.db.session import get_db
from sports_data_api.security import hash_api_key

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class AuthContext:
    """Identidad resuelta de quien hace la request."""

    tenant_id: UUID
    role: APIKeyRole
    # ``None`` cuando el contexto viene del fallback de dev X-Tenant-ID.
    api_key_id: UUID | None
    via_dev_header: bool = False


def _parse_bearer(authorization: str | None) -> str | None:
    """Extrae el token de un header ``Authorization: Bearer <token>``."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def resolve_api_key(token: str, db: AsyncSession) -> APIKey:
    """
    Resuelve un token crudo a su fila ``APIKey``: hashea, busca, valida que
    no esté revocado ni expirado, y actualiza ``last_used_at``.

    Lanza 401 si el key no existe / está revocado / expiró.
    """
    api_key = (
        await db.execute(
            select(APIKey).where(APIKey.key_hash == hash_api_key(token))
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid API key",
            headers=_UNAUTHORIZED_HEADERS,
        )
    if api_key.revoked_at is not None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "API key has been revoked",
            headers=_UNAUTHORIZED_HEADERS,
        )
    now = datetime.now(timezone.utc)
    if api_key.expires_at is not None and api_key.expires_at < now:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "API key has expired",
            headers=_UNAUTHORIZED_HEADERS,
        )
    api_key.last_used_at = now
    await db.flush()
    return api_key


async def get_auth_context(
    authorization: str | None = Header(default=None),
    x_tenant_id: UUID | None = Header(default=None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """
    Dependency de autenticación. Resuelve el ``AuthContext`` de la request.

    Precedencia:
      1. ``Authorization: Bearer <api_key>`` — el mecanismo real.
      2. ``X-Tenant-ID`` — fallback de dev, sólo si ``allow_header_tenant_auth``.
      3. Si no hay ninguno válido → 401.
    """
    token = _parse_bearer(authorization)
    if token is not None:
        api_key = await resolve_api_key(token, db)
        return AuthContext(
            tenant_id=api_key.tenant_id,
            role=api_key.role,
            api_key_id=api_key.id,
        )

    settings = get_settings()
    if settings.allow_header_tenant_auth and x_tenant_id is not None:
        # Fallback de dev: sin key real, asumimos rol admin (acceso total)
        # para no trabar el bridge ni el smoke test.
        return AuthContext(
            tenant_id=x_tenant_id,
            role=APIKeyRole.admin,
            api_key_id=None,
            via_dev_header=True,
        )

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Missing credentials: provide 'Authorization: Bearer <api_key>'",
        headers=_UNAUTHORIZED_HEADERS,
    )


def require_role(*allowed: APIKeyRole):
    """
    Factory de dependency: exige que el rol del caller esté en ``allowed``.

    Uso:
        @router.post("", dependencies=[Depends(require_role(APIKeyRole.admin))])
    """

    async def _dependency(
        auth: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if auth.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role: {', '.join(r.value for r in allowed)}",
            )
        return auth

    return _dependency


# =============================================================================
# Admin / root — gestión de tenants y API keys
# =============================================================================

@dataclass(frozen=True)
class AdminCaller:
    """
    Caller autorizado para operaciones de administración.

    ``is_root`` distingue las dos formas: el root token (cross-tenant, para
    bootstrap) y un admin-key (scopeado a su propio tenant).
    """

    is_root: bool
    # ``None`` cuando ``is_root`` — el root opera cross-tenant.
    tenant_id: UUID | None


async def require_admin_or_root(
    x_root_admin_token: str | None = Header(default=None, alias="X-Root-Admin-Token"),
    authorization: str | None = Header(default=None),
    x_tenant_id: UUID | None = Header(default=None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AdminCaller:
    """
    Autoriza al caller como root (token) o como admin-key. Cualquier otra
    cosa → 403 (o 401 si no mandó credenciales).
    """
    settings = get_settings()

    if x_root_admin_token is not None:
        if not secrets.compare_digest(
            x_root_admin_token, settings.api_root_admin_token
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid root admin token")
        return AdminCaller(is_root=True, tenant_id=None)

    # Sin root token: exigir un AuthContext con rol admin.
    auth = await get_auth_context(
        authorization=authorization, x_tenant_id=x_tenant_id, db=db
    )
    if auth.role != APIKeyRole.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Requires an admin-role API key or the root admin token",
        )
    return AdminCaller(is_root=False, tenant_id=auth.tenant_id)
