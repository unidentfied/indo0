"""
Sindio — Unified local development server.

Serves all API endpoints directly (no ML Core dependency).
Doubles as a proxy to ML Core on port 8081 when available for
real ML inference and metrics — falls back to mock data gracefully.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Response, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import httpx

import structlog
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from jose import jwt as _jwt

from app.limiter import limiter

from app.shutdown import install_signal_handlers, register_shutdown_handler
from app.rbac import require_viewer

structlog.configure(
    processors=[structlog.processors.JSONRenderer()],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger("sindio.mock_api")

from app.routers.api import router as api_router
from app.routers.streaming import router as stream_router
from app.routers.reports import router as reports_router
from app.routers.feedback import router as feedback_router
from app.routers.privacy import router as privacy_router

_ENV = os.getenv("ENV", "development").lower()

app = FastAPI(
    title="Sindio",
    description="AI-powered urban planning tool for Nairobi — unified local server",
    version="0.1.0",
    docs_url="/docs" if _ENV != "production" else None,
    redoc_url="/redoc" if _ENV != "production" else None,
    openapi_url="/openapi.json" if _ENV != "production" else None,
)

# Install graceful shutdown handlers
install_signal_handlers()

# Body size limit middleware
@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:  # 10 MB
        return JSONResponse(
            {"detail": "Request body exceeds 10MB limit"},
            status_code=413,
        )
    return await call_next(request)

_JWT_SECRET = os.getenv("JWT_SECRET", "")

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
if not _CORS_ORIGINS:
    if os.getenv("ENV", "development").lower() == "production":
        raise RuntimeError("CORS_ORIGINS environment variable is required in production")
    logger.warning(
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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Security headers middleware ────────────────────────────

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self';"
    )
    if not request.url.hostname or request.url.hostname in ("localhost", "127.0.0.1"):
        response.headers["Strict-Transport-Security"] = "max-age=0"
    else:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ── Structured request logging middleware ──────────────────

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    logger.info("request", method=request.method, path=request.url.path)
    response = await call_next(request)
    logger.info("response", status_code=response.status_code, path=request.url.path)
    return response

# ── RBAC + API key auth middleware ────────────────────────────

_API_KEY = os.getenv("SINDIO_API_KEY", "")


@app.middleware("http")
async def rbac_middleware(request: Request, call_next):
    """Enforce authentication on protected endpoints.

    Public endpoints (health, metrics, docs, stream) are exempt.
    All other endpoints require a valid API key OR a valid JWT Bearer token.
    """
    public_paths = {"/health", "/metrics", "/docs", "/openapi.json", "/api/v1/stream"}
    if any(request.url.path.startswith(p) for p in public_paths):
        return await call_next(request)

    authenticated = False

    # 1. API key check
    if _API_KEY:
        header_key = request.headers.get("X-API-Key", "")
        if header_key == _API_KEY:
            authenticated = True

    # 2. JWT Bearer token check (fallback when no API key or invalid)
    if not authenticated and _JWT_SECRET:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                _jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
                authenticated = True
            except Exception:
                pass

    if not authenticated:
        return JSONResponse(
            {"detail": "Unauthorized — missing or invalid API key or JWT token"},
            status_code=401,
        )

    return await call_next(request)

# ── Global exception handler ─────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Audit logging middleware ───────────────────────────────

@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        logger.info(
            "audit",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            client_host=request.client.host if request.client else None,
        )
    return response

# ── Trace ID propagation middleware ────────────────────────

import uuid as _uuid

@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or request.headers.get("X-Request-ID") or str(_uuid.uuid4())
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    structlog.contextvars.unbind_contextvars("trace_id")
    return response

# ── OpenTelemetry tracing middleware ───────────────────────

@app.middleware("http")
async def tracing_middleware(request: Request, call_next):
    from opentelemetry import trace
    tracer = trace.get_tracer("sindio.mock_api")
    with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        span.set_attribute("http.client_ip", request.client.host if request.client else "")
        response = await call_next(request)
        span.set_attribute("http.status_code", response.status_code)
        return response

# ── Optional proxy to ML Core (port 8081) ────────────────────────

_CORE_URL = os.getenv("CORE_URL", "http://localhost:8081")
_USE_CORE = os.getenv("SINDIO_USE_CORE", "0") == "1"


@app.middleware("http")
async def core_proxy_middleware(request: Request, call_next):
    """Proxy /api/v1/* requests to ML Core when available.

    If Core returns a successful response (< 500), return it directly.
    Otherwise (5xx or unreachable) fall through to the mock API router
    so endpoints the core lacks or crashes on still work.
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

            # Core has this endpoint and is healthy — return its response
            if resp.status_code < 500:
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


# ── Mount all routers ──────────────────────────────────────────
app.include_router(api_router, prefix="/api", dependencies=[Depends(require_viewer)])
app.include_router(stream_router, prefix="/api/v1")
app.include_router(reports_router, dependencies=[Depends(require_viewer)])
app.include_router(feedback_router, dependencies=[Depends(require_viewer)])
app.include_router(privacy_router)   # individual endpoints already enforce role checks


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
            from app.core.database import get_engine
            from sqlalchemy import text
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
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
        if rest_of_path.startswith(("api", "health", "metrics", "docs", "openapi")):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = _FRONTEND_DIST / rest_of_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
