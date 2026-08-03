# backend/core/app/services/health.py
"""Health endpoint implementations.
Provides additional health checks such as database connectivity.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text, create_engine
from backend.core.app.logging import logger


def _get_db_engine():
    """Lightweight DB engine factory — inlined here to avoid importing the
    heavy ingest_geospatial module (which pulls in pandas, geopandas, etc.)."""
    from backend.core.app.config import config
    return create_engine(config.database_url)


router = APIRouter()

@router.get("/health/db", tags=["Health"], summary="Database connectivity check", response_description="Health status")
async def health_db():
    """Check database connectivity.
    Returns 200 with status "ok" if a simple SELECT succeeds.
    Returns 503 on failure.
    """
    try:
        engine = _get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.error("db_health_check_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable")
