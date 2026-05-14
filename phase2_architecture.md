# SmartBasket Phase 2 — Architecture Document

**Status:** Draft v1
**Last updated:** 2026-05-12
**Author:** Diego + Claude
**Scope:** Phase 2A foundation + 2B player intelligence, with extension points for 2C/2D

---

## 0. Executive Summary

Phase 2 transforma SmartBasket de un **generador de clips local** a una **plataforma de inteligencia deportiva** con datos estructurados, consultables y enriquecibles por humanos. La pieza central es una base de eventos relacional (Postgres) accesible por API, que alimenta tanto el pipeline existente como nuevos servicios (scouting, recruiting, dashboards).

**Decisiones clave ya tomadas:**

| Decisión | Elección |
|---|---|
| Base de datos | Postgres 16 |
| Topología | Microservicios independientes (no monorepo) |
| Tagging de jugadores | Humano (semi-asistido), no automático en MVP |
| Caso de uso prioritario | (1) Scouting reports → (2) Recruiting reels → (3) Dashboards |
| **Multi-tenancy** | **Sí, desde el día 1. `tenant_id` en cada tabla de negocio + RLS en Postgres.** |

**El "norte verdadero" del Phase 2A es:** un coach o scout puede subir un video de un partido, taguear jugadores en una UI, y obtener un reporte de scouting auto-generado de un jugador específico.

---

## 1. Goals & Non-Goals

### 1.1 Goals (Phase 2A + 2B)

1. Persistir cada evento detectado como una fila estructurada (no JSON suelto).
2. Identificar jugadores por etiqueta humana (no auto-OCR en MVP).
3. Exponer la data por API REST estable.
4. Generar reportes de scouting LLM-based a partir de eventos agregados por jugador.
5. Mantener el pipeline existente como **un productor más** de la nueva API.
6. Trazabilidad: cada evento sabe de qué pipeline_run vino y qué humano lo revisó.

### 1.2 Non-Goals (explícitamente fuera de scope en este doc)

- Tracking 3D / biomecánica.
- Auto-OCR de números de camiseta (se posterga a Stage 2 de Phase 2B).
- Live streaming / overlays en vivo (Phase 2D).
- Federación de datos entre clubes externos.
- Predictive analytics (Expected FG%, Shot Quality model).

---

## 2. System Overview

### 2.1 Componentes

| Servicio | Estado | Responsabilidad | Repo |
|---|---|---|---|
| **basketball-highlight-agent** | EXISTE | Pipeline video → candidatos → clips. Refactor para escribir vía API en vez de JSON. | `basketball-highlight-agent/` (mismo monorepo de Phase 1) |
| **sports-data-api** | NUEVO | API REST sobre Postgres. Dueño del schema. CRUD games/events/players/teams/clips. | repo separado: `sports-data-api` |
| **reviewer-ui** | EXISTE (Streamlit) | UI de tagging humano. Consume sports-data-api. | sigue donde está, se desacopla de la DB directa |
| **scouting-engine** | NUEVO | Toma eventos por jugador y genera reportes con Claude API. Cola async. | repo separado: `scouting-engine` |
| **media-server** | EXISTE (nginx) | Sirve clips estáticos. | sin cambios |
| **postgres** | NUEVO | Base relacional única. | infra |
| **object-storage** | NUEVO | S3-compatible (MinIO en dev). Clips y reels viven acá, no en filesystem. | infra |

### 2.2 Diagrama de alto nivel

```
                 ┌──────────────────┐
                 │   reviewer-ui    │
                 │   (Streamlit)    │
                 └────────┬─────────┘
                          │ HTTP
                          ▼
┌──────────────────────────────────────────┐
│           sports-data-api                │
│           (FastAPI + Postgres)           │
│                                          │
│  /games  /events  /players  /clips  /…   │
└─────▲──────────────▲──────────────▲──────┘
      │              │              │
      │ writes       │ reads        │ reads
      │ events       │ events       │ events
      │              │              │
┌─────┴────────┐  ┌──┴───────────┐ ┌┴────────────────┐
│ basketball-  │  │  scouting-   │ │  dashboards     │
│ highlight-   │  │  engine      │ │  (future)       │
│ agent        │  │  (Claude)    │ │                 │
└──────┬───────┘  └──────────────┘ └─────────────────┘
       │
       │ reads/writes
       ▼
┌─────────────────────────┐
│   object-storage (S3)   │  ← videos input, clips, thumbnails
└─────────────────────────┘
```

