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

**Backend smoke tests** exist in `backend/app/tests/test_api_smoke.py` (pytest + httpx ASGI client). Run them manually from `backend/app/` with:

```bash
PYTHONPATH=".:..:$PYTHONPATH" pytest tests/test_api_smoke.py
```

The Poetry core also declares `pytest`/`pytest-asyncio` as dev deps.

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
| PostgreSQL 16 + PostGIS + TimescaleDB | internal only |
| Qdrant vector DB | `:6333` |
| Redis 7 | internal only |
| MinIO S3-compatible | `:9000` (console `:9001`) |
| PGAdmin | `:5050` |
| LocalStack (mock SQS/SNS) | `:4566` |
| Elasticsearch 8 | `:9200` |
| ML Core (Python) | `:8081` |
| Streaming (Rust) | `:8082` |
| Frontend (nginx) | `:3000` |

**Local development with host access to DB/Redis:**
Create `docker/docker-compose.override.yml`:
```yaml
services:
  postgres:
    ports:
      - "127.0.0.1:5432:5432"
  redis:
    ports:
      - "127.0.0.1:6379:6379"
```
This file is gitignored and auto-merged by Docker Compose for local dev only.

SQL migrations in `backend/migrations/` auto-mount as PostgreSQL init scripts.

## Deployment & infra directories

- `k8s/` — Kubernetes manifests (namespace, configmap, secrets, deployments, services, HPA, Istio VS, ServiceMonitors) with Kustomize + overlays
- ~~`terraform/`~~ — Removed. Infrastructure is managed via Railway dashboard.
- `monitoring/` — Grafana dashboards + Prometheus alerting rules:
  - `data-quality-alerts.yml` — mock fallback ratio, model confidence, real data fetch alerts
  - `infrastructure-alerts.yml` — stress index, degraded assets, time-to-breach, simulation failures, API error/latency

## Production deployment (Railway + Netlify)

**Backend** is deployed to Railway manually via dashboard (Builder = Dockerfile).
- There is no `railway.toml` in this repo — configure services directly in Railway.
- Required env vars in Railway dashboard: `CORS_ORIGINS`, `SINDIO_SKIP_RASTER=1`, `SINDIO_USE_CORE=0`
- `CORS_ORIGINS` must include the deployed Netlify frontend URL

**Frontend** is deployed to Netlify manually (no CI/CD yet).
- Run `npm run build` in `sindio/frontend/` — the `postbuild` script injects a timestamp into `sw.js` to bust the Service Worker cache
- Deploy `dist/` with `netlify deploy --prod --dir=dist`
- Set `VITE_API_BASE_URL=<railway-backend-url>` before building

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

## Real data ingestion

`backend/core/app/ingestion/` contains fetchers that integrate with live Nairobi data sources:

| Fetcher | Source | Data | Env Vars |
|---|---|---|---|
| `KPLCFetcher` | Kenya Power | Substation loading, generation dispatch, outages | `KPLC_API_URL`, `KPLC_API_KEY` |
| `NairobiWaterFetcher` | NCWSC | Reservoirs, treatment plants, pipelines | `NCWSC_PORTAL_URL` |
| `WeatherFetcher` | Open-Meteo / OpenWeatherMap | Thermal stress, UV, humidity | `OPENWEATHER_API_KEY` |
| `OSMFetcher` | OpenStreetMap Overpass | Roads, sidewalks, power lines, water pipes, rail | `OVERPASS_API_URL` |
| `KenyaOpenDataFetcher` | Kenya Open Data Initiative | Wards, roads, power lines GeoJSON | (none, public) |
| `WorldPopFetcher` | WorldPop raster | Population density (297MB GeoTIFF) | `SINDIO_SKIP_RASTER` |
| `NairobiMetropolitanFetcher` | NMS portal | Water supply, road maintenance (HTML scraping) | (none, public) |

**Run all fetchers:**
```bash
cd backend/core && poetry run python -c "from app.ingestion import run_all; print(run_all())"
```

