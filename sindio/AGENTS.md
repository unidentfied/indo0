# AGENTS.md — Sindio

## Project root

All paths below assume you are in `sindio/`. The workspace root (`S:i/`) contains only asset directories (`imagg/`, `venv/`) — do not treat it as the project root.

## Multi-language monorepo

The `backend/` directory contains **four independent services** in different languages:

| Service | Language | Dir | Port | Role |
|---|---|---|---|---|
| FastAPI mock | Python | `backend/app/` | 8080 | Simple mock API (default backend for frontend) |
| ML Core | Python | `backend/core/` | 8081 | ML inference, simulation, alerts (Poetry-managed) |
| Go API | Go | `backend/api/` | 8080 | Alternative mock API (same endpoints, Gin framework) |
| Streaming | Rust | `backend/streaming/` | 8082 | Axum HTTP server for sensor ingest + Kafka consumer binary |

**Only one service should use port 8080 at a time** — the Python FastAPI mock and Go API are alternative implementations of the same endpoints.

## Developer commands

```bash
# ═══════════════════════════════════════════════════════════════
# Quick-start local development (no Docker/DB needed)
# ═══════════════════════════════════════════════════════════════

# Start both backend (8080) + frontend (3000) in one command
./dev.sh

# Or start individually
./dev.sh backend     # FastAPI mock on :8080
./dev.sh frontend    # Vite dev server on :3000 (proxies /api → :8080)

# The dev.sh script auto-creates a Python venv at /tmp/sindio-venv
# and installs only pre-built wheels (fastapi, uvicorn, httpx, pydantic, numpy).
# rasterio is NOT installed — the backend falls back to hardcoded
# Nairobi density points automatically.

# ═══════════════════════════════════════════════════════════════
# Manual setup (if not using dev.sh)
# ═══════════════════════════════════════════════════════════════

# One-shot full setup (all languages + docker pull + .env)
./scripts/setup_dev_env.sh

# Infrastructure (must be running for any backend service that uses DB/Redis/etc.)
docker compose -f docker/docker-compose.yml up -d

# Frontend (port 3000, proxies /api → :8080)
cd frontend && npm run dev

# Python FastAPI mock (port 8080, self-contained, no ML Core needed)
cd backend/app && SINDIO_SKIP_RASTER=1 PYTHONPATH=".:..:$PYTHONPATH" \
  uvicorn app.main:app --reload --port 8080

# Python ML Core (port 8081, Poetry)
cd backend/core && poetry install --with dev && poetry run uvicorn app.main:app --port 8081 --reload

# Go API (port 8080)
cd backend/api && go run ./cmd/api/

# Rust streaming HTTP server (port 8082)
cd backend/streaming && cargo run

# Rust mobility consumer (Kafka → TimescaleDB, separate binary)
cd backend/streaming && cargo run --bin mobility-consumer

# Seed test data (requires PostgreSQL from docker-compose & .env)
python scripts/seed_test_data.py

# Discover new data sources (requires SERPAPI_API_KEY)
python scripts/discover_data_sources.py
```

There is **no test suite yet**. The Poetry core declares `pytest` and `pytest-asyncio` as dev deps but no test files exist.

## Environment config

Copy `.env.example` to `.env` before running anything. The docker-compose services and seed script read from `.env`. Key variables: `DB_*`, `REDIS_*`, `QDRANT_*`, `MINIO_*`, `ELASTICSEARCH_*`, `OPENAI_API_KEY`, `MAPBOX_ACCESS_TOKEN`, `HUGGINGFACE_HUB_TOKEN`.

Set `SINDIO_SKIP_RASTER=1` in `.env` to skip the 297 MB WorldPop raster download during development.

## Python conventions

- **Line length**: 100 (black + ruff, configured in `backend/core/pyproject.toml`)
- **Type checking**: mypy strict mode (`mypy --strict`)
- **Lint**: `ruff check .` (configured in pyproject.toml)
- **Format**: `black .`
- The ML Core uses Poetry; the mock API uses plain pip/requirements.txt

## Frontend

- React 18 + Vite 5 + Tailwind CSS 3 + TypeScript 5
- Two routes only: `/` (LandingPage) and `/dashboard` (Dashboard)
- Vite dev server proxies `/api` and `/health` → `http://localhost:8080`
- Falls back to hardcoded mock data if the backend is unreachable — this is by design
- Tailwind uses custom `sindio-*` color tokens defined in `tailwind.config.js`
- Map visualization uses maplibre-gl + deck.gl