### 2.3 ¿Por qué microservicios separados?

- **Versionado independiente**: el pipeline cambia con frecuencia (modelos, configs). La API debe ser estable para clientes externos.
- **Escalado distinto**: pipeline necesita GPU; API necesita CPU + I/O; scouting-engine necesita ancho de banda para LLM.
- **Schema ownership claro**: sólo `sports-data-api` aplica migrations. Los demás servicios son clientes.

---

## 3. Data Model

### 3.1 Postgres schema (DDL inicial)

```sql
-- =============================================================================
-- EXTENSIONS
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy search en nombres
-- pgvector se agrega en Stage 2 (embeddings de clips)

-- =============================================================================
-- TENANTS — multi-tenant root
-- =============================================================================
CREATE TABLE tenants (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          TEXT NOT NULL UNIQUE,           -- "club-rojo", "academia-norte"
  display_name  TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','suspended','archived')),
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE tenants IS
  'Cada cliente (club, academia, federación) es un tenant. Todas las tablas '
  'de negocio llevan tenant_id y se filtran vía RLS por la sesión actual.';

-- Sesión: el API setea esto al inicio de cada request, usando la API key.
-- Las policies de RLS leen este valor para filtrar.
-- Se hace en cada request, NO se persiste a nivel de rol DB.
-- Ejemplo: SELECT set_config('app.current_tenant_id', '<uuid>', true);

-- =============================================================================
-- ENUMS
-- =============================================================================
CREATE TYPE event_type AS ENUM (
  'shot_attempt',
  'made_shot',
  'missed_shot',
  'three_pointer_attempt',
  'three_pointer_made',
  'rebound_offensive',
  'rebound_defensive',
  'assist',
  'block',
  'steal',
  'turnover',
  'foul',
  'fast_break',
  'screen',
  'celebration',
  'unknown'
);

CREATE TYPE review_status AS ENUM (
  'unreviewed', 'confirmed', 'corrected', 'rejected'
);

CREATE TYPE pipeline_status AS ENUM (
  'pending', 'processing', 'ready', 'failed'
);

-- =============================================================================
-- DOMAIN ENTITIES
-- =============================================================================
CREATE TABLE seasons (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  name         TEXT NOT NULL,               -- "2025-26"
  start_date   DATE NOT NULL,
  end_date     DATE NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, name)
);
CREATE INDEX idx_seasons_tenant ON seasons (tenant_id);

CREATE TABLE teams (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  external_id  TEXT,                        -- id en federación/liga si hay
  name         TEXT NOT NULL,
  level        TEXT,                        -- U14|U16|U18|varsity|collegiate
  city         TEXT,
  country      TEXT,
  metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, external_id)
);
CREATE INDEX idx_teams_tenant ON teams (tenant_id);
CREATE INDEX idx_teams_name_trgm ON teams USING GIN (name gin_trgm_ops);

CREATE TABLE players (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  external_id     TEXT,
  first_name      TEXT NOT NULL,
  last_name       TEXT NOT NULL,
  date_of_birth   DATE,
  height_cm       INTEGER,
  position        TEXT,                     -- PG|SG|SF|PF|C
  dominant_hand   TEXT CHECK (dominant_hand IN ('L','R','B')),
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, external_id)
);
CREATE INDEX idx_players_tenant ON players (tenant_id);
CREATE INDEX idx_players_name_trgm
  ON players USING GIN ((first_name || ' ' || last_name) gin_trgm_ops);

CREATE TABLE player_team_memberships (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  player_id       UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  team_id         UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  season_id       UUID REFERENCES seasons(id),
  jersey_number   INTEGER,
  start_date      DATE NOT NULL,
  end_date        DATE,
  UNIQUE (tenant_id, team_id, season_id, jersey_number),
  CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX idx_ptm_tenant ON player_team_memberships (tenant_id);
CREATE INDEX idx_ptm_player ON player_team_memberships (player_id);
CREATE INDEX idx_ptm_team_season ON player_team_memberships (team_id, season_id);

-- =============================================================================
-- GAMES & PIPELINE
-- =============================================================================
CREATE TABLE games (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  external_id              TEXT,
  season_id                UUID REFERENCES seasons(id),
  home_team_id             UUID NOT NULL REFERENCES teams(id),
  away_team_id             UUID NOT NULL REFERENCES teams(id),
  played_at                TIMESTAMPTZ NOT NULL,
  venue                    TEXT,
  final_score_home         INTEGER,
  final_score_away         INTEGER,
  -- video / pipeline
  video_uri                TEXT NOT NULL,            -- s3://bucket/<tenant>/games/<id>/source.mp4
  video_duration_seconds   REAL NOT NULL,
  video_width              INTEGER,
  video_height             INTEGER,
  pipeline_status          pipeline_status NOT NULL DEFAULT 'pending',
  last_pipeline_run_id     UUID,                     -- FK añadida abajo
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (home_team_id <> away_team_id),
  UNIQUE (tenant_id, external_id)
);
CREATE INDEX idx_games_tenant_played ON games (tenant_id, played_at DESC);
CREATE INDEX idx_games_status
  ON games (tenant_id, pipeline_status)
  WHERE pipeline_status <> 'ready';

CREATE TABLE pipeline_runs (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  game_id            UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at        TIMESTAMPTZ,
  pipeline_version   TEXT NOT NULL,                  -- git sha o tag
  config_snapshot    JSONB NOT NULL,                 -- YAMLs efectivos serializados
  status             TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
  error              TEXT,
  metrics            JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_pipeline_runs_game ON pipeline_runs (game_id, started_at DESC);
CREATE INDEX idx_pipeline_runs_tenant ON pipeline_runs (tenant_id);

ALTER TABLE games
  ADD CONSTRAINT fk_games_last_run
  FOREIGN KEY (last_pipeline_run_id) REFERENCES pipeline_runs(id);

-- =============================================================================
-- EVENTS — la entidad central
-- =============================================================================
CREATE TABLE events (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  game_id             UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  pipeline_run_id     UUID REFERENCES pipeline_runs(id),

  -- temporal
  start_time_seconds  REAL NOT NULL,
  end_time_seconds    REAL NOT NULL,
  quarter             SMALLINT CHECK (quarter BETWEEN 1 AND 8),  -- ≥5 = OT
  game_clock_seconds  REAL,

  -- spatial (court 0-1, ya normalizado)
  court_x             REAL CHECK (court_x BETWEEN 0 AND 1),
  court_y             REAL CHECK (court_y BETWEEN 0 AND 1),

  -- semantic
  event_type          event_type NOT NULL DEFAULT 'unknown',
  player_id           UUID REFERENCES players(id),
  team_id             UUID REFERENCES teams(id),
  assist_player_id    UUID REFERENCES players(id),

  -- scoring
  raw_score           REAL NOT NULL,
  confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  signals             JSONB NOT NULL DEFAULT '{}'::jsonb,
  reasons             TEXT[] NOT NULL DEFAULT '{}',
  vlm_metadata        JSONB,                          -- play_type, description, etc

  -- review
  review_status       review_status NOT NULL DEFAULT 'unreviewed',
  reviewed_by         TEXT,
  reviewed_at         TIMESTAMPTZ,
  review_notes        TEXT,

  -- referencia al clip
  clip_id             UUID,                           -- FK añadida abajo

  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CHECK (end_time_seconds > start_time_seconds)
);
CREATE INDEX idx_events_tenant ON events (tenant_id);
CREATE INDEX idx_events_game ON events (game_id, start_time_seconds);
CREATE INDEX idx_events_player_type
  ON events (player_id, event_type)
  WHERE player_id IS NOT NULL;
CREATE INDEX idx_events_unreviewed
  ON events (tenant_id, game_id)
  WHERE review_status = 'unreviewed';
CREATE INDEX idx_events_signals ON events USING GIN (signals);

CREATE TABLE event_tags (        -- audit trail de cambios de review
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  event_id    UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  tagger      TEXT NOT NULL,
  tagged_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  before      JSONB,
  after       JSONB,
  notes       TEXT
);
CREATE INDEX idx_event_tags_event ON event_tags (event_id, tagged_at);
CREATE INDEX idx_event_tags_tenant ON event_tags (tenant_id);

-- =============================================================================
-- CLIPS
-- =============================================================================
CREATE TABLE clips (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  event_id           UUID REFERENCES events(id) ON DELETE SET NULL,
  game_id            UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  storage_uri        TEXT NOT NULL,                  -- s3://bucket/<tenant>/clips/...
  duration_seconds   REAL NOT NULL,
  width              INTEGER,
  height             INTEGER,
  fps                REAL,
  format             TEXT,
  size_bytes         BIGINT,
  thumbnail_uri      TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_clips_tenant ON clips (tenant_id);
CREATE INDEX idx_clips_game ON clips (game_id);
CREATE INDEX idx_clips_event ON clips (event_id);

ALTER TABLE events
  ADD CONSTRAINT fk_events_clip
  FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE SET NULL;

-- =============================================================================
-- SCOUTING REPORTS
-- =============================================================================
CREATE TABLE scouting_reports (
  id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                  UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  player_id                  UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  season_id                  UUID REFERENCES seasons(id),
  game_filter_ids            UUID[] NOT NULL DEFAULT '{}',
  audience                   TEXT NOT NULL CHECK (audience IN ('coach','scout','recruit','parent')),
  -- contenido
  report_md                  TEXT NOT NULL,
  report_json                JSONB NOT NULL,         -- strengths/weaknesses/highlights estructurados
  -- provenance
  generated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  model_version              TEXT NOT NULL,           -- "claude-sonnet-4-6"
  prompt_template_version    TEXT NOT NULL,           -- "scout_v1.2"
  source_event_ids           UUID[] NOT NULL,
  source_event_count         INTEGER NOT NULL,
  -- ciclo de vida
  status                     TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','published','archived'))
);
CREATE INDEX idx_reports_player_recent
  ON scouting_reports (player_id, generated_at DESC);
CREATE INDEX idx_reports_tenant ON scouting_reports (tenant_id);

-- =============================================================================
-- API KEYS — scope por tenant
-- =============================================================================
CREATE TABLE api_keys (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,                  -- "pipeline-prod", "reviewer-ui"
  key_hash        TEXT NOT NULL UNIQUE,            -- bcrypt/argon2 del secret real
  key_prefix      TEXT NOT NULL,                   -- primeros 8 chars para UI
  role            TEXT NOT NULL CHECK (role IN ('pipeline','reviewer','readonly','admin')),
  last_used_at    TIMESTAMPTZ,
  revoked_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ
);
CREATE INDEX idx_api_keys_tenant ON api_keys (tenant_id) WHERE revoked_at IS NULL;

-- =============================================================================
-- ROW-LEVEL SECURITY — defense in depth
-- =============================================================================
-- Activar RLS sobre cada tabla de negocio. La API setea
-- `app.current_tenant_id` al inicio de cada request, y las policies
-- usan ese valor para filtrar/restringir.
--
-- IMPORTANTE: el rol DB que usa la API NO debe ser superuser (BYPASSRLS).

ALTER TABLE seasons                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE players                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_team_memberships   ENABLE ROW LEVEL SECURITY;
ALTER TABLE games                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs             ENABLE ROW LEVEL SECURITY;
ALTER TABLE events                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_tags                ENABLE ROW LEVEL SECURITY;
ALTER TABLE clips                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE scouting_reports          ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys                  ENABLE ROW LEVEL SECURITY;

-- Helper para crear policy estándar (mismo patrón para todas las tablas)
-- USANDO función para no repetir 22 policies copy-paste.
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
$$;

-- Patrón por tabla (ejemplo events; análogo para las demás):
CREATE POLICY tenant_isolation ON events
  USING (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- (Las policies para el resto de tablas siguen el mismo patrón
-- y se generan en la migration con un bucle.)
```

