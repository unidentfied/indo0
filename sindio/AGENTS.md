# AGENTS.md — Sindio

## Project root & git

All working paths below assume you are in `sindio/`. **Git operations** must be run from the workspace root (`S:i/`) — that is where `.git/` lives.

## Multi-language monorepo

The `backend/` directory contains **four independent services**:

| Service | Language | Dir | Port | Role |
|---|---|---|---|---|
| ML Core | Python | `backend/core/app/` | 8081 (default) | ML inference, simulation, alerts, monitoring (Poetry-managed) |
| FastAPI mock | Python | `backend/app/` | 8080 | Simple mock API; can proxy to ML Core on :8081 |
| Go API | Go | `backend/api/` | 8080 | Alternative mock API (same endpoints, Gin framework) |
| Streaming | Rust | `backend/streaming/` | 8082 | Axum HTTP server + Kafka consumer binary |

**Only one service on port 8080 at a time** — the Python mock and Go API are alternative implementations.

## Developer commands

```bash
# ═══════════════════════════════════════════════════════════════
# Quick-start (no Docker/DB needed)
# ═══════════════════════════════════════════════════════════════

./dev.sh              # Start ML Core (default port 8080) + frontend (4000)
./dev.sh backend      # ML Core only (${CORE_PORT:-8080})
./dev.sh frontend     # Vite dev server only (:4000)

# dev.sh auto-creates /tmp/sindio-venv with pre-built wheels.
# rasterio is NOT installed — falls back to hardcoded Nairobi density points.

# ═══════════════════════════════════════════════════════════════
# Manual / individual services
# ═══════════════════════════════════════════════════════════════

# Full setup (all runtimes + docker pull + .env)
./scripts/setup_dev_env.sh

# Infrastructure (PostgreSQL, Redis, Qdrant, MinIO, etc.)
docker compose -f docker/docker-compose.yml up -d

# Frontend — port 4000, proxies /api → :8080 (or $VITE_API_URL)
cd frontend && npm run dev

# Python ML Core (port 8081, Poetry; requires pydantic-settings)
cd backend/core && poetry install --with dev && poetry run uvicorn app.main:app --port 8081 --reload

# Python FastAPI mock (port 8080, plain pip; proxies to ML Core on :8081 if available)
cd backend/app && SINDIO_SKIP_RASTER=1 PYTHONPATH=".:..:$PYTHONPATH" \
  uvicorn app.main:app --reload --port 8080

# Go API (port 8080; tests: go test ./...)
cd backend/api && go run ./cmd/api/
cd backend/api && go test ./... -v

# Rust streaming HTTP server (port 8082; tests: cargo test)
cd backend/streaming && cargo run

# Rust Kafka → TimescaleDB consumer (separate binary)
cd backend/streaming && cargo run --bin mobility-consumer

# Seed test data (requires PostgreSQL from docker-compose & .env)
python scripts/seed_test_data.py

# ═══════════════════════════════════════════════════════════════
# Frontend verification
# ═══════════════════════════════════════════════════════════════

npm run lint          # tsc --noEmit
npm run test          # vitest run (jsdom, globals, setupFiles: src/test-setup.ts)
npm run build         # tsc && vite build
```

**No backend test suite exists yet.** The Poetry core declares `pytest`/`pytest-asyncio` as dev deps but no test files are present.

## Environment config

Copy `.env.example` to `.env` before running anything. docker-compose and seed scripts read from `.env`.

Key variables: `DB_*`, `REDIS_*`, `QDRANT_*`, `MINIO_*`, `ELASTICSEARCH_*`, `OPENAI_API_KEY`, `MAPBOX_ACCESS_TOKEN`, `HUGGINGFACE_HUB_TOKEN`.

Set `SINDIO_SKIP_RASTER=1` in `.env` to skip the 297 MB WorldPop raster download.

## Python conventions

- **Line length**: 100 (black + ruff, `backend/core/pyproject.toml`)
- **Type checking**: `mypy --strict` (configured in pyproject.toml)
- **Lint**: `ruff check .`
- **Format**: `black .`
- ML Core uses Poetry; the mock API uses plain pip (`backend/requirements.txt`)

## Frontend

- React 18 + Vite 5 + Tailwind CSS 3 + TypeScript 5
- Routes: `/` (LandingPage), `/dashboard` (Dashboard), plus NotFoundPage and PlaceholderPage
- Vite server on **port 4000**; proxies `/api` and `/health` → `http://localhost:8080` (overridable via `VITE_API_URL`)
- Centralized API client at `src/services/api.ts` — all HTTP calls should go through this module
- Falls back to hardcoded mock data if backend is unreachable — by design
- Custom `sindio-*` color tokens in `tailwind.config.js`
- Map visualization: maplibre-gl + deck.gl

