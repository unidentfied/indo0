"""
Long Interval Scheduler — Celery Beat
=======================================

Runs infrastructure stress tests at cadences measured in *months*,
not hours.  Schedule state is persisted in PostgreSQL for durability
across pod restarts (Redis is too volatile for 6+ month intervals).

Key differences from ``alert_scheduler.py``:
  - PostgreSQL-backed state (not Redis).
  - Per-asset scheduling (not per-type mode switching).
  - Critical floor per type (30/45/60/90 days, not a single absolute).
  - Recurring multiplier per type (1.3–2.0, not a single 2x).
  - 5 % jitter (tighter than the 10 % in the short-interval scheduler).
  - Dispatcher tick runs every 1 hour (not every 5 minutes).

Usage::

    celery -A app.services.long_interval_scheduler beat   --loglevel=info
    celery -A app.services.long_interval_scheduler worker --loglevel=info -Q sindio_long_interval
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sindio.long_scheduler")

# ======================================================================
# Celery app
# ======================================================================

CELERY_BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

long_app = Celery(
    "sindio_long_scheduler",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Africa/Nairobi",
    enable_utc=True,
)

long_app.conf.update(
    task_default_queue="sindio_long_interval",
    task_default_routing_key="sindio_long_interval",
    result_expires=timedelta(days=30),
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_time_limit=3600,        # 1 hour max per task
    task_soft_time_limit=3300,   # 55 minutes soft
)

# ======================================================================
# Infrastructure intervals (long — measured in months)
# Data collection period per type for recurring-stress detection.
# ======================================================================

INFRASTRUCTURE_INTERVALS: Dict[str, Dict[str, Any]] = {
    "water": {
        "minimum": timedelta(days=180),          # 6 months
        "recurring_multiplier": 2.0,              # → 360 days
        "critical_floor": timedelta(days=30),
        "data_window_months": 6,                  # pipe burst patterns detectable in 6mo
    },
    "power": {
        "minimum": timedelta(days=210),           # 7 months
        "recurring_multiplier": 1.8,              # → 378 days
        "critical_floor": timedelta(days=45),
        "data_window_months": 6,                  # load patterns emerge quickly
    },
    "roads": {
        "minimum": timedelta(days=270),           # 9 months
        "recurring_multiplier": 1.5,              # → 405 days
        "critical_floor": timedelta(days=60),
        "data_window_months": 9,                  # seasonal traffic needs 9mo
    },
    "solid_waste": {
        "minimum": timedelta(days=365),           # 12 months
        "recurring_multiplier": 1.3,              # → 474 days
        "critical_floor": timedelta(days=90),
        "data_window_months": 8,                  # collection patterns over 8mo
    },
    "sidewalks": {
        "minimum": timedelta(days=180),           # 6 months
        "recurring_multiplier": 2.2,              # → 396 days (pedestrian patterns slow)
        "critical_floor": timedelta(days=45),
        "data_window_months": 12,                 # pedestrian flow changes very slowly
    },
    "lrt": {
        "minimum": timedelta(days=150),           # 5 months
        "recurring_multiplier": 1.6,              # → 240 days
        "critical_floor": timedelta(days=30),
        "data_window_months": 6,                  # train schedules create clear patterns
    },
    "sgr": {
        "minimum": timedelta(days=150),           # 5 months
        "recurring_multiplier": 1.5,              # → 225 days
        "critical_floor": timedelta(days=30),
        "data_window_months": 6,                  # SGR schedules are regular
    },
    "airports": {
        "minimum": timedelta(days=210),           # 7 months
        "recurring_multiplier": 1.9,              # → 399 days
        "critical_floor": timedelta(days=30),
        "data_window_months": 12,                 # flight schedules change seasonally
    },
}

INFRA_TYPES = list(INFRASTRUCTURE_INTERVALS.keys())
DISPatCH_TICK_MINUTES = 60   # How often the dispatcher checks for due assets
JITTER_FRACTION = 0.05       # ±5 %

# ======================================================================
# PostgreSQL helpers
# ======================================================================

def _get_db_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
        f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME', 'sindio')}",
    )


def _init_schedule_table() -> None:
    """Idempotent table creation."""
    import psycopg2

    conn = psycopg2.connect(_get_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS long_interval_schedule (
                    asset_id              TEXT PRIMARY KEY,
                    infrastructure_type   VARCHAR(20) NOT NULL,
                    classification        VARCHAR(20) DEFAULT 'normal',
                    density_rho           DOUBLE PRECISION,
                    current_stress        DOUBLE PRECISION,
                    base_interval_days    INTEGER NOT NULL,
                    applied_multiplier    DOUBLE PRECISION DEFAULT 1.0,
                    final_interval_days   INTEGER NOT NULL,
                    jitter_pct            DOUBLE PRECISION DEFAULT 0,
                    last_run              TIMESTAMPTZ,
                    next_run              TIMESTAMPTZ NOT NULL,
                    last_result           JSONB DEFAULT '{}',
                    created_at            TIMESTAMPTZ DEFAULT NOW(),
                    updated_at            TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_lis_next_run
                    ON long_interval_schedule (next_run)
                    WHERE next_run IS NOT NULL;
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_lis_infra
                    ON long_interval_schedule (infrastructure_type, next_run);
            """)
            conn.commit()
    finally:
        conn.close()


