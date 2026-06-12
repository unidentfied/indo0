"""
Sindio Alert Scheduler — Celery Beat with dynamic intervals.

Infrastructure types run stress tests at different cadences.
When a test detects assets exceeding a critical threshold, the
interval for that type is shortened from 'standard' to 'critical'.

Interval jitter (±10 %) prevents thundering-herd problems when
multiple wards hit the wall clock simultaneously.

Redis keys (prefixed sindio:schedule:):
  - {type}:mode        → "standard" | "critical"
  - {type}:last_run    → ISO-8601 timestamp
  - {type}:next_run    → ISO-8601 timestamp
  - {type}:interval_s  → float seconds

API endpoint: GET /api/v1/next_updates
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Graceful celery fallback — same pattern as schedule.py
try:
    from celery import Celery
    from celery.schedules import crontab
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sindio.scheduler")

# ──────────────────────────────────────────────────────────────
# Celery app (only created when celery is available)
# ──────────────────────────────────────────────────────────────
CELERY_BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

if HAS_CELERY:
    app = Celery(
        "sindio_scheduler",
        broker=CELERY_BROKER,
        backend=CELERY_BACKEND,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Africa/Nairobi",
    )
else:
    app = None  # type: ignore[assignment]

if HAS_CELERY:
    app.conf.update(  # type: ignore[union-attr]
        task_default_queue="sindio_scheduler",
        task_default_routing_key="sindio_scheduler",
        result_expires=timedelta(hours=1),
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )

# ──────────────────────────────────────────────────────────────
# Redis helper (thin wrapper around the broker connection)
# ──────────────────────────────────────────────────────────────
REDIS_PREFIX = "sindio:schedule:"

try:
    import redis as redis_lib

    _redis_pool: Optional[redis_lib.ConnectionPool] = None

    def _get_redis() -> redis_lib.Redis:
        global _redis_pool
        if _redis_pool is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            _redis_pool = redis_lib.ConnectionPool.from_url(redis_url, decode_responses=True)
        return redis_lib.Redis(connection_pool=_redis_pool)

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("redis-py not installed — schedule state will be in-memory only.")

    class _FakeRedis:
        def __init__(self):
            self._store: Dict[str, str] = {}

        def get(self, key: str) -> Optional[str]:
            return self._store.get(key)

        def set(self, key: str, value: str, ex: Optional[int] = None):
            self._store[key] = value

        def setex(self, key: str, ttl: int, value: str):
            self._store[key] = value

        def keys(self, pattern: str = "*") -> List[str]:
            prefix = pattern.replace("*", "")
            return [k for k in self._store if k.startswith(prefix)]

        def mget(self, keys: List[str]) -> List[Optional[str]]:
            return [self._store.get(k) for k in keys]

        def delete(self, *keys: str):
            for k in keys:
                self._store.pop(k, None)

    _fake_redis = _FakeRedis()

    def _get_redis():
        return _fake_redis


# ──────────────────────────────────────────────────────────────
# Intervals & thresholds — sourced from unified registry
# ──────────────────────────────────────────────────────────────
from app.services.monitor.registry import get_all_configs, get_config as get_infra_config

# Build compatibility dicts from registry so existing code paths work
INFRA_TYPES = [c.name for c in get_all_configs()]

INFRASTRUCTURE_INTERVALS: Dict[str, Dict[str, timedelta]] = {}
CRITICAL_THRESHOLDS: Dict[str, float] = {}

for c in get_all_configs():
    INFRASTRUCTURE_INTERVALS[c.name] = {
        "standard": timedelta(days=c.schedule.scheduler_interval_days),
        "critical": timedelta(hours=c.schedule.scheduler_critical_hours),
    }
    CRITICAL_THRESHOLDS[c.name] = c.thresholds.critical

JITTER_FRACTION = 0.10  # ±10 %

MASTER_TICK_MINUTES = 5  # How often the scheduler-master runs


# ──────────────────────────────────────────────────────────────
# Redis state helpers
# ──────────────────────────────────────────────────────────────


def _key(infra_type: str, suffix: str) -> str:
    return f"{REDIS_PREFIX}{infra_type}:{suffix}"


def get_mode(infra_type: str) -> str:
    r = _get_redis()
    return r.get(_key(infra_type, "mode")) or "standard"


def set_mode(infra_type: str, mode: str):
    r = _get_redis()
    r.set(_key(infra_type, "mode"), mode)


def get_last_run(infra_type: str) -> Optional[datetime]:
    r = _get_redis()
    val = r.get(_key(infra_type, "last_run"))
    if val:
        return datetime.fromisoformat(val)
    return None


def set_last_run(infra_type: str, ts: datetime):
    r = _get_redis()
    r.set(_key(infra_type, "last_run"), ts.isoformat())


def get_next_run(infra_type: str) -> Optional[datetime]:
    r = _get_redis()
    val = r.get(_key(infra_type, "next_run"))
    if val:
        return datetime.fromisoformat(val)
    return None


def set_next_run(infra_type: str, ts: datetime):
    r = _get_redis()
    r.set(_key(infra_type, "next_run"), ts.isoformat())


def compute_jittered_interval(infra_type: str) -> timedelta:
    """Return the current interval with ±JITTER_FRACTION applied."""
    mode = get_mode(infra_type)
    base = INFRASTRUCTURE_INTERVALS[infra_type].get(
        mode, INFRASTRUCTURE_INTERVALS[infra_type]["standard"]
    )
    factor = random.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    return timedelta(seconds=base.total_seconds() * factor)


def get_all_next_runs() -> Dict[str, Optional[str]]:
    """Return dict of infra_type → ISO-8601 next_run timestamp."""
    r = _get_redis()
    keys = [_key(t, "next_run") for t in INFRA_TYPES]
    vals = r.mget(keys)
    return {
        t: v for t, v in zip(INFRA_TYPES, vals)
    }


def get_all_modes() -> Dict[str, str]:
    r = _get_redis()
    keys = [_key(t, "mode") for t in INFRA_TYPES]
    vals = r.mget(keys)
    return {
        t: (v or "standard") for t, v in zip(INFRA_TYPES, vals)
    }


# ──────────────────────────────────────────────────────────────
# Tasks (graceful no-op when celery unavailable)
# ──────────────────────────────────────────────────────────────


def _register_scheduler_task(func=None, *, name="", **kwargs):
    """Decorator that registers a Celery task if celery is available, else no-op."""
    def decorator(f):
        if app is None:
            return f
        return app.task(bind=True, name=name, **kwargs)(f)
    if func is not None:
        return decorator(func)
    return decorator


@_register_scheduler_task(name="sindio.scheduler_master", max_retries=0)
def scheduler_master(self=None) -> Dict[str, str]:
    """Periodic master tick — dispatches stress tests for types due to run.

    Runs every MASTER_TICK_MINUTES via Celery Beat.
    Compares current time against each type's next_run, and fires
    run_stress_test_for_type when a type is due.
    """
    now = datetime.now(timezone.utc)
    dispatched: Dict[str, str] = {}

    for infra_type in INFRA_TYPES:
        next_run = get_next_run(infra_type)

        # If no next_run set, initialise it to now + jittered interval
        if next_run is None:
            interval = compute_jittered_interval(infra_type)
            new_next = now + interval
            set_next_run(infra_type, new_next)
            logger.info("[%s] Initialised: mode=%s, next_run=%s", infra_type, get_mode(infra_type), new_next.isoformat())
            continue

        # Is it time?
        if now >= next_run:
            logger.info("[%s] Triggering stress test (was due at %s)", infra_type, next_run.isoformat())
            run_stress_test_for_type.delay(infra_type)

            # Schedule next run with fresh jitter
            interval = compute_jittered_interval(infra_type)
            new_next = now + interval
            set_next_run(infra_type, new_next)
            dispatched[infra_type] = "dispatched"
        else:
            dispatched[infra_type] = "waiting"

    return dispatched


@_register_scheduler_task(
    name="sindio.run_stress_test_for_type",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    acks_late=True,
    task_time_limit=600,
    task_soft_time_limit=540,
)
def run_stress_test_for_type(self=None, infra_type: str = "") -> Dict[str, Any]:
    """Run a stress test for a single infrastructure type.

    1. Runs the simulation engine for this type.
    2. Checks if any asset exceeds the critical threshold.
    3. If yes → switch mode to 'critical' (shorter interval).
    4. If no and mode is 'critical' → revert to 'standard'.
    5. Stores last_run timestamp in Redis.
    """
    logger.info("[%s] Starting stress test…", infra_type)
    now = datetime.now(timezone.utc)

    try:
        from app.services.simulation_engine import SimulationEngine
        from app.services.data_fusion import DataFusionEngine

        fusion = DataFusionEngine()
        ds = fusion.fuse(timestamp=now, features=["population", infra_type])

        engine = SimulationEngine()
        gdf = engine.run(
            fused_dataset=ds,
            density_projection_years=10,
            parallel=False,
        )

        # Filter to this infrastructure type
        type_gdf = gdf[gdf["asset_type"] == infra_type]

        # Check against critical threshold
        threshold = CRITICAL_THRESHOLDS.get(infra_type, 0.80)
        stressed = type_gdf[
            type_gdf["stress_physics"] > threshold
        ]

        previous_mode = get_mode(infra_type)

        if len(stressed) > 0:
            max_stress = stressed["stress_physics"].max()
            if previous_mode != "critical":
                set_mode(infra_type, "critical")
                logger.warning(
                    "[%s] Switched to CRITICAL mode — %d assets > %.0f%% "
                    "(max=%.2f)",
                    infra_type, len(stressed), threshold * 100, max_stress,
                )
            outcome = "critical"
        else:
            if previous_mode == "critical":
                set_mode(infra_type, "standard")
                logger.info("[%s] Reverted to STANDARD mode — all assets below threshold.", infra_type)
            outcome = "standard"

        set_last_run(infra_type, now)

        return {
            "infra_type": infra_type,
            "mode": get_mode(infra_type),
            "previous_mode": previous_mode,
            "outcome": outcome,
            "assets_tested": len(type_gdf),
            "assets_critical": len(stressed),
            "max_stress": float(stressed["stress_physics"].max()) if len(stressed) > 0 else 0.0,
            "last_run": now.isoformat(),
        }

    except Exception as exc:
        logger.error("[%s] Stress test failed: %s", infra_type, exc)
        set_last_run(infra_type, now)
        raise


# ──────────────────────────────────────────────────────────────
# Celery Beat schedule (only when celery is available)
# ──────────────────────────────────────────────────────────────
if HAS_CELERY:
    app.conf.beat_schedule = {  # type: ignore[union-attr]
        "scheduler-master": {
            "task": "sindio.scheduler_master",
            "schedule": timedelta(minutes=MASTER_TICK_MINUTES),
            "options": {"queue": "sindio_scheduler"},
        },
    }

# ──────────────────────────────────────────────────────────────
# API helper — used by the /api/v1/next_updates endpoint
# ──────────────────────────────────────────────────────────────


def get_schedule_status() -> List[Dict[str, Any]]:
    """Return current schedule state for all infrastructure types.

    Called by the FastAPI endpoint /api/v1/next_updates.
    """
    now = datetime.now(timezone.utc)
    modes = get_all_modes()
    next_runs = get_all_next_runs()
    result = []

    for infra_type in INFRA_TYPES:
        next_run_ts = next_runs.get(infra_type)
        next_run_iso = None
        seconds_until: Optional[float] = None

        if next_run_ts:
            next_run_dt = datetime.fromisoformat(next_run_ts)
            next_run_iso = next_run_dt.isoformat()
            seconds_until = max(0.0, (next_run_dt - now).total_seconds())

        result.append({
            "infrastructure_type": infra_type,
            "mode": modes.get(infra_type, "standard"),
            "interval_standard_seconds": INFRASTRUCTURE_INTERVALS[infra_type]["standard"].total_seconds(),
            "interval_critical_seconds": INFRASTRUCTURE_INTERVALS[infra_type]["critical"].total_seconds(),
            "critical_threshold": CRITICAL_THRESHOLDS.get(infra_type, 0.80),
            "next_update": next_run_iso,
            "seconds_until_next": seconds_until,
            "last_run": (
                get_last_run(infra_type).isoformat()
                if get_last_run(infra_type) else None
            ),
        })

    return result


# ──────────────────────────────────────────────────────────────
# Celery Beat CLI entrypoint
# ──────────────────────────────────────────────────────────────
# Run with:
#   celery -A app.services.alert_scheduler beat  --loglevel=info
#   celery -A app.services.alert_scheduler worker --loglevel=info -Q sindio_scheduler
# (in two separate terminals)
