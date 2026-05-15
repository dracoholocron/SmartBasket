"""
Tests de autenticación por API key (S0.4-D).

Cubren los helpers de crypto (``security.py``) y el resolvedor de keys
(``_auth.resolve_api_key``): un key válido autentica y actualiza
``last_used_at``; un key desconocido / revocado / expirado se rechaza con 401.

Usan la infra de testcontainers de ``conftest.py``. ``api_keys`` no tiene RLS
(migración ``c3e5a7b9d1f2``), así que ``app_user`` puede insertar y leer la
tabla sin setear la GUC de tenant.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from sports_data_api.api.v1._auth import resolve_api_key
from sports_data_api.db.models import APIKey, APIKeyRole
from sports_data_api.security import generate_api_key, hash_api_key
from tests.conftest import TENANT_A

# asyncio_mode = "auto" (pyproject.toml) ya detecta los tests async; no hace
# falta un pytestmark a nivel módulo — y aplicarlo rompía el test sincrónico.


def test_generate_api_key_roundtrip():
    """El key generado tiene el prefijo esperado y el hash es consistente."""
    full_key, key_prefix, key_hash = generate_api_key()
    assert full_key.startswith("sdk_")
    assert key_prefix == full_key[:12]
    assert key_hash == hash_api_key(full_key)
    assert len(key_hash) == 64  # SHA-256 hex

    # Dos llamadas nunca colisionan.
    other_key, _, other_hash = generate_api_key()
    assert other_key != full_key
    assert other_hash != key_hash


async def _insert_key(session, **overrides) -> tuple[str, APIKey]:
    """Inserta un APIKey de prueba y devuelve (token_crudo, fila)."""
    full_key, key_prefix, key_hash = generate_api_key()
    row = APIKey(
        tenant_id=overrides.get("tenant_id", uuid.UUID(TENANT_A)),
        name=overrides.get("name", "test-key"),
        role=overrides.get("role", APIKeyRole.pipeline),
        key_hash=key_hash,
        key_prefix=key_prefix,
        revoked_at=overrides.get("revoked_at"),
        expires_at=overrides.get("expires_at"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return full_key, row


async def test_valid_key_resolves(app_sessionmaker):
    """Un key válido resuelve a su fila y marca last_used_at."""
    async with app_sessionmaker() as s:
        full_key, row = await _insert_key(s)
        resolved = await resolve_api_key(full_key, s)
        assert resolved.id == row.id
        assert resolved.tenant_id == uuid.UUID(TENANT_A)
        assert resolved.role == APIKeyRole.pipeline
        assert resolved.last_used_at is not None
        await s.rollback()


async def test_unknown_key_rejected(app_sessionmaker):
    """Un token que no existe en la tabla -> 401."""
    async with app_sessionmaker() as s:
        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key("sdk_this_key_does_not_exist", s)
        assert exc_info.value.status_code == 401


async def test_revoked_key_rejected(app_sessionmaker):
    """Un key con revoked_at seteado -> 401."""
    async with app_sessionmaker() as s:
        full_key, _ = await _insert_key(s, revoked_at=datetime.now(timezone.utc))
        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key(full_key, s)
        assert exc_info.value.status_code == 401
        await s.rollback()


async def test_expired_key_rejected(app_sessionmaker):
    """Un key con expires_at en el pasado -> 401."""
    async with app_sessionmaker() as s:
        full_key, _ = await _insert_key(
            s, expires_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key(full_key, s)
        assert exc_info.value.status_code == 401
        await s.rollback()


async def test_future_expiry_key_still_valid(app_sessionmaker):
    """Un key con expires_at en el futuro sigue siendo válido."""
    async with app_sessionmaker() as s:
        full_key, row = await _insert_key(
            s, expires_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        resolved = await resolve_api_key(full_key, s)
        assert resolved.id == row.id
        await s.rollback()
