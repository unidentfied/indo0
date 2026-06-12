"""
Async inference queue using Celery + Redis.

Tasks:
  - infer_single_cell(cell_id, lat, lon, timestamp)
  - infer_batch(cells: list[dict])

Workers consume tasks, run RAGInferenceEngine, and cache results
in Qdrant + Redis. Batches are split into chunks of 256 cells.

Configuration via env:
  CELERY_BROKER_URL  (default: redis://localhost:6379/0)
  CELERY_RESULT_BACKEND (default: redis://localhost:6379/1)
  MODEL_PATH         (default: models/trained/sindio_foundation_v1.pt)

Usage:
  celery -A app.services.inference_queue worker --loglevel=info --concurrency=4
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from celery import Celery, group, chord
from celery.signals import worker_ready, worker_shutdown
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

# ──────────────────────────────────────────────────────────────
# Celery app
# ──────────────────────────────────────────────────────────────
CELERY_BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery(
    "sindio_inference",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=300,       # 5 minutes per task
    task_soft_time_limit=240,  # 4 minutes soft limit
    worker_max_tasks_per_child=500,
    worker_concurrency=4,
)

app.conf.update(
    task_default_queue="sindio_inference",
    task_default_routing_key="sindio_inference",
    result_expires=timedelta(hours=6),
    worker_prefetch_multiplier=1,
)

# ──────────────────────────────────────────────────────────────
# Lazy-loaded engine (one per worker process)
# ──────────────────────────────────────────────────────────────
_engine: Any = None


def _get_engine():
    global _engine
    if _engine is None:
        from app.services.rag_inference import RAGInferenceEngine

        model_path = os.getenv(
            "MODEL_PATH", "models/trained/sindio_foundation_v1.pt"
        )
        _engine = RAGInferenceEngine(model_path=model_path)
        logger.info("RAGInferenceEngine initialised (model=%s)", model_path)
    return _engine


@worker_ready.connect
def on_worker_ready(**kwargs):
    _get_engine()
    logger.info("Celery worker ready — engine loaded.")


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    global _engine
    _engine = None
    logger.info("Celery worker shutdown — engine released.")


# ──────────────────────────────────────────────────────────────
# Tasks
# ──────────────────────────────────────────────────────────────

@app.task(
    bind=True,
    name="sindio.infer_cell",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def infer_single_cell(
    self,
    cell_id: str,
    lat: float,
    lon: float,
    timestamp: Optional[str] = None,
    force_fresh: bool = False,
) -> Dict[str, Any]:
    """Async inference for a single cell.

    Args:
        cell_id: unique cell identifier.
        lat: latitude in WGS84.
        lon: longitude in WGS84.
        timestamp: ISO-8601 string (defaults to now).
        force_fresh: skip Qdrant cache lookup.

    Returns:
        dict with keys: cell_id, stress_power, stress_water, stress_road,
                        breach_prob, source, cache_score.
    """
    engine = _get_engine()
    ts = datetime.fromisoformat(timestamp) if timestamp else datetime.now(timezone.utc)

    result = engine.infer_cell(
        cell_id=cell_id,
        lat=lat,
        lon=lon,
        timestamp=ts,
        force_fresh=force_fresh,
    )

    return {
        "cell_id": result.cell_id,
        "lat": result.lat,
        "lon": result.lon,
        "timestamp": result.timestamp.isoformat(),
        "stress_power": result.stress_power,
        "stress_water": result.stress_water,
        "stress_road": result.stress_road,
        "breach_prob": result.breach_prob,
        "source": result.source,
        "cache_score": result.cache_score,
    }


@app.task(
    bind=True,
    name="sindio.infer_batch",
    acks_late=True,
)
def infer_batch(
    self,
    cells: List[Dict[str, Any]],
    force_fresh: bool = False,
) -> List[Dict[str, Any]]:
    """Async batch inference for up to 256 cells.

    Splits into sub-tasks of 256, runs them as a Celery group.

    Args:
        cells: list of dicts with keys: cell_id, lat, lon, timestamp?.
        force_fresh: skip cache for all cells.

    Returns:
        list of result dicts, same order as input.
    """
    CHUNK_SIZE = 256
    if len(cells) > CHUNK_SIZE:
        chunks = [cells[i:i + CHUNK_SIZE] for i in range(0, len(cells), CHUNK_SIZE)]
        jobs = group(
            infer_batch_chunk.s(chunk, force_fresh) for chunk in chunks
        )
        result = jobs.apply_async()
        nested = result.get(timeout=600)
        output = []
        for chunk_results in nested:
            output.extend(chunk_results)
        return output

    return _infer_batch_sync(cells, force_fresh)


@app.task(
    bind=True,
    name="sindio.infer_batch_chunk",
    acks_late=True,
)
def infer_batch_chunk(
    self,
    cells: List[Dict[str, Any]],
    force_fresh: bool = False,
) -> List[Dict[str, Any]]:
    """Single chunk of ≤256 cells. Called internally by infer_batch."""
    return _infer_batch_sync(cells, force_fresh)


def _infer_batch_sync(
    cells: List[Dict[str, Any]],
    force_fresh: bool = False,
) -> List[Dict[str, Any]]:
    """Synchronous batch inference shared by all tasks."""
    engine = _get_engine()
    results = engine.infer_batch(cells=cells, force_fresh=force_fresh)

    return [
        {
            "cell_id": r.cell_id,
            "lat": r.lat,
            "lon": r.lon,
            "timestamp": r.timestamp.isoformat(),
            "stress_power": r.stress_power,
            "stress_water": r.stress_water,
            "stress_road": r.stress_road,
            "breach_prob": r.breach_prob,
            "source": r.source,
            "cache_score": r.cache_score,
        }
        for r in results
    ]


# ──────────────────────────────────────────────────────────────
# Utility: submit jobs from non-Celery code
# ──────────────────────────────────────────────────────────────


def submit_cell_inference(
    cell_id: str,
    lat: float,
    lon: float,
    timestamp: Optional[str] = None,
    force_fresh: bool = False,
) -> Any:
    """Submit a single-cell inference job. Returns AsyncResult."""
    return infer_single_cell.delay(cell_id, lat, lon, timestamp, force_fresh)


def submit_batch_inference(
    cells: List[Dict[str, Any]],
    force_fresh: bool = False,
) -> Any:
    """Submit a batch inference job. Returns AsyncResult."""
    return infer_batch.delay(cells, force_fresh)


def submit_region_inference(
    bbox: Tuple[float, float, float, float],
    resolution_m: int = 100,
    force_fresh: bool = False,
) -> Any:
    """Generate a grid over a bounding-box region and submit all cells.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) in WGS84.
        resolution_m: cell size in metres.
        force_fresh: force model run for all cells.
    """
    import geopandas as gpd
    from shapely.geometry import box

    # Convert bbox to UTM 37S grid
    gdf_bbox = gpd.GeoDataFrame(
        {"geometry": [box(*bbox)]},
        crs="EPSG:4326",
    ).to_crs("EPSG:32737")

    bounds = gdf_bbox.total_bounds
    xmin, ymin, xmax, ymax = bounds

    cells = []
    x = xmin
    while x < xmax:
        y = ymin
        while y < ymax:
            # Convert cell centre back to WGS84
            centre = gpd.GeoSeries(
                [box(x, y, x + resolution_m, y + resolution_m).centroid],
                crs="EPSG:32737",
            ).to_crs("EPSG:4326")
            lon, lat = centre.iloc[0].x, centre.iloc[0].y
            cells.append({
                "cell_id": f"region_{int(x)}_{int(y)}",
                "lat": float(lat),
                "lon": float(lon),
            })
            y += resolution_m
        x += resolution_m

    logger.info("Region submission: %d cells over bbox=%s", len(cells), bbox)
    return submit_batch_inference(cells, force_fresh=force_fresh)
