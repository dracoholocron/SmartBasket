# sports-data-api

Multi-tenant REST API sobre Postgres para la plataforma SmartBasket Phase 2.

Owner del schema de la base de eventos deportivos. El pipeline (`basketball-highlight-agent`), el reviewer UI y el scouting-engine son **clientes** de este servicio.

> Ver el doc de arquitectura completo en `../phase2_architecture.md`.

---

## Quick start (local)

```bash
cp .env.example .env
docker compose up --build
```

Esto levanta:

| Servicio | Puerto | Qué expone |
|---|---|---|
| `postgres` | 5432 | Postgres 16 + pgcrypto + pg_trgm |
| `api` | 8000 | FastAPI con `/health` y `/health/db` |

Verificar:

```bash
curl http://localhost:8000/health        # → {"status":"ok"}
curl http://localhost:8000/health/db     # → {"status":"ok","result":1}
```

---

## Estructura

```
sports-data-api/
├── pyproject.toml            # paquete + deps
├── Dockerfile                # imagen de runtime
├── docker-compose.yml        # postgres + api locales
├── alembic.ini               # config de migrations
├── migrations/               # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── src/sports_data_api/
│   ├── main.py               # FastAPI factory
│   ├── config.py             # settings (pydantic-settings)
│   └── db/
│       ├── base.py           # SQLAlchemy DeclarativeBase
│       └── session.py        # async engine + session
└── tests/
```

---

## Comandos útiles

```bash
# Aplicar migrations
docker compose exec api alembic upgrade head

# Crear nueva migration (manual)
docker compose exec api alembic revision -m "descripcion"

# Tests
docker compose exec api pytest -v

# Shell de Postgres
docker compose exec postgres psql -U sportsdata
```

---

## Estado actual

- **S0.1 (scaffolding) — listo:** `/health` + `/health/db` operativos.
- **S0.2 (initial schema) — pendiente:** migration 0001 con todas las tablas + RLS.
- **S0.3 (modelos + DTOs) — pendiente.**
- **S0.4 (endpoints CRUD + tests) — pendiente.**
- **S0.5 (bridge JSON → API) — pendiente.**
