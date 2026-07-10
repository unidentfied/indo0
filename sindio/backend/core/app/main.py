import json
import os
import threading

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.util import get_remote_address

import structlog
from fastapi.middleware.cors import CORSMiddleware

structlog.configure(
    processors=[structlog.processors.JSONRenderer()],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger()
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .config import config

from app.routers import health, simulations, infrastructure, alerts, schedule, monitor, dashboard, training, simulation_compat
from app.auth import auth_router, require_auth, optional_auth
from app.services.data_quality_metrics import registry as dq_registry
from app.services.model_registry import ModelRegistry

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Sindio Core", port=config.port)

    # Load models in background so HTTP server starts immediately
    async def _load_models_bg():
        try:
            await model_registry.load_models()
        except Exception:
            logger.warning("Model registry loading failed — running with heuristics only")

    import asyncio as _asyncio
    _asyncio.create_task(_load_models_bg())

    # Initialize database schema for ingestion in background so HTTP server starts immediately
    def _init_tables():
        try:
            from app.database import init_ingestion_tables
            init_ingestion_tables()
        except Exception as exc:
            logger.warning("Ingestion table init failed (non-critical): %s", exc)

    threading.Thread(target=_init_tables, daemon=True).start()

    # Run external data ingestion in background so HTTP server starts immediately
    if os.getenv("SINDIO_AUTO_INGEST", "1") == "1":
        def _background_ingestion():
            try:
                from app.ingestion import run_all
                results = run_all()
                logger.info("Auto-ingestion complete", results=results)
            except Exception as exc:
                logger.warning("Auto-ingestion failed (non-critical): %s", exc)

        threading.Thread(target=_background_ingestion, daemon=True).start()

    # Start periodic scheduler for recurring ingestion + monitoring
    if os.getenv("SINDIO_SCHEDULER", "1") == "1":
        from app.scheduler import start_scheduler
        start_scheduler()

    yield

    # Shutdown
    if os.getenv("SINDIO_SCHEDULER", "1") == "1":
        from app.scheduler import stop_scheduler
        stop_scheduler()
    await model_registry.unload_models()
    logger.info("Sindio Core stopped")


limiter = Limiter(key_func=get_remote_address, storage_uri=config.redis_url)
app = FastAPI(
    title="Sindio Core",
    description="Python ML core for predictive urban planning simulations",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv("ENV", "development").lower() != "production" else None,
    redoc_url="/redoc" if os.getenv("ENV", "development").lower() != "production" else None,
    openapi_url="/openapi.json" if os.getenv("ENV", "development").lower() != "production" else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Global exception handler for unexpected errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
if not _CORS_ORIGINS:
    if os.getenv("ENV", "development").lower() == "production":
        raise RuntimeError("CORS_ORIGINS environment variable is required in production")
    _CORS_ORIGINS = "http://localhost:3000,https://sindio.net"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.unbind_contextvars("request_id")
    return response


@app.middleware("http")
async def tracing_middleware(request: Request, call_next):
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("sindio.core")
        with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.client_ip", request.client.host if request.client else "")
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            return response
    except ImportError:
        return await call_next(request)


model_registry = ModelRegistry()

app.include_router(health.router, prefix="/health")
app.include_router(auth_router, prefix="/auth")
app.include_router(simulations.router, prefix="/api/v1/simulations")
app.include_router(simulation_compat.router, prefix="/api/v1/simulate")

app.include_router(infrastructure.router, prefix="/api/v1/infrastructure")

app.include_router(dashboard.router, prefix="/api/v1")

app.include_router(alerts.router, prefix="/api/v1")

app.include_router(schedule.router)
app.include_router(monitor.router)
app.include_router(training.router, prefix="/api/v1")
# Static files mount — disabled in Docker because frontend/dist is not copied into the image.
# Serve static files via a reverse proxy (nginx, Netlify, or Railway static serving) instead.
# To enable locally, set CORE_SERVE_STATIC=1.
if os.getenv("CORE_SERVE_STATIC") == "1":
    _frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
    if os.path.isdir(_frontend_dist):
        app.mount("/static", StaticFiles(directory=_frontend_dist, html=True), name="static")



@app.get("/metrics")
@limiter.exempt
def metrics_endpoint():
    return Response(
        generate_latest(registry=dq_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/health/ready")
@limiter.exempt
async def health_ready():
    deps = {}
    deps["models_loaded"] = len(model_registry.models) > 0

    try:
        from app.database import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        deps["postgres"] = "ok"
    except Exception as exc:
        logger.warning("Postgres health check failed", error=str(exc))
        deps["postgres"] = "unreachable"

    # Service is always "ready" to accept requests — it falls back to heuristics / mock data
    # when models or DB are unavailable. Never return 503 here so external healthchecks
    # (e.g., Railway) do not restart the container.
    all_ok = deps.get("postgres") == "ok" and deps.get("models_loaded") is True
    return Response(
        content=json.dumps({"status": "ready" if all_ok else "degraded", "dependencies": deps}),
        media_type="application/json",
        status_code=200,
    )

if __name__ == "__main__":
    import uvicorn
    # Respect Railway's dynamic $PORT; fallback to CORE_PORT then 8081
    _port = int(os.getenv("PORT", os.getenv("CORE_PORT", "8081")))
    uvicorn.run(app, host="0.0.0.0", port=_port)