## Docker infrastructure

`docker compose -f docker/docker-compose.yml up -d` starts:

| Service | Port |
|---|---|
| PostgreSQL 16 + PostGIS + TimescaleDB | `:5432` |
| Qdrant vector DB | `:6333` |
| Redis 7 | `:6379` |
| MinIO S3-compatible | `:9000` (console `:9001`) |
| PGAdmin | `:5050` |
| LocalStack (mock SQS/SNS) | `:4566` |
| Elasticsearch 8 | `:9200` |
| ML Core (Python) | `:8081` |
| Streaming (Rust) | `:8082` |
| Frontend (nginx) | `:3000` |

SQL migrations in `backend/migrations/` auto-mount as PostgreSQL init scripts.

## Deployment & infra directories

- `k8s/` — Kubernetes manifests (namespace, configmap, secrets, deployments, services, HPA, Istio VS, ServiceMonitors) with Kustomize + overlays
- `terraform/` — IaC with `dev.tfvars` and `prod.tfvars`
- `monitoring/` — Grafana dashboards + Prometheus alerting rules:
  - `data-quality-alerts.yml` — mock fallback ratio, model confidence, real data fetch alerts
  - `infrastructure-alerts.yml` — stress index, degraded assets, time-to-breach, simulation failures, API error/latency

## Production deployment (Railway + Netlify)

**Backend** is deployed to Railway via `railway.toml` (config-as-code) + `sindio/backend/app/Dockerfile`.
- Railway auto-deploys on every push to `main`
- Required env vars in Railway dashboard: `CORS_ORIGINS`, `SINDIO_SKIP_RASTER=1`, `SINDIO_USE_CORE=0`
- `CORS_ORIGINS` must include the deployed Netlify frontend URL

**Frontend** is deployed to Netlify via GitHub Actions (`.github/workflows/frontend.yml`).
- GitHub Actions builds `sindio/frontend/` and deploys `dist/` to Netlify
- Requires GitHub secrets: `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`
- Requires GitHub variable or `.env.production`: `VITE_API_BASE_URL=<railway-backend-url>`

**API connection:**
- Dev: Vite proxy (`/api` → `localhost:8080`)
- Prod: `VITE_API_BASE_URL` is baked into the build; all `/api/*` and `/health` calls go directly to Railway

Full instructions: `sindio/DEPLOY.md`

## Data quality metrics

All services expose `/metrics` (Prometheus) with gauges keyed by `infrastructure_type`. The mock app always reports 100% mock ratio; the ML Core updates based on actual connectivity.

## Unified monitoring system

`backend/core/app/services/monitor/` — **single parameterized system** for all infrastructure types (power, water, roads, solid_waste, sidewalks, lrt, sgr, airports).

- `registry.py` — single source of truth for per-type settings (thresholds, intervals, actions, data sources, physics engines)
- `monitor.py` — `InfrastructureMonitor` handles all types; `get_all_stressed_assets()` returns stressed assets across ALL types
- `ingestion.py` — cascade: Postgres → HTTP API → Kafka → fallback
- `stress.py` — dispatches to pandapower (power), EPANET (water), CTM (roads), or heuristic

**API**: `GET /api/v1/monitor/stress` returns all stressed assets with baseline deviation, failure mode, time-to-breach, and recommendation.

**To add an infrastructure type**: add one `InfraConfig` entry in `registry.py`. No other changes needed.

## Key gotchas

- `dev.sh` runs the **ML Core** from `backend/core/app/`, not the mock API. It exports `JWT_SECRET` and `DB_PASSWORD` with dev defaults so the ML Core can start without `.env`.
- `dev.sh` also exports `CORE_PORT=8080` so the frontend Vite proxy (`:8080` default) aligns. The standalone ML Core uses port 8081.
- The mock API (`backend/app/`) defaults to `SINDIO_USE_CORE=1` — it will proxy to ML Core on :8081 when available.
- Only one service on port 8080 at a time (Python mock or Go API).
- ML Core loads models on startup via `ModelRegistry`. If model files are missing (`models/trained/*.pth`, `models/embeddings/*.npy`), the registry starts empty and the service relies on heuristics.
- Docker core port mapping is `8081:8081` (matching the container CMD). Frontend nginx proxies `/api/` → `sindio-core:8081`.
- Raw GIS data (`data/raw/*.shp`, `*.geojson`, `*.tif`) is gitignored.
- Rust crate has **two binaries**: default (`cargo run`) starts the HTTP server on :8082; `cargo run --bin mobility-consumer` starts the Kafka → TimescaleDB pipeline.
- Seed script `SYSTEM_TYPES` and `SEVERITY_LEVELS` must match DB CHECK constraints (`roads` not `road`; no `info` severity).