### 3.2 Decisiones de modelado y por qué

- **UUIDs en todas las PKs**: facilita generación distribuida (el pipeline puede crear ids antes de hablar con la DB) y evita filtrado por ranges secuenciales.
- **`tenant_id` en cada tabla de negocio + RLS**: defensa en profundidad. Aunque la API filtre por `tenant_id`, una query con bug no puede cruzar tenants porque Postgres lo bloquea.
- **`signals JSONB` se mantiene**: el pipeline cambia de señales con frecuencia; no quiero migration cada vez. Las que se promueven a columna lo hacen cuando estabilizan.
- **`event_type` como enum**: validación a nivel DB, pero hay valor `unknown` para soportar candidatos pre-VLM.
- **`event_tags` audit table**: para entender cómo aprendió un revisor (entrenamiento futuro de modelos).
- **Court coords normalizadas (0-1)**: el video puede cambiar de cámara entre partidos; coordenadas en cancha son comparables.
- **`scouting_reports.source_event_ids`**: trazabilidad. Si un evento se corrige después, sé qué reportes podrían quedar obsoletos.
- **Unique constraints con `tenant_id`**: `(tenant_id, external_id)` en vez de solo `external_id`. Permite que dos tenants tengan el mismo external_id sin colisionar.
- **`ON DELETE RESTRICT` en FKs hacia `tenants`**: prevenir borrado accidental que cascadee a miles de filas. El borrado de tenant debe ser un proceso explícito.

