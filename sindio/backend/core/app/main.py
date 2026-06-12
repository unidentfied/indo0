import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.routers import health, simulations, infrastructure, alerts, schedule, monitor, dashboard
from app.services.data_quality_metrics import registry as dq_registry
from app.services.model_registry import ModelRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    await model_registry.load_models()
    yield
    await model_registry.unload_models()


app = FastAPI(
    title="Sindio Core",
    description="Python ML core for predictive urban planning simulations",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model_registry = ModelRegistry()

app.include_router(health.router, prefix="/health")
app.include_router(simulations.router, prefix="/api/simulations")
app.include_router(infrastructure.router, prefix="/api/infrastructure")
app.include_router(dashboard.router, prefix="/api")  # /api/dashboard/*
app.include_router(schedule.router)  # /api/v1/next_updates
app.include_router(monitor.router)  # /api/v1/monitor/*


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus metrics endpoint including data quality gauges."""
    return Response(
        generate_latest(registry=dq_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/health/ready")
async def health_ready():
    """Kubernetes readiness probe — checks model registry and DB."""
    deps = {}
    deps["models_loaded"] = len(model_registry.models) > 0

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "sindio"),
            user=os.getenv("DB_USER", "sindio_user"),
            password=os.getenv("DB_PASSWORD", "sindio_pass"),
            connect_timeout=3,
        )
        conn.close()
        deps["postgres"] = "ok"
    except Exception:
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