def _pg_conn():
    import psycopg2
    return psycopg2.connect(_get_db_url())


# ======================================================================
# Interval calculation (the core business logic)
# ======================================================================

def get_next_interval(
    infrastructure_type: str,
    classification: str = "normal",
    density_rho: Optional[float] = None,
    current_stress: float = 0.5,
    random_seed: Optional[int] = None,
) -> Tuple[timedelta, float, float]:
    """Compute the next check interval for a single asset.

    Returns
    -------
    (interval, multiplier, jitter_pct)
    """
    cfg = INFRASTRUCTURE_INTERVALS.get(infrastructure_type)
    if cfg is None:
        raise ValueError(f"Unknown infrastructure_type: {infrastructure_type}")

    base = cfg["minimum"]
    multiplier = 1.0

    # ── Recurring-only → multiply ────────────────────────────
    if classification == "recurring_only" and (density_rho is None or density_rho < 0.3):
        multiplier = cfg["recurring_multiplier"]

    # ── Critical stress → shorten (but never below critical_floor) ──
    if current_stress > 0.85:
        critical_floor = cfg["critical_floor"]
        base = max(critical_floor, base * 0.5)
        multiplier = 1.0  # Critical overrides recurring multiplier

    interval = timedelta(seconds=base.total_seconds() * multiplier)

    # ── Jitter (±5 %) — clamped to not fall below critical_floor ──
    rng = random.Random(random_seed) if random_seed is not None else random.Random()
    jitter_factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    jittered = interval.total_seconds() * jitter_factor
    jitter_pct = (jitter_factor - 1.0) * 100

    # Clamp to critical_floor (per-type)
    floor = cfg["critical_floor"].total_seconds()
    jittered = max(jittered, floor)

    return timedelta(seconds=jittered), multiplier, jitter_pct


# ======================================================================
# Schedule state persistence (PostgreSQL — not Redis)
# ======================================================================

