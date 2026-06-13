from __future__ import annotations

import os
import logging

import sqlalchemy
from sqlalchemy import create_engine, Engine

logger = logging.getLogger("sindio.db")

_engine: Engine | None = None


def _build_db_url() -> str:
    user = os.getenv("DB_USER", "sindio_user")
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD environment variable is required for database access")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "sindio")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL") or _build_db_url()
        _engine = create_engine(
            db_url,
            pool_size=int(os.getenv("DB_POOL_MIN", "5")),
            max_overflow=int(os.getenv("DB_POOL_MAX", "10")) - int(os.getenv("DB_POOL_MIN", "5")),
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        logger.info("Database connection pool initialized (pool_size=%s, max_overflow=%s)",
                     _engine.pool.size(), _engine.pool.overflow())
    return _engine


def get_db_url() -> str:
    return os.getenv("DATABASE_URL") or _build_db_url()
