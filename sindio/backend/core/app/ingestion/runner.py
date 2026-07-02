"""
Sindio — Unified Ingestion Runner
===================================
Orchestrates all external-data fetchers, runs them sequentially,
logs outcomes, and provides a scheduler-compatible interface.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .base import FetcherResult
from .kodi import KenyaOpenDataFetcher
from .nms import NairobiMetropolitanFetcher
from .kenya_power import KenyaPowerFetcher
from .worldpop import WorldPopFetcher

logger = logging.getLogger("sindio.ingestion")

# All registered fetchers
FETCHERS = [
    KenyaOpenDataFetcher,
    NairobiMetropolitanFetcher,
    KenyaPowerFetcher,
    WorldPopFetcher,
]


def run_all(db_url: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Run every fetcher once and return aggregate statistics.

    Args:
        db_url: PostgreSQL connection string (defaults to env var)
        force: if True, ignore cached hashes / idempotency checks

    Returns:
        {
            "total_fetchers": int,
            "success": int,
            "partial": int,
            "failed": int,
            "total_records": int,
            "details": {fetcher_name: {"status": str, "records": int}},
        }
    """
    results: Dict[str, Any] = {
        "total_fetchers": len(FETCHERS),
        "success": 0,
        "partial": 0,
        "failed": 0,
        "total_records": 0,
        "details": {},
    }

    for cls in FETCHERS:
        fetcher = cls(db_url=db_url)
        result = fetcher.run()

        results["details"][result.fetcher_name] = {
            "status": result.status,
            "records": len(result.records),
            "duration_ms": round(result.duration_ms, 1),
        }

        results["total_records"] += len(result.records)
        if result.status == "success":
            results["success"] += 1
        elif result.status == "partial":
            results["partial"] += 1
        else:
            results["failed"] += 1

    logger.info(
        "[Runner] Complete: %d success, %d partial, %d failed — %d total records",
        results["success"], results["partial"], results["failed"], results["total_records"]
    )
    return results


def run_single(fetcher_name: str, db_url: Optional[str] = None) -> Optional[FetcherResult]:
    """Run one fetcher by its source_name."""
    for cls in FETCHERS:
        if cls.source_name.lower() == fetcher_name.lower():
            fetcher = cls(db_url=db_url)
            return fetcher.run()
    logger.warning("[Runner] No fetcher named '%s' found", fetcher_name)
    return None


def list_fetchers() -> List[Dict[str, str]]:
    """Return metadata about all registered fetchers."""
    return [
        {
            "name": cls.source_name,
            "infra_type": cls.infrastructure_type,
            "class": cls.__name__,
        }
        for cls in FETCHERS
    ]