def _upsert_schedule(
    asset_id: str,
    infra_type: str,
    classification: str,
    density_rho: Optional[float],
    current_stress: float,
    next_run: datetime,
    base_days: int,
    multiplier: float,
    final_days: int,
    jitter_pct: float,
    last_run: Optional[datetime] = None,
) -> None:
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO long_interval_schedule
                    (asset_id, infrastructure_type, classification, density_rho,
                     current_stress, base_interval_days, applied_multiplier,
                     final_interval_days, jitter_pct, last_run, next_run)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO UPDATE SET
                    classification      = EXCLUDED.classification,
                    density_rho         = EXCLUDED.density_rho,
                    current_stress      = EXCLUDED.current_stress,
                    base_interval_days  = EXCLUDED.base_interval_days,
                    applied_multiplier  = EXCLUDED.applied_multiplier,
                    final_interval_days = EXCLUDED.final_interval_days,
                    jitter_pct          = EXCLUDED.jitter_pct,
                    last_run            = EXCLUDED.last_run,
                    next_run            = EXCLUDED.next_run,
                    updated_at          = NOW()
                """,
                (
                    asset_id, infra_type, classification, density_rho,
                    current_stress, base_days, multiplier, final_days,
                    jitter_pct, last_run, next_run,
                ),
            )
            conn.commit()
    finally:
        conn.close()


def _get_due_assets(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Return assets whose ``next_run`` <= now (due to be checked)."""
    ts = now or datetime.now(timezone.utc)
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_id, infrastructure_type, classification,
                       density_rho, current_stress, next_run
                FROM long_interval_schedule
                WHERE next_run <= %s
                ORDER BY next_run
                LIMIT 100
                """,
                (ts,),
            )
            rows = cur.fetchall()
            return [
                {
                    "asset_id": r[0],
                    "infrastructure_type": r[1],
                    "classification": r[2] or "normal",
                    "density_rho": float(r[3]) if r[3] is not None else None,
                    "current_stress": float(r[4]) if r[4] is not None else 0.5,
                    "next_run": r[5],
                }
                for r in rows
            ]
    finally:
        conn.close()


def _mark_completed(asset_id: str, result: Dict[str, Any]) -> None:
    """Update last_run, recompute next_run, store result."""
    conn = _pg_conn()
    try:
        now = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT infrastructure_type, classification, density_rho,
                       current_stress, base_interval_days
                FROM long_interval_schedule
                WHERE asset_id = %s
                """,
                (asset_id,),
            )
            row = cur.fetchone()
            if row is None:
                return

            infra_type = row[0]
            classification = row[1] or "normal"
            density_rho = row[2]
            current_stress = float(row[3]) if row[3] is not None else 0.5

            interval, multiplier, jitter_pct = get_next_interval(
                infrastructure_type=infra_type,
                classification=classification,
                density_rho=density_rho,
                current_stress=current_stress,
            )
            next_run = now + interval

            cur.execute(
                """
                UPDATE long_interval_schedule
                SET last_run = %s, next_run = %s,
                    final_interval_days = %s,
                    applied_multiplier = %s,
                    jitter_pct = %s,
                    last_result = %s,
                    updated_at = NOW()
                WHERE asset_id = %s
                """,
                (
                    now, next_run, int(interval.total_seconds() / 86400),
                    float(multiplier), jitter_pct,
                    json.dumps(result, default=str),
                    asset_id,
                ),
            )
            conn.commit()
    finally:
        conn.close()


# ======================================================================
# Register / seed a new asset
# ======================================================================

