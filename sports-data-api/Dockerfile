# ─────────────────────────────────────────────────────────────────────────────
# sports-data-api — FastAPI + SQLAlchemy async + Alembic
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps por si asyncpg necesita compilar (wheels para slim ya existen en >=0.29)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ─── Instalación de dependencias (capa cacheable) ─────────────────────────
# pyproject.toml declara `readme = "README.md"` y `packages.find` sobre src/,
# así que tenemos que tener AMBOS presentes al momento de hacer `pip install -e`.
# Creamos un stub mínimo de src/ para que setuptools resuelva el package;
# después COPY src lo sobrescribe con el código real.
COPY pyproject.toml README.md /app/
RUN mkdir -p /app/src/sports_data_api && \
    touch /app/src/sports_data_api/__init__.py && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

# ─── Código real (capa que cambia frecuente, NO invalida pip install) ────
COPY src /app/src
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY tests /app/tests

ENV PYTHONPATH=/app/src

EXPOSE 8000

# Por defecto: API. Se sobrescribe en docker-compose para dev (--reload)
CMD ["uvicorn", "sports_data_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