**Run single fetcher:**
```bash
cd backend/core && poetry run python -c "from app.ingestion import run_single; print(run_single('Kenya Power'))"
```

All fetchers follow the `BaseFetcher` pattern: retry with exponential backoff, insert to PostgreSQL, log run outcomes.

## ML training pipeline

```bash
# Train the urban-stress prediction model
cd backend/core && poetry run python app/training/train_stress_model.py --epochs 100 --samples 50000

# Output: models/trained/urban_stress_v1.pth
```

The training script generates synthetic-but-realistic data matching known Nairobi patterns (peak-hour multipliers, wet/dry season, ward population densities) and trains a lightweight MLP (`StressPredictor`) that outputs stress prediction (0-1) and breach classification (4 classes).

## Container images

No automated image builds exist yet. Build manually:

```bash
# Mock API
docker build -f backend/app/Dockerfile -t sindio-api:latest .
# ML Core
docker build -f backend/core/Dockerfile.core -t sindio-simulator:latest .
# Go API
docker build -f backend/api/Dockerfile -t sindio-go-api:latest .
# Streaming
docker build -f backend/streaming/Dockerfile -t sindio-streaming:latest .
# Frontend
docker build -f docker/build/Dockerfile.frontend -t sindio-frontend:latest .
```



## Backup & restore

```bash
# Automated backup (runs via scheduler every 24h)
./scripts/backup_db.sh [s3-bucket-name]

# Restore from backup (requires typing RESTORE to confirm)
./scripts/restore_db.sh /tmp/sindio_backups/sindio_YYYYMMDD_HHMMSS.sql.gz

# Disaster recovery procedures: scripts/disaster_recovery.sh
```

## Seed GIS data

```bash
# Generate synthetic-but-realistic Nairobi ward + infrastructure GeoJSON
python scripts/generate_seed_gis.py
# Output: data/fixtures/nairobi_wards.geojson, power_grid.geojson, water_network.geojson, road_network.geojson
```

## Load testing

```bash
# k6 (install: brew install k6)
cd tests/load && k6 run k6-load-test.js --env API_URL=https://your-api.com

# Locust (install: pip install locust)
cd tests/load && locust -f locustfile.py --host http://localhost:8080
```

## Incident response

Runbooks are in `docs/runbooks/`:
- `incident-response.md` — Severity levels (SEV-1 to SEV-4), response procedures, PIR template
- `alert-escalation.md` — Escalation matrix, notification channels, war room procedure, on-call rotation

## Key gotchas

- `dev.sh` runs the **Python mock API** from `backend/app/` (not the ML Core). It auto-creates a venv at `/tmp/sindio-venv` and sets `CORE_PORT=${CORE_PORT:-8080}` so the frontend Vite proxy aligns. The standalone ML Core (`backend/core/`) runs on port 8081 via Poetry and is started separately.
- The mock API (`backend/app/`) defaults to `SINDIO_USE_CORE=0` — proxy to ML Core must be enabled explicitly in Railway env vars.
- **Local dev with proxy:** `dev.sh` runs Core on port 8080. If you set `SINDIO_USE_CORE=1` locally, also set `CORE_URL=http://localhost:8080` so the Mock API proxy points to the correct port (default is 8081).
- Only one service on port 8080 at a time (Python mock or Go API).
- ML Core loads models on startup via `ModelRegistry`. If model files are missing (`models/trained/*.pth`, `models/embeddings/*.npy`), the registry starts empty and the service relies on heuristics.
- Docker core port mapping is `8081:8081` (matching the container CMD). Frontend nginx proxies `/api/` → `sindio-core:8081`.
- Raw GIS data (`data/raw/*.shp`, `*.geojson`, `*.tif`) is gitignored.
- Rust crate has **two binaries**: default (`cargo run`) starts the HTTP server on :8082; `cargo run --bin mobility-consumer` starts the Kafka → TimescaleDB pipeline.
- Seed script `SYSTEM_TYPES` and `SEVERITY_LEVELS` must match DB CHECK constraints (`roads` not `road`; no `info` severity).