## Docker infrastructure

`docker compose -f docker/docker-compose.yml up -d` starts:
- PostgreSQL 16 + PostGIS 3.4 + TimescaleDB 2 on `:5432`
- Qdrant vector DB on `:6333`
- Redis 7 on `:6379`
- MinIO S3-compatible on `:9000` (console at `:9001`)
- PGAdmin on `:5050`
- LocalStack (mock SQS/SNS) on `:4566`
- Elasticsearch 8 on `:9200` (hybrid text search for alerts)

SQL migrations live in `backend/migrations/` and are auto-mounted as init scripts for the PostgreSQL container.

## Deployment & infra directories

- `k8s/` — Kubernetes manifests (namespace, configmap, secrets, deployments, services, HPA, Istio VS, ServiceMonitors) with Kustomize + overlays
- `terraform/` — IaC with `dev.tfvars` and `prod.tfvars`
- `monitoring/` — Grafana dashboards + Prometheus alerting rules:
  - `sindio-dashboard.json` — general infrastructure stress, RAG, alert rates
  - `data-quality-dashboard.json` — real data ratio, mock fallback rate, model confidence per infra type
  - `data-quality-alerts.yml` — Prometheus rules: alert when mock > 10% for > 1h

## Data quality metrics

All services expose `/metrics` (Prometheus format) with data quality gauges:
- `data_quality_real_data_ratio{infrastructure_type}` — fraction of assets with fresh real data (0–1)
- `data_quality_mock_fallback_ratio{infrastructure_type}` — fraction served from mock/fallback (0–1)
- `data_quality_model_confidence{infrastructure_type}` — average model confidence (0–1)
- `data_quality_fallback_total{infrastructure_type,source}` — cumulative fallback events
- `data_quality_real_fetch_total{infrastructure_type,source}` — cumulative real fetches

The mock FastAPI backend (`backend/app/`) always reports 100% mock ratio. The ML Core (`backend/core/`) updates ratios based on actual PostGIS/Kafka connectivity. The Go API reports ratios based on pgx pool health.

## Unified monitoring system

`backend/core/app/services/monitor/` is a **single parameterized system** for ALL infrastructure types (power, water, roads, solid_waste, sidewalks, lrt, sgr, airports). Infrastructure type is just a config key — there are NO separate systems per type.

- `registry.py` — **single source of truth** for all per-type settings (thresholds, intervals, actions, data sources, physics engines). Previously scattered across 7+ files.
- `monitor.py` — `InfrastructureMonitor` class: one class handles all types identically. Entry point: `get_all_stressed_assets()` returns stressed assets across ALL types in one call.
- `ingestion.py` — unified data ingestion: tries Postgres → HTTP API → Kafka → fallback, in order.
- `baseline.py` — historical baseline comparison with time-of-day and day-of-week heuristics.
- `reports.py` — official report integration: checks real-time data against published reports.
- `stress.py` — unified stress calculator: dispatches to pandapower (power), EPANET (water), CTM (roads), or heuristic (all others).

**API endpoint**: `GET /api/v1/monitor/stress` — single call returns all stressed assets across all types with baseline deviation, failure mode, time-to-breach, recommendation, data source freshness, and report alignment.

**To add a new infrastructure type**: add one `InfraConfig` entry in `registry.py`. No other code changes needed.

## Key gotchas

- The `backend/app/` (mock FastAPI) and `backend/api/` (Go) serve the same API surface on port 8080. You only need one of them running.
- The Python ML Core (`backend/core/`) loads ML models on startup via `ModelRegistry`. If model files are missing, the service will fail to start.
- Model files (`models/trained/*.pth`, `models/embeddings/*.npy`) are gitignored — they are large and must be provided separately.
- Raw GIS data (`data/raw/*.shp`, `*.geojson`, `*.tif`) is gitignored.
- The Rust streaming crate has **two binaries**: the default `sindio-streaming` (Axum HTTP server on port 8082, `src/main.rs`) and `mobility-consumer` (Kafka → TimescaleDB, `src/mobility/main.rs`). `cargo run` alone starts the HTTP server.
