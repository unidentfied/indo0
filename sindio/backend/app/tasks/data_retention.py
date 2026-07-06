"""Sindio — Data retention task for GDPR compliance and storage cost control."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import text

from app.core.database import get_engine

logger = logging.getLogger("sindio.retention")

_RETENTION_DAYS = {
    "feedback": 365,
    "sensor_telemetry": 90,
    "simulations": 180,
    "playbook_executions": 365,
}


@shared_task(name="sindio.data_retention.cleanup_old_data")
def cleanup_old_data():
    """Delete or anonymize data older than the retention policy."""
    engine = get_engine()
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    total_deleted = 0

    with engine.connect() as conn:
        for table, days in _RETENTION_DAYS.items():
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            try:
                result = conn.execute(
                    text(f"DELETE FROM {table} WHERE created_at < :cutoff"),
                    {"cutoff": cutoff},
                )
                conn.commit()
                deleted = result.rowcount
                total_deleted += deleted
                logger.info("Retention cleanup", table=table, deleted=deleted, cutoff=cutoff.isoformat())
            except Exception as exc:
                logger.warning("Retention cleanup failed", table=table, error=str(exc))

    logger.info("Retention cleanup complete", total_deleted=total_deleted)
    return {"total_deleted": total_deleted}
