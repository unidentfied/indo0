"""
Sindio — Unified local development server.

Serves all API endpoints directly (no ML Core dependency).
Doubles as a proxy to ML Core on port 8081 when available for
real ML inference and metrics — falls back to mock data gracefully.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import httpx

from app.routers.api import router as api_router

app = FastAPI(
    title="Sindio",
    description="AI-powered urban planning tool for Nairobi — unified local server",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount mock API router at /api prefix ─────────────────────────

app.include_router(api_router, prefix="/api")


# ── Optional proxy to ML Core (port 8081) for health/metrics ─────

_CORE_URL = os.getenv("CORE_URL", "http://localhost:8081")
_USE_CORE = os.getenv("SINDIO_USE_CORE", "1") == "1"


async def _proxy_optional(request: Request, path: str):
    if not _USE_CORE:
        return JSONResponse({"status": "ok", "source": "mock", "core_proxy_disabled": True})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_CORE_URL}{path}")
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
                },
            )
    except Exception:
        return JSONResponse({"status": "ok", "source": "mock", "core_unreachable": True})


@app.get("/health")
@app.post("/health")
async def health(request: Request):
    return await _proxy_optional(request, "/health")


@app.get("/health/ready")
async def health_ready():
    """Kubernetes readiness probe — checks configured dependencies only."""
    deps = {}

    # Check Postgres only if explicitly configured (not default localhost)
    db_host = os.getenv("DB_HOST")
    if db_host and db_host != "localhost":
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=db_host,
                port=os.getenv("DB_PORT", "5432"),
                dbname=os.getenv("DB_NAME", "sindio"),
                user=os.getenv("DB_USER", "sindio_user"),
                password=os.getenv("DB_PASSWORD", ""),
                connect_timeout=3,
            )
            conn.close()
            deps["postgres"] = "ok"
        except Exception:
            deps["postgres"] = "unreachable"
    else:
        deps["postgres"] = "not_configured"

    # Check Redis only if explicitly configured (not default localhost)
    redis_host = os.getenv("REDIS_HOST")
    if redis_host and redis_host != "localhost":
        try:
            import redis
            r = redis.Redis(
                host=redis_host,
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD", ""),
                socket_connect_timeout=3,
            )
            r.ping()
            deps["redis"] = "ok"
        except Exception:
            deps["redis"] = "unreachable"
    else:
        deps["redis"] = "not_configured"

    # Ready if all configured deps are ok; degraded only if configured deps fail
    configured = [v for v in deps.values() if v != "not_configured"]
    all_ok = all(v == "ok" for v in configured) if configured else True
    return JSONResponse(
        {"status": "ready" if all_ok else "degraded", "dependencies": deps},
        status_code=200 if all_ok else 503,
    )


@app.get("/metrics")
async def metrics(request: Request):
    return await _proxy_optional(request, "/metrics")


# ── Frontend serving (production build) ──────────────────────────

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():

    @app.get("/{rest_of_path:path}")
    async def serve_frontend(rest_of_path: str):
        file_path = _FRONTEND_DIST / rest_of_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
