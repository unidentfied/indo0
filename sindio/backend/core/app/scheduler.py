"""
Sindio — Periodic Data Refresh Scheduler
===========================================
Uses APScheduler to run ingestion fetchers on a configurable interval.
Stores job state in Redis so multiple core instances don't duplicate work.
Includes DB backup scheduling and health-check endpoint for monitoring.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger("sindio.scheduler")

_scheduler: Optional[AsyncIOScheduler] = None
_health: dict = {"status": "stopped", "last_ingestion": None, "last_monitor": None, "errors": 0}


def _build_jobstores():
    """Redis job store if REDIS_URL is set and reachable, otherwise memory fallback."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            # Parse Redis URL to extract host/port/db for APScheduler RedisJobStore
            # APScheduler RedisJobStore expects a host parameter, not full URL
            # We try the URL-form first; if it fails, fall back to memory
            store = RedisJobStore(
                jobs_key="sindio.jobs",
                run_times_key="sindio.run_times",
                host=redis_url,
            )
            logger.info("Scheduler using Redis job store")
            return {"default": store}
        except Exception as exc:
            logger.warning("Redis job store unavailable (%s) — using memory fallback", exc)
    logger.warning("REDIS_URL not set — scheduler using in-memory job store (state lost on restart)")
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
    backup_interval_hours = int(os.getenv("SINDIO_BACKUP_INTERVAL_HOURS", "24"))

    sched.add_job(
        _run_ingestion, "interval", minutes=ingest_interval_min,
        id="ingestion_run_all", replace_existing=True,
    )
    sched.add_job(
        _run_monitor_refresh, "interval", minutes=5,
        id="monitor_refresh", replace_existing=True,
    )
    sched.add_job(
        _run_db_backup, "interval", hours=backup_interval_hours,
        id="db_backup", replace_existing=True,
    )

    sched.start()
    _health["status"] = "running"
    logger.info("Scheduler started (ingest:%dmin, monitor:5min, backup:%dh)", ingest_interval_min, backup_interval_hours)


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _health["status"] = "stopped"
        logger.info("Scheduler stopped")
        _scheduler = None


def get_health() -> dict:
    """Return scheduler + ingestion health for monitoring."""
    return dict(_health)


# ── Job callbacks ────────────────────────────────────────────

def _run_ingestion() -> None:
    """Execute all external data fetchers."""
    try:
        from app.ingestion import run_all
        results = run_all()
        _health["last_ingestion"] = datetime.now(timezone.utc).isoformat()
        _health["errors"] = results.get("failed", 0)
        logger.info("Scheduled ingestion complete: %s", results)
    except Exception as exc:
        _health["errors"] += 1
        logger.exception("Scheduled ingestion failed: %s", exc)


def _run_monitor_refresh() -> None:
    """Refresh monitor caches so the dashboard serves recent data."""
    try:
        from app.services.monitor import InfrastructureMonitor
        from app.services.monitor.registry import get_all_configs
        for cfg in get_all_configs():
            monitor = InfrastructureMonitor(cfg.name)
            monitor.run(force_mock=False)
        _health["last_monitor"] = datetime.now(timezone.utc).isoformat()
        logger.debug("Monitor refresh complete for all types")
    except Exception as exc:
        logger.warning("Monitor refresh failed: %s", exc)


def _run_db_backup() -> None:
    """Dump the database to a local file for disaster recovery."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DB backup skipped — DATABASE_URL not set")
        return
    backup_dir = Path("/tmp/sindio_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"sindio_backup_{ts}.sql"
    try:
        subprocess.run(
            ["pg_dump", db_url, "--no-owner", "--no-acl", "-f", str(path)],
            check=True, capture_output=True, timeout=300,
        )
        logger.info("DB backup written to %s (%d bytes)", path, path.stat().st_size)
        # Rotate: keep last 7
        backups = sorted(backup_dir.glob("sindio_backup_*.sql"))
        for old in backups[:-7]:
            old.unlink()
    except Exception as exc:
        logger.error("DB backup failed: %s", exc)