### 3.3 Migrations

- **Tool**: Alembic 1.13+.
- **Política**: una migration por PR. Nunca editar una migration ya mergeada.
- **Down-migration obligatoria** para todas hasta producción.
- **Naming**: `YYYYMMDD_NNNN_descripcion.py`.

---

## 4. Microservice Boundaries

### 4.1 `sports-data-api` (NUEVO)

**Owner**: schema de la DB. Único servicio que aplica migrations.

**Responsabilidades:**
- CRUD de entidades del modelo.
- Validación con Pydantic.
- Autenticación (API keys para servicios, OAuth/JWT para humanos).
- Rate limiting básico.
- Idempotencia en escrituras críticas (pipeline_run results).

**No es responsable de:**
- Procesamiento de video (es solo storage de resultados).
- Generación de reportes (delega en scouting-engine).
- Servir bytes de video/clips (eso lo hace nginx/CDN).

**Stack:**

| Capa | Elección |
|---|---|
| Framework | FastAPI 0.110+ |
| ORM | SQLAlchemy 2.0 (async) |
| Driver | asyncpg |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Testing | pytest-asyncio + httpx |
| Container | Python 3.11-slim |

### 4.2 `basketball-highlight-agent` (EXISTE, refactor)

**Cambios mínimos para Phase 2A:**
1. Agregar `--api-base-url` y `--api-key` como flags al CLI.
2. Nuevo módulo `api_client.py` con métodos `create_pipeline_run`, `post_events`, `upload_clip`.
3. Modo dual durante transición: `--output-mode {json,api,both}`. Default `both`.
4. Mantener el output JSON local — útil para debugging y trabajo offline.

