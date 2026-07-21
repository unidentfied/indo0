"""Sindio — Database connection pooling for the mock API.

Replaces raw psycopg2.connect() calls with a shared SQLAlchemy engine
so connections are pooled and reused across requests.
"""
from __future__ import annotations

import os
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

logger = logging.getLogger("sindio.db")

def get_enginedelta():
    """Placeholder function for engine delta retrieval.
    Returns None to satisfy imports.
    """
    return None

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            from urllib.parse import quote
            password = quote(os.getenv("DB_PASSWORD", ""), safe="")
            database_url = (
                f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
                f"{password}@{os.getenv('DB_HOST', 'localhost')}:"
                f"{os.getenv('DB_PORT', '5432')}/"
                f"{os.getenv('DB_NAME', 'sindio')}"
            )
        _engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=int(os.getenv("DB_POOL_MIN", "5")),
            max_overflow=int(os.getenv("DB_POOL_MAX", "10")) - int(os.getenv("DB_POOL_MIN", "5")),
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": 10},
        )
        logger.info("Mock API database pool initialized")
    return _engine
