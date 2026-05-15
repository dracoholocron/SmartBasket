"""
Generación y hashing de API keys (S0.4-D).

Un API key se genera una vez, se le muestra al cliente en texto plano una
sola vez, y nunca más: la DB sólo guarda el hash y un prefijo para poder
identificarlo en listados.

Por qué SHA-256 y no bcrypt/argon2
----------------------------------
bcrypt/argon2 son hashes deliberadamente lentos, pensados para passwords
elegidos por humanos (baja entropía, vulnerables a fuerza bruta). Un API key
acá es un token aleatorio de 256 bits (``secrets.token_urlsafe(32)``): no hay
nada que adivinar por fuerza bruta, así que un hash rápido como SHA-256
alcanza y mantiene el lookup de autenticación barato.
"""
from __future__ import annotations

import hashlib
import secrets

# Prefijo legible del key — "sports-data-key". Ayuda a identificar de un
# vistazo qué es el token si aparece en un log o en el portapapeles.
_KEY_NAMESPACE = "sdk"

# Cuántos caracteres del key guardamos como ``key_prefix`` (sólo display).
_PREFIX_DISPLAY_LEN = 12


def generate_api_key() -> tuple[str, str, str]:
    """
    Genera un API key nuevo.

    Devuelve ``(full_key, key_prefix, key_hash)``:
      * ``full_key``   — el token completo. Se le muestra al cliente UNA vez.
      * ``key_prefix`` — primeros caracteres, para identificarlo en listados.
      * ``key_hash``   — SHA-256 hex, lo único que se persiste para auth.
    """
    token = secrets.token_urlsafe(32)
    full_key = f"{_KEY_NAMESPACE}_{token}"
    key_prefix = full_key[:_PREFIX_DISPLAY_LEN]
    return full_key, key_prefix, hash_api_key(full_key)


def hash_api_key(full_key: str) -> str:
    """SHA-256 hex del key crudo. Determinístico — sirve para el lookup."""
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()
