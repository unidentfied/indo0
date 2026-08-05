import json
import os
import threading
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .auth import auth_router
from .config import config
from .logging import logger
from .routers import (
    alerts,
    dashboard,
    health,
    infrastructure,
    monitor,
    schedule,
    simulation_compat,
    simulations,
    training,
)
from .routers.carbon import carbon_router
from .routers.cascade import cascade_router
from .routers.cities import city_router
from .routers.citizen_reports import citizen_reports_router
from .routers.datasets import datasets_router
from .routers.insurance import insurance_router
from .routers.nl_map import nl_map_router
from .routers.population import population_router
from .routers.roi import roi_router
from .routers.snapshot import snapshot_router
from .routers.data_freshness import data_freshness_router
from .services.data_quality_metrics import registry as dq_registry
from .services.model_registry import ModelRegistry


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

    # Initialize database schema for ingestion + users in background
    def _init_tables():
        try:
            from sqlalchemy import inspect

            from .database import get_engine, init_ingestion_tables
            engine = get_engine()
            init_ingestion_tables()
            from .models.user import User, UserBase

            inspector = inspect(engine)
            if "users" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("users")}
                if "password_hash" not in cols or "full_name" in cols:
                    logger.warning("users table has old schema — dropping and recreating (no user data will be lost because the old schema was incompatible)")
                    UserBase.metadata.drop_all(bind=engine, tables=[User.__table__])

            UserBase.metadata.create_all(bind=engine)
            from .models.city import CityBase
            CityBase.metadata.create_all(bind=engine)
            from .models.population import PopulationBase
            PopulationBase.metadata.create_all(bind=engine)
            from .models.carbon import CarbonBase
            CarbonBase.metadata.create_all(bind=engine)
            from .models.insurance import InsuranceBase
            InsuranceBase.metadata.create_all(bind=engine)
            from .models.cascade import CascadeBase
            CascadeBase.metadata.create_all(bind=engine)
            from .models.citizen_report import CitizenReportBase
            CitizenReportBase.metadata.create_all(bind=engine)
            from .models.roi import RoiBase
            RoiBase.metadata.create_all(bind=engine)
            logger.info("Database tables verified/created (core)")
        except Exception as exc:
            logger.warning("Table init failed (non-critical): %s", exc)

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


_ENV_NAME = os.getenv("ENV", "development").lower()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://" if _ENV_NAME != "production" else config.redis_url,
    enabled=_ENV_NAME != "test",
)
app = FastAPI(
    title="Sindio Core",
    description="Python ML core for predictive urban planning simulations",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _ENV_NAME != "production" else None,
    redoc_url="/redoc" if _ENV_NAME != "production" else None,
    openapi_url="/openapi.json" if _ENV_NAME != "production" else None,
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
    _CORS_ORIGINS = "http://localhost:4000,http://localhost:3000,https://sindio.net"

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
app.include_router(simulations.router, prefix="/api/simulations")

app.include_router(simulation_compat.router, prefix="/api/v1/simulate")
app.include_router(simulation_compat.router, prefix="/api/simulate")

app.include_router(infrastructure.router, prefix="/api/v1/infrastructure")
app.include_router(infrastructure.router, prefix="/api/infrastructure")

app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api")

app.include_router(alerts.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api")

app.include_router(schedule.router)
app.include_router(monitor.router)
app.include_router(training.router, prefix="/api/v1")
app.include_router(city_router, prefix="/api/v1")
app.include_router(population_router, prefix="/api/v1")
app.include_router(carbon_router, prefix="/api/v1")
app.include_router(insurance_router, prefix="/api/v1")
app.include_router(datasets_router, prefix="/api/v1")
app.include_router(roi_router, prefix="/api/v1")
app.include_router(cascade_router, prefix="/api/v1")
app.include_router(citizen_reports_router, prefix="/api/v1")
app.include_router(data_freshness_router, prefix="/api/v1")
app.include_router(nl_map_router, prefix="/api/v1")
app.include_router(snapshot_router, prefix="/api/v1")
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


@app.get("/health/live")
@limiter.exempt
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
@limiter.exempt
async def health_ready():
    deps = {}
    deps["models_loaded"] = model_registry.loaded_count
    deps["models_total"] = model_registry.trained_total
    deps["embeddings_ready"] = model_registry.embeddings_ready
    deps["models"] = model_registry.summary

    try:
        from sqlalchemy import text

        from app.database import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        deps["postgres"] = "ok"
    except Exception as exc:
        logger.warning("Postgres health check failed", error=str(exc))
        deps["postgres"] = "unreachable"

    try:
        import redis as _redis
        _r = _redis.Redis.from_url(config.redis_url, socket_connect_timeout=2)
        _r.ping()
        _r.close()
        deps["redis"] = "ok"
    except Exception as exc:
        logger.warning("Redis health check failed", error=str(exc))
        deps["redis"] = "unreachable"

    has_models = model_registry.loaded_count > 0
    has_postgres = deps.get("postgres") == "ok"
    has_redis = deps.get("redis") == "ok"
    all_ok = has_models and has_postgres and has_redis

    return Response(
        content=json.dumps({"status": "ready" if all_ok else "degraded", "dependencies": deps}),
        media_type="application/json",
        status_code=200 if all_ok else 503,
    )

if __name__ == "__main__":
    import uvicorn
    # Respect Railway's dynamic $PORT; fallback to CORE_PORT then 8081
    _port = int(os.getenv("PORT", os.getenv("CORE_PORT", "8081")))
    uvicorn.run(app, host="0.0.0.0", port=_port)
