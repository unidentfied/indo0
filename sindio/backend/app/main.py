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

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
if not _CORS_ORIGINS:
    import logging
    logging.getLogger("sindio.main").warning(
        "CORS_ORIGINS is not set. CORS will default to localhost-only. "
        "Set CORS_ORIGINS in your Railway/Render dashboard to your frontend URL(s)."
    )
    _CORS_ORIGINS = "http://localhost:3000"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API key auth middleware (write-protect POST/PUT/DELETE) ──

_API_KEY = os.getenv("SINDIO_API_KEY", "")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Require X-API-Key on write operations when SINDIO_API_KEY is set."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and _API_KEY:
        header_key = request.headers.get("X-API-Key", "")
        if header_key != _API_KEY:
            return JSONResponse(
                {"detail": "Unauthorized — missing or invalid API key"},
                status_code=401,
            )
    return await call_next(request)

# ── Optional proxy to ML Core (port 8081) ────────────────────────

_CORE_URL = os.getenv("CORE_URL", "http://localhost:8081")
_USE_CORE = os.getenv("SINDIO_USE_CORE", "1") == "1"


@app.middleware("http")
async def core_proxy_middleware(request: Request, call_next):
    """Proxy /api/v1/* requests to ML Core when available.

    If the core has the endpoint (returns non-404), we return the core's
    response directly. If the core returns 404 or is unreachable, we fall
    through to the mock API router so endpoints the core lacks still work.
    """
    if not _USE_CORE:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/v1/"):
        return await call_next(request)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            method = request.method
            url = f"{_CORE_URL}{path}"
            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length", "transfer-encoding")
            }
            body = await request.body()
            params = str(request.query_params)

            resp = await client.request(
                method, url, headers=headers, content=body, params=params
            )

            # Core has this endpoint — return its response
            if resp.status_code != 404:
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers={
                        k: v
                        for k, v in resp.headers.items()
                        if k.lower()
                        not in ("transfer-encoding", "content-encoding", "content-length")
                    },
                )
    except Exception:
        pass  # Core unreachable — fall through to mock API

    return await call_next(request)


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


# ── Mount mock API router at /api prefix ─────────────────────────
app.include_router(api_router, prefix="/api")


@app.get("/health")
@app.post("/health")
async def health(request: Request):
    return await _proxy_optional(request, "/health")


@app.get("/health/ready")
async def health_ready():
    """Kubernetes readiness probe — checks configured dependencies only."""
    deps = {}

    # ── Postgres ───────────────────────────────────────────────────
    database_url = os.getenv("DATABASE_URL")
    db_host = os.getenv("DB_HOST")
    if database_url or (db_host and db_host != "localhost"):
        try:
            import psycopg2
            if database_url:
                conn = psycopg2.connect(database_url, connect_timeout=3)
            else:
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

    # ── Redis ──────────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL")
    redis_host = os.getenv("REDIS_HOST")
    if redis_url or (redis_host and redis_host != "localhost"):
        try:
            import redis
            if redis_url:
                r = redis.Redis.from_url(
                    redis_url,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
            else:
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
