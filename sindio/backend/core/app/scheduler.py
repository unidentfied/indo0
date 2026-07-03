"""
Sindio — Periodic Data Refresh Scheduler
===========================================
Uses APScheduler to run ingestion fetchers on a configurable interval.
Stores job state in Redis so multiple core instances don't duplicate work.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger("sindio.scheduler")

_scheduler: Optional[AsyncIOScheduler] = None


def _build_jobstores():
    """Redis job store if REDIS_URL is set, otherwise memory fallback."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return {"default": RedisJobStore(jobs_key="sindio.jobs", run_times_key="sindio.run_times", host=redis_url)}
    return {"default": {"type": "memory"}}


def _build_executors():
    return {"default": ThreadPoolExecutor(max_workers=2)}


def _build_job_defaults():
    return {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}


def get_scheduler() -> AsyncIOScheduler:
    """Return the global scheduler instance (singleton)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores=_build_jobstores(),
            executors=_build_executors(),
            job_defaults=_build_job_defaults(),
            timezone="UTC",
        )
    return _scheduler


def start_scheduler() -> None:
    """Start the scheduler and register periodic jobs."""
    sched = get_scheduler()
    if sched.running:
        return

    ingest_interval_min = int(os.getenv("SINDIO_INGEST_INTERVAL_MIN", "60"))

    # Main ingestion job: runs all fetchers
    sched.add_job(
        _run_ingestion,
        "interval",
        minutes=ingest_interval_min,
        id="ingestion_run_all",
        replace_existing=True,
    )

    # Light monitoring refresh: every 5 minutes (populates dashboard)
    sched.add_job(
        _run_monitor_refresh,
        "interval",
        minutes=5,
        id="monitor_refresh",
        replace_existing=True,
    )

    sched.start()
    logger.info("Scheduler started (ingest every %d min, monitor every 5 min)", ingest_interval_min)


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        _scheduler = None


# ── Job callbacks ────────────────────────────────────────────

def _run_ingestion() -> None:
    """Execute all external data fetchers."""
    try:
        from app.ingestion import run_all
        results = run_all()
        logger.info("Scheduled ingestion complete: %s", results)
    except Exception as exc:
        logger.exception("Scheduled ingestion failed: %s", exc)


def _run_monitor_refresh() -> None:
    """Refresh monitor caches so the dashboard serves recent data."""
    try:
        from app.services.monitor import InfrastructureMonitor
        from app.services.monitor.registry import get_all_configs
        for cfg in get_all_configs():
            monitor = InfrastructureMonitor(cfg.name)
            monitor.run(force_mock=False)
        logger.debug("Monitor refresh complete for all types")
    except Exception as exc:
        logger.warning("Monitor refresh failed: %s", exc)
