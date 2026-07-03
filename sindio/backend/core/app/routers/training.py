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

from fastapi import APIRouter, HTTPException

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


@router.post("/training/start")
async def start_training():
    """Trigger a full model training run in the background."""
    if _training_status["state"] == "running":
        raise HTTPException(status_code=409, detail="Training already in progress")

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