### 4.3 `reviewer-ui` (EXISTE, extender)

**Cambios:**
- Quitar acceso directo a `data/candidates/*.json`.
- Cliente HTTP al `sports-data-api`.
- Nueva pantalla "Player tagging": para cada evento sin `player_id`, dropdown filtrable de jugadores del equipo en ese partido (memberships activas en `played_at`).
- Atajos de teclado: `1-9` tagear con jersey, `R` rechazar, `Enter` confirmar.

### 4.4 `scouting-engine` (NUEVO)

**Responsabilidad:** dado un `player_id` y filtros, generar reporte LLM-based.

**Flujo interno:**
1. GET `/players/:id/events?status=confirmed&season_id=...` del `sports-data-api`.
2. Agrupa por `event_type`, agrega métricas básicas (FG%, distribución por zona).
3. Selecciona clips representativos (top-N por confidence × score, balanceados por tipo).
4. Construye prompt con: stats agregadas + descripciones VLM de los clips clave.
5. Llama a Claude API.
6. Parsea respuesta a `report_md` + `report_json` estructurado.
7. POSTea `scouting_reports` al API.

**Stack:**

| Capa | Elección |
|---|---|
| Framework | FastAPI (consistencia con sports-data-api) |
| Cola async | Redis + RQ (simple) o Celery si crece |
| LLM | Claude API vía SDK oficial (`anthropic`) |
| Templates | Jinja2 versionado por carpeta `prompts/scout_v1/` |

---

## 5. API Contracts

### 5.1 `sports-data-api` — endpoints principales

> Convención: REST + JSON. Paths kebab-case. Status codes estándar. Errores en formato RFC 7807 (Problem Details).

#### Games

