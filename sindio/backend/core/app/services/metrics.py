# backend/core/app/services/metrics.py
"""Prometheus metrics definitions for Sindio ingestion pipeline.
Provides counters and histograms used across the service layer.
"""

from prometheus_client import Counter, Histogram, Gauge

# Histogram for total ingestion duration per asset type
INGEST_DURATION = Histogram(
    "sindio_ingest_duration_seconds",
    "Duration of ingestion per asset type",
    ["asset_type"],
)

# Counter for rows processed (before upsert)
ROWS_PROCESSED = Counter(
    "sindio_rows_processed_total",
    "Number of rows processed for ingestion",
    ["asset_type"],
)

# Counter for successful upserts
UPSERT_SUCCESS = Counter(
    "sindio_upserts_success_total",
    "Successful upsert operations",
    ["asset_type"],
)

# Counter for failed upserts (e.g., DB errors)
UPSERT_FAILURE = Counter(
    "sindio_upserts_failed_total",
    "Failed upsert operations",
    ["asset_type"],
)

# Gauge for active parallel workers during ingestion
PARALLEL_WORKERS_ACTIVE = Gauge(
    "parallel_workers_active",
    "Number of active parallel ingestion workers",
    ["asset_type"],
)