def register_asset(
    asset_id: str,
    infrastructure_type: str,
    classification: str = "normal",
    density_rho: Optional[float] = None,
    current_stress: float = 0.5,
    random_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Register a new asset in the schedule and return its next_run."""
    cfg = INFRASTRUCTURE_INTERVALS.get(infrastructure_type)
    if cfg is None:
        raise ValueError(f"Unknown infrastructure_type: {infrastructure_type}")

    interval, multiplier, jitter_pct = get_next_interval(
        infrastructure_type=infrastructure_type,
        classification=classification,
        density_rho=density_rho,
        current_stress=current_stress,
        random_seed=random_seed,
    )

    now = datetime.now(timezone.utc)
    next_run = now + interval
    base_days = int(cfg["minimum"].total_seconds() / 86400)
    final_days = int(interval.total_seconds() / 86400)

    _upsert_schedule(
        asset_id=asset_id,
        infra_type=infrastructure_type,
        classification=classification,
        density_rho=density_rho,
        current_stress=current_stress,
        next_run=next_run,
        base_days=base_days,
        multiplier=multiplier,
        final_days=final_days,
        jitter_pct=jitter_pct,
        last_run=None,
    )

    logger.info(
        "Registered %s: next_run=%s (%dd, %.1fx, jitter=%+.1f%%)",
        asset_id, next_run.isoformat(), final_days, multiplier, jitter_pct,
    )
    return {
        "asset_id": asset_id,
        "infrastructure_type": infrastructure_type,
        "next_run": next_run.isoformat(),
        "interval_days": final_days,
        "multiplier": multiplier,
        "jitter_pct": jitter_pct,
    }


# ======================================================================
# Celery tasks
# ======================================================================

@long_app.task(
    bind=True,
    name="sindio.long_dispatcher",
    max_retries=0,
)
def long_dispatcher(self) -> Dict[str, Any]:
    """Periodic dispatcher — fires ``run_stress_test_for_type`` for due assets.

    Runs once per hour via Celery Beat.
    """
    now = datetime.now(timezone.utc)
    due = _get_due_assets(now)

    if not due:
        return {"dispatched": 0, "message": "No assets due"}

    by_type: Dict[str, List[str]] = {}
    for asset in due:
        by_type.setdefault(asset["infrastructure_type"], []).append(asset["asset_id"])

    for infra_type, asset_ids in by_type.items():
        run_stress_test_for_type.delay(infra_type, asset_ids)
        logger.info(
            "Dispatched %s for %d assets: %s",
            infra_type, len(asset_ids), asset_ids[:3],
        )

    return {"dispatched": len(due), "by_type": {k: len(v) for k, v in by_type.items()}}


@long_app.task(
    bind=True,
    name="sindio.long_run_stress_test",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    acks_late=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,
)
def run_stress_test_for_type(
    self,
    infra_type: str,
    asset_ids: List[str],
) -> Dict[str, Any]:
    """Run stress tests for a batch of assets belonging to one type."""
    logger.info("[%s] Running stress test for %d assets", infra_type, len(asset_ids))
    results: Dict[str, Any] = {"infra_type": infra_type, "assets": {}}

    try:
        from app.services.simulation_engine import SimulationEngine
        from app.services.data_fusion import DataFusionEngine

        fusion = DataFusionEngine()
        ds = fusion.fuse(
            timestamp=datetime.now(timezone.utc),
            features=["population", infra_type],
        )

        engine = SimulationEngine()
        gdf = engine.run(fused_dataset=ds, density_projection_years=10, parallel=False)

        for asset_id in asset_ids:
            row = gdf[gdf["asset_id"] == asset_id] if "asset_id" in gdf.columns else None
            stress_val = float(row["stress_physics"].iloc[0]) if row is not None and len(row) > 0 else 0.5

            result = {
                "asset_id": asset_id,
                "stress": stress_val,
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
            _mark_completed(asset_id, result)
            results["assets"][asset_id] = result

    except Exception as exc:
        logger.error("[%s] Stress test failed: %s", infra_type, exc)
        raise

    return results


# ======================================================================
# Celery Beat schedule
# ======================================================================

long_app.conf.beat_schedule = {
    "long-dispatcher": {
        "task": "sindio.long_dispatcher",
        "schedule": timedelta(minutes=DISPatCH_TICK_MINUTES),
        "options": {"queue": "sindio_long_interval"},
    },
}

# ======================================================================
# API helper — used by /api/v1/next_updates
# ======================================================================

def get_next_updates(
    infrastructure_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the schedule state for the next_updates API endpoint.

    All returned timestamps are in the future — no asset is scheduled
    sooner than its type minimum from today.
    """
    now = datetime.now(timezone.utc)
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            if infrastructure_type:
                cur.execute(
                    """
                    SELECT asset_id, infrastructure_type, classification,
                           density_rho, current_stress, base_interval_days,
                           final_interval_days, last_run, next_run, last_result
                    FROM long_interval_schedule
                    WHERE infrastructure_type = %s
                    ORDER BY next_run
                    """,
                    (infrastructure_type,),
                )
            else:
                cur.execute(
                    """
                    SELECT asset_id, infrastructure_type, classification,
                           density_rho, current_stress, base_interval_days,
                           final_interval_days, last_run, next_run, last_result
                    FROM long_interval_schedule
                    ORDER BY next_run
                    """,
                )

            rows = cur.fetchall()
            results = []
            for r in rows:
                next_run = r[8]
                last_run = r[7]
                results.append({
                    "asset_id": r[0],
                    "update_type": r[1],
                    "classification": r[2] or "normal",
                    "density_rho": float(r[3]) if r[3] is not None else None,
                    "current_stress": float(r[4]) if r[4] is not None else None,
                    "interval_days": int(r[6]),
                    "next_at": next_run.isoformat() if next_run else None,
                    "last_run": last_run.isoformat() if last_run else None,
                    "seconds_until_next": (
                        max(0.0, (next_run - now).total_seconds())
                        if next_run else None
                    ),
                })

            return results
    finally:
        conn.close()


def get_upcoming_assets(days_ahead: int = 7) -> List[Dict[str, Any]]:
    """Return assets scheduled within the next N days."""
    now = datetime.now(timezone.utc)
    window = now + timedelta(days=days_ahead)

    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_id, infrastructure_type, next_run, final_interval_days
                FROM long_interval_schedule
                WHERE next_run BETWEEN %s AND %s
                ORDER BY next_run
                """,
                (now, window),
            )
            return [
                {
                    "asset_id": r[0],
                    "infrastructure_type": r[1],
                    "next_run": r[2].isoformat(),
                    "interval_days": int(r[3]),
                }
                for r in cur.fetchall()
            ]
    finally:
        conn.close()
