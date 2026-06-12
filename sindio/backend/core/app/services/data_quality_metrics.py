"""
Sindio — Data Quality Prometheus Metrics
=========================================

Exposes three core gauges per infrastructure type:
  - data_quality_real_data_ratio    — fraction of assets served from fresh real data (0–1)
  - data_quality_mock_fallback_ratio — fraction of requests served from mock/fallback (0–1)
  - data_quality_model_confidence   — average model confidence score (0–1)

Plus counters for absolute fallback events:
  - data_quality_fallback_total{infrastructure_type,source} — cumulative fallback count

Usage:
    from app.services.data_quality_metrics import DataQualityMetrics

    metrics = DataQualityMetrics()
    metrics.set_real_data_ratio("power", 0.85)
    metrics.set_mock_fallback_ratio("power", 0.15)
    metrics.set_model_confidence("power", 0.92)
    metrics.record_fallback("water", "kafka_unreachable")

    # In FastAPI:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    @app.get("/metrics")
    def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
"""

from __future__ import annotations

import logging
from typing import Optional

from prometheus_client import Counter, Gauge, CollectorRegistry

logger = logging.getLogger("sindio.data_quality")

# Shared registry so all metrics are collected together
registry = CollectorRegistry()

# ── Gauges (current state, updated on every data fetch) ──────

DATA_QUALITY_REAL_RATIO = Gauge(
    "data_quality_real_data_ratio",
    "Fraction of assets served from fresh real data (0–1). "
    "1.0 means all assets have real data; 0.0 means all are mock.",
    ["infrastructure_type"],
    registry=registry,
)

DATA_QUALITY_MOCK_RATIO = Gauge(
    "data_quality_mock_fallback_ratio",
    "Fraction of requests served from mock/fallback data (0–1). "
    "Complement of real_data_ratio; alerts when > 0.10 for > 1h.",
    ["infrastructure_type"],
    registry=registry,
)

DATA_QUALITY_MODEL_CONFIDENCE = Gauge(
    "data_quality_model_confidence",
    "Average model confidence score for the last inference batch (0–1).",
    ["infrastructure_type"],
    registry=registry,
)

# ── Counters (cumulative fallback events) ────────────────────

DATA_QUALITY_FALLBACK_TOTAL = Counter(
    "data_quality_fallback_total",
    "Total number of fallback/mock data events. "
    "Labelled by infrastructure type and fallback source.",
    ["infrastructure_type", "source"],
    registry=registry,
)

DATA_QUALITY_REAL_FETCH_TOTAL = Counter(
    "data_quality_real_fetch_total",
    "Total number of successful real data fetches from external sources.",
    ["infrastructure_type", "source"],
    registry=registry,
)


class DataQualityMetrics:
    """Convenience wrapper for recording data quality metrics."""

    def set_real_data_ratio(self, infra_type: str, ratio: float) -> None:
        """Set the fraction of assets with fresh real data (0–1)."""
        DATA_QUALITY_REAL_RATIO.labels(infrastructure_type=infra_type).set(
            round(max(0.0, min(1.0, ratio)), 4)
        )

    def set_mock_fallback_ratio(self, infra_type: str, ratio: float) -> None:
        """Set the fraction of requests served from mock/fallback (0–1)."""
        DATA_QUALITY_MOCK_RATIO.labels(infrastructure_type=infra_type).set(
            round(max(0.0, min(1.0, ratio)), 4)
        )

    def set_model_confidence(self, infra_type: str, confidence: float) -> None:
        """Set the average model confidence score (0–1)."""
        DATA_QUALITY_MODEL_CONFIDENCE.labels(infrastructure_type=infra_type).set(
            round(max(0.0, min(1.0, confidence)), 4)
        )

    def record_fallback(self, infra_type: str, source: str) -> None:
        """Record a single fallback event."""
        DATA_QUALITY_FALLBACK_TOTAL.labels(
            infrastructure_type=infra_type, source=source
        ).inc()
        logger.info("Fallback recorded: infra=%s source=%s", infra_type, source)

    def record_real_fetch(self, infra_type: str, source: str) -> None:
        """Record a successful real data fetch."""
        DATA_QUALITY_REAL_FETCH_TOTAL.labels(
            infrastructure_type=infra_type, source=source
        ).inc()

    def update_ratios_from_counts(
        self,
        infra_type: str,
        real_count: int,
        mock_count: int,
    ) -> None:
        """Compute and set real/mock ratios from raw counts."""
        total = real_count + mock_count
        if total == 0:
            self.set_real_data_ratio(infra_type, 0.0)
            self.set_mock_fallback_ratio(infra_type, 1.0)
            return
        real_ratio = real_count / total
        self.set_real_data_ratio(infra_type, real_ratio)
        self.set_mock_fallback_ratio(infra_type, 1.0 - real_ratio)


# Module-level singleton for easy import
metrics = DataQualityMetrics()