```
GET    /games?season_id=&team_id=&status=&from=&to=&limit=&offset=
POST   /games
GET    /games/{game_id}
PATCH  /games/{game_id}
DELETE /games/{game_id}
POST   /games/{game_id}/pipeline-runs           # dispara el pipeline (async)
GET    /games/{game_id}/events
GET    /games/{game_id}/clips
GET    /games/{game_id}/review-progress         # % de eventos revisados
```

**Ejemplo `POST /games`**:

```json
{
  "external_id": "club_x_2026_05_11",
  "season_id": "...",
  "home_team_id": "...",
  "away_team_id": "...",
  "played_at": "2026-05-11T19:00:00-05:00",
  "venue": "Polideportivo Norte",
  "video_uri": "s3://smartbasket/games/raw/20260511_151008.mp4",
  "video_duration_seconds": 2880.5,
  "video_width": 1920,
  "video_height": 1080
}
```

#### Events

```
GET    /events?game_id=&player_id=&type=&review_status=&limit=&offset=
GET    /events/{event_id}
PATCH  /events/{event_id}                       # update review
POST   /events/bulk                             # writes desde pipeline
POST   /events/bulk-review                      # bulk tagging desde UI
```

**Ejemplo `PATCH /events/{id}`** (tagging humano):

```json
{
  "event_type": "three_pointer_made",
  "player_id": "...",
  "assist_player_id": null,
  "review_status": "corrected",
  "review_notes": "estaba clasificado como shot_attempt",
  "tagger": "diferalh"
}
```

#### Players / Teams / Seasons

```
GET    /players?team_id=&q=&season_id=
POST   /players
GET    /players/{player_id}
PATCH  /players/{player_id}
GET    /players/{player_id}/events
GET    /players/{player_id}/clips
GET    /players/{player_id}/scouting-reports
GET    /players/{player_id}/stats?season_id=&game_id=

# análogo para /teams y /seasons
```

#### Clips

```
POST   /clips                                   # registra clip ya subido al storage
GET    /clips/{clip_id}                         # devuelve metadata + URL pre-firmada
```

### 5.2 `scouting-engine` — endpoints

```
POST   /reports/generate
       body: {
         "player_id": "...",
         "season_id": "...",          // opcional
         "game_ids": ["..."],          // opcional, default = todos
         "audience": "coach",
         "max_clips_referenced": 8
       }
       → 202 Accepted + { "job_id": "...", "status_url": "/reports/jobs/{job_id}" }

GET    /reports/jobs/{job_id}
       → { "status": "running"|"succeeded"|"failed", "report_id": "...", "error": "..." }
```

### 5.3 Autenticación y tenant scoping

- **API keys con tenant scope**: cada key pertenece a un tenant. Header `X-API-Key`. El middleware:
  1. Resuelve la key (hash lookup en `api_keys`).
  2. Carga `tenant_id` + `role`.
  3. Ejecuta `SELECT set_config('app.current_tenant_id', '<uuid>', true)` al inicio de la transacción.
  4. A partir de ahí RLS filtra automáticamente.
- **Roles** (`api_keys.role`):
  - `pipeline`: write events/clips, read-mostly del resto.
  - `reviewer`: read events, write review/tags.
  - `readonly`: solo GET.
  - `admin`: full CRUD dentro del tenant.
- **Humanos**: Phase 2A → un login simple por env var en la UI mapeado a una key de role `reviewer`. Phase 2B → integrar Auth0/Clerk con tenant claim.
- **Rate limit**: 100 req/min por API key. Suficiente para revisor humano.
- **Provisionado de tenants**: hay un único endpoint admin (out-of-band, fuera del API normal) que crea tenants y emite su primera API key admin. Ese endpoint requiere credencial de root (env var del servidor), no API key.

---

## 6. Data Flow — Use Case Prioritario (Scouting Report)

