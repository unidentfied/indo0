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

from app.routers import health, simulations, infrastructure, alerts, schedule, monitor, dashboard, training
from app.auth import auth_router, require_auth, optional_auth
from app.services.data_quality_metrics import registry as dq_registry
from app.services.model_registry import ModelRegistry

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Sindio Core", port=config.port)

    # Initialize database schema for ingestion
    from app.database import init_ingestion_tables
    init_ingestion_tables()

    try:
        await model_registry.load_models()
    except Exception:
        logger.warning("Model registry loading failed — running with heuristics only")

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
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Global exception handler for unexpected errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.unbind_contextvars("request_id")
    return response


model_registry = ModelRegistry()

app.include_router(health.router, prefix="/health")
app.include_router(auth_router, prefix="/auth")
app.include_router(simulations.router, prefix="/api/v1/simulations")

app.include_router(infrastructure.router, prefix="/api/v1/infrastructure")

app.include_router(dashboard.router, prefix="/api/v1")

app.include_router(alerts.router, prefix="/api/v1")

app.include_router(schedule.router)
app.include_router(monitor.router)
app.include_router(training.router, prefix="/api/v1")
import os
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

    all_ok = deps.get("postgres") == "ok"
    return Response(
        content=json.dumps({"status": "ready" if all_ok else "degraded", "dependencies": deps}),
        media_type="application/json",
        status_code=200 if all_ok else 503,
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CORE_PORT", "8081")))
