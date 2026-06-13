import json
import os
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.routers import health, simulations, infrastructure, alerts, schedule, monitor, dashboard
from app.auth import auth_router, require_auth, optional_auth
from app.services.data_quality_metrics import registry as dq_registry
from app.services.model_registry import ModelRegistry

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "sindio"),
    "user": os.getenv("DB_USER", "sindio_user"),
    "password": os.getenv("DB_PASSWORD"),
    "connect_timeout": 3,
}

if not DB_CONFIG["password"]:
    raise RuntimeError("DB_PASSWORD environment variable is required")

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("sindio.core")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Sindio Core", port=int(os.getenv("CORE_PORT", "8081")))
    await model_registry.load_models()
    yield
    await model_registry.unload_models()
    logger.info("Sindio Core stopped")


limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app = FastAPI(
    title="Sindio Core",
    description="Python ML core for predictive urban planning simulations",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(simulations.router, prefix="/api/simulations")
app.include_router(infrastructure.router, prefix="/api/infrastructure")
app.include_router(dashboard.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(schedule.router)
app.include_router(monitor.router)


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
        import psycopg2
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
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