```
1. Coach sube video    ─────────► reviewer-ui (form de upload)
                                     │ POST /games (con video_uri pre-uploaded a S3)
                                     ▼
2. Game created        ─────────► sports-data-api → Postgres
                                     │ POST /games/:id/pipeline-runs
                                     ▼
3. Pipeline triggered  ─────────► basketball-highlight-agent
                                     │ procesa video local (GPU)
                                     │ POST /events/bulk (con review_status='unreviewed')
                                     │ POST /clips (uno por evento)
                                     │ PATCH /games/:id (pipeline_status='ready')
                                     ▼
4. Coach taguea        ─────────► reviewer-ui
                                     │ GET /games/:id/events?review_status=unreviewed
                                     │ por cada evento:
                                     │   PATCH /events/:id  (player_id + corrections)
                                     ▼
5. Listo para reporte  ─────────► coach hace click "Generar reporte" para Jugador X
                                     │ POST /reports/generate { player_id: X, audience: 'coach' }
                                     ▼
6. Scouting engine     ─────────► scouting-engine
                                     │ GET /players/X/events?status=confirmed
                                     │ + agrega métricas + selecciona clips clave
                                     │ + llama Claude API
                                     │ POST /scouting_reports
                                     ▼
7. Coach lee reporte   ─────────► reviewer-ui muestra report_md + clips embebidos
```

**Latencias objetivo:**

| Paso | Target |
|---|---|
| 1-3 (upload + pipeline) | ≤ 1.5× duración del video |
| 4 (tagging humano) | ~30 min para 1 partido de 40 min con ~50 candidatos |
| 5-7 (reporte) | < 60 segundos |

---

## 7. Human Tagging Workflow

### 7.1 Estados del evento

```
       crea pipeline
          │
          ▼
    ┌──────────┐    revisor confirma    ┌──────────┐
    │unreviewed│ ─────────────────────► │ confirmed│
    └──────────┘                        └──────────┘
       │  │
       │  └─ revisor corrige tipo    ┌──────────┐
       │     o tagea jugador     ──► │ corrected│
       │                              └──────────┘
       │
       └──── revisor rechaza         ┌──────────┐
              (no es highlight)  ──► │ rejected │
                                     └──────────┘
```

### 7.2 UX target

Por cada evento sin tagear, el revisor ve:
- Clip embebido (autoplay loop).
- Sugerencia del VLM: `play_type` + `confidence`.
- Dropdown filtrable con jugadores del **roster activo en ese partido** (filtrado por `played_at` y `player_team_memberships`).
- Botones: ✅ Confirmar (Enter), ✏️ Corregir, ❌ Rechazar (Delete).
- Atajos: `1-9` para tagear por número de camiseta (resuelve a player_id vía memberships).

### 7.3 Reglas para evitar burnout

- Mostrar progreso del partido (X/Y eventos revisados).
- Permitir "saltear" un evento sin tagear (queda `unreviewed`).
- Queue priorizada: ordenar por `raw_score` descendente para que los más probables vengan primero.
- Auto-save: cada acción persiste en backend al instante.

---

## 8. Tech Stack Decisions

| Componente | Elección | Por qué |
|---|---|---|
| DB | Postgres 16 | Tu decisión. JSONB + arrays + enums + foreign keys + pg_trgm = stack maduro. |
| API framework | FastAPI | Pydantic nativo, async, OpenAPI auto, el equipo ya usa Python/Pydantic. |
| ORM | SQLAlchemy 2.0 async | Maduro, soporta async, alembic integrado. |
| Migrations | Alembic | Estándar de facto con SQLAlchemy. |
| Object storage | MinIO (dev) / S3 (prod) | API S3 compatible en ambos. |
| Queue | Redis + RQ | Simple, ya está en muchas arquitecturas. Celery si crece. |
| LLM | Claude API (Sonnet 4.6) | Calidad alta, structured outputs, ya alineado con el ecosistema. |
| Container orch | docker-compose (dev) → k8s (prod) | Iterativo. |
| Observability | structured logs (loguru) + OpenTelemetry + Prometheus | Stack abierto, sin vendor lock. |
| Auth | API keys (s2s) + Auth0/Clerk (humanos, Phase 2B) | API keys simples al inicio. |
| Testing | pytest + httpx + testcontainers-postgres | Tests reales sobre Postgres, no SQLite mock. |

---

## 9. Deployment & Observability

### 9.1 Topología de despliegue (dev)

```
docker-compose.yml (en cada repo de microservicio)

postgres:5432           ─┐
minio:9000              ─┤  ← shared infra (un docker-compose central)
redis:6379              ─┘
sports-data-api:8000    ← container propio
scouting-engine:8001    ← container propio
basketball-pipeline     ← GPU host, no en compose
reviewer-ui:8501        ← se conecta al api
```

