"""
Sindio — ML Training Pipeline Trigger
======================================
Endpoint to start model training. Training runs for hours,
so it is executed in a background thread with status tracked
via the existing task store (Redis / in-memory).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_auth
from app.services.model_registry import ModelRegistry

logger = logging.getLogger("sindio.training")
router = APIRouter()
model_registry = ModelRegistry()

_training_status = {"state": "idle", "started_at": None, "finished_at": None, "error": None}


def _run_training():
    """Background thread entry point for training."""
    global _training_status
    _training_status = {
        "state": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
    }
    try:
        from app.training.train_model import main as train_main
        train_main()
        _training_status["state"] = "completed"
    except Exception as exc:
        logger.exception("Training failed")
        _training_status["state"] = "failed"
        _training_status["error"] = str(exc)
    finally:
        _training_status["finished_at"] = datetime.now(timezone.utc).isoformat()
        # Reload models in registry so new weights are active
        try:
            model_registry.load_models()
        except Exception:
            logger.warning("Model reload after training failed")


@router.post("/training/start", dependencies=[Depends(require_auth)])
async def start_training():
    """Trigger a full model training run in the background."""
    if _training_status["state"] == "running":
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Guard: verify data exists before starting
    try:
        from app.database import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM sensor_readings")).scalar()
            if count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"No sensor data available ({count} rows in sensor_readings). "
                           "Training requires at least 6 months of real sensor data. "
                           "Run ingestion first: POST /api/v1/ingestion/run",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot verify training data: {exc}. Ensure DATABASE_URL is configured.",
        )

    thread = threading.Thread(target=_run_training, daemon=True)
    thread.start()

    return {
        "status": "started",
        "state": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/training/status")
async def training_status():
    """Check current training status."""
    return _training_status


@router.get("/training/config")
async def training_config():
    """Return current hyperparameters and data requirements."""
    try:
        from app.training.train_model import HYPERPARAMS, HELD_OUT_WARDS
        return {
            "hyperparameters": HYPERPARAMS,
            "held_out_wards": HELD_OUT_WARDS,
            "note": "Training requires at least 6 months of real sensor data for meaningful results.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load training config: {exc}")


# ── Ingestion trigger ────────────────────────────────────────

@router.post("/ingestion/run", dependencies=[Depends(require_auth)])
async def trigger_ingestion():
    """Manually trigger all ingestion fetchers. Returns result counts."""
    try:
        from app.ingestion import run_all
        results = run_all()
        return results
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")


# ── Monitoring health ────────────────────────────────────────

@router.get("/monitoring/health")
async def monitoring_health():
    """Return scheduler health, ingestion status, and DB connectivity."""
    health = {"scheduler": "unknown", "ingestion": None, "db": "unknown"}
    try:
        from app.scheduler import get_health
        health["scheduler"] = get_health()["status"]
        health["ingestion"] = get_health()["last_ingestion"]
    except Exception:
        health["scheduler"] = "unavailable"

    try:
        from app.database import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        health["db"] = "ok"

        # Row counts
        for table in ["sensor_readings", "infrastructure_assets", "population_density", "ingestion_logs"]:
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                health[f"{table}_rows"] = count
            except Exception:
                health[f"{table}_rows"] = "N/A"
    except Exception:
        health["db"] = "unreachable"

    return health