### 9.2 Producción (objetivo Phase 2B)

- Postgres managed (RDS / Cloud SQL).
- S3 / R2 para object storage.
- API + scouting-engine en Kubernetes (deployment + HPA por CPU).
- Pipeline en VM con GPU dedicada (no es un buen fit para k8s sin GPU operator).
- Cert manager + ingress para HTTPS.

### 9.3 Observabilidad

- **Logs**: JSON structured con loguru, ingestados en Loki/Cloudwatch.
- **Metrics**: Prometheus scrape sobre `/metrics` (cada microservicio expone).
- **Traces**: OpenTelemetry, exportador a Jaeger en dev / a vendor en prod.
- **Métricas clave**:
  - `pipeline_run_duration_seconds` (histograma por status)
  - `events_unreviewed_total` (gauge por game)
  - `scouting_report_generation_seconds`
  - `api_request_duration_seconds`

### 9.4 Backups & migraciones

- Postgres: snapshots diarios + WAL streaming.
- Object storage: versioning habilitado.
- Migrations: aplicadas vía pipeline CI/CD, nunca a mano en prod.

---

## 10. Stage 0 — Hand-off para empezar

**Lo que ya queda fijado por este doc y arrancamos en Stage 0:**

1. Repo nuevo `sports-data-api` (Python, FastAPI, SQLAlchemy, Alembic).
2. Schema inicial (sección 3.1) como migration `0001_initial_schema.py`.
3. Pydantic models 1:1 con tablas + DTOs separados (Create/Update/Read).
4. Endpoints CRUD básicos de `seasons`, `teams`, `players`, `games`.
5. Tests con `testcontainers-postgres`.
6. Docker-compose con `postgres + sports-data-api` levantando juntos.
7. Bridge script: lee `data/candidates/*.json` de Phase 1 → POSTea al API.

**Lo que NO hace Stage 0:**
- Endpoints de events / clips (Stage 1).
- Auth real (Stage 1).
- Refactor del pipeline existente para escribir vía API (Stage 1).
- Scouting engine (Stage 1+).

---

## 11. Open Questions

Cosas que dejé sin resolver porque dependen de info que no tengo aún:

1. ~~**Multi-tenancy.**~~ **RESUELTO (2026-05-12):** multi-tenant con `tenant_id` en cada tabla de negocio + Row-Level Security en Postgres. Ver §3.1 y §5.3.
2. **Identidad del revisor.** ¿Es siempre vos en MVP o ya hay otros revisores? Eso define si `tagger` es un string libre o FK a `users`.
3. **Almacenamiento de videos source.** ¿Se mantienen post-procesamiento o se borran tras N días?
4. **Privacy / consent.** Video juvenil. ¿Hay un proceso de consentimiento de los padres que deba estar reflejado en `players`?
5. **Versionado del schema de eventos.** Si cambia `event_type` enum (añadir/quitar valores), ¿migrar histórico o mantener compat?
6. **Hosting del pipeline.** El pipeline corre en tu máquina con GPU. ¿Plan B cuando haya más partidos que tu GPU puede procesar?

Estas las podemos cerrar antes de empezar Stage 0 o ir resolviendo en el camino — pero la #1 (multi-tenancy) **debería decidirse antes de la primera migration**.

---

## Apéndice A — Estructura propuesta del repo `sports-data-api`

```
sports-data-api/
├── pyproject.toml
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── README.md
├── src/
│   └── sports_data_api/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app factory
│       ├── config.py               # pydantic-settings
│       ├── db/
│       │   ├── session.py
│       │   ├── base.py
│       │   └── models/             # SQLAlchemy ORM
│       │       ├── games.py
│       │       ├── players.py
│       │       ├── events.py
│       │       └── ...
│       ├── schemas/                # Pydantic DTOs
│       │   ├── game.py
│       │   ├── event.py
│       │   └── ...
│       ├── routers/                # FastAPI endpoints
│       │   ├── games.py
│       │   ├── events.py
│       │   └── ...
│       ├── services/               # business logic
│       └── auth/
├── migrations/
│   └── versions/
│       └── 0001_initial_schema.py
├── tests/
│   ├── conftest.py                 # testcontainers fixture
│   ├── test_games.py
│   └── ...
└── scripts/
    └── seed_dev.py                  # data de prueba
```
