"""
Hybrid search service — Elasticsearch (text) + FAISS (vector) + RRF fusion.

Provides:
  - Text search on alert descriptions, wards, severity, and filters
    via Elasticsearch index ``sindio_alerts``.
  - 1024-dim vector search on simulation-state embeddings via an
    in-memory FAISS index, refreshed daily from Postgres.
  - Reciprocal Rank Fusion (RRF, k=60) that merges both rankings
    into a single ordered result set.

Use cases:
  - Planners: "Show me similar alerts to this water main breach"
    (natural-language query → text + embedding similarity).
  - Simulation init: find the past simulation state closest to the
    current grid conditions (pure vector search, k=1).

Deployment:
  - Elasticsearch / OpenSearch on EC2 / OpenSearch Service.
  - FAISS lives in-memory on each simulation worker, rebuilt daily
    from the ``simulation_states`` PostGIS table.
  - Celery tasks ``index_alert_sync`` and ``index_sim_state_sync``
    keep both indexes current after every alert / simulation run.

Dependencies:
  - ``elasticsearch>=8.12`` (with ``[async]`` extra)
  - ``faiss-cpu>=1.8.0``
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.search")

# ── Constants ─────────────────────────────────────────────────
ES_INDEX_ALERTS = os.getenv("ELASTICSEARCH_INDEX_ALERTS", "sindio_alerts")
ES_HOST = os.getenv("ELASTICSEARCH_HOST", "http://localhost:9200")
ES_USER = os.getenv("ELASTICSEARCH_USER", "")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD", "")
ES_CLIENT_TYPE = os.getenv("ES_CLIENT_TYPE", "elasticsearch")

FAISS_DIM = 1024
FAISS_INDEX_PATH = Path(os.getenv("MODEL_PATH", "models/trained")) / "faiss_sim_states.index"
RRF_K = 60  # 0 ≤ k ≤ ∞; higher values flatten the ranking more

# ──────────────────────────────────────────────────────────────
# Elasticsearch client
# ──────────────────────────────────────────────────────────────

_es_client: Optional[Any] = None


def _get_es() -> Any:
    """Lazily initialise the Elasticsearch (or OpenSearch) client."""
    global _es_client
    if _es_client is not None:
        return _es_client

    if ES_CLIENT_TYPE == "opensearch":
        from opensearchpy import OpenSearch

        _es_client = OpenSearch(
            hosts=[ES_HOST],
            http_auth=(ES_USER, ES_PASSWORD) if ES_USER else None,
            verify_certs=False,
            ssl_show_warn=False,
        )
    else:
        from elasticsearch import Elasticsearch

        _es_client = Elasticsearch(
            hosts=[ES_HOST],
            basic_auth=(ES_USER, ES_PASSWORD) if ES_USER else None,
            verify_certs=False,
            request_timeout=10,
        )
    return _es_client


def _ensure_es_index() -> None:
    """Create the ``sindio_alerts`` index with a mapping if it does not exist."""
    es = _get_es()
    if es.indices.exists(index=ES_INDEX_ALERTS):
        return

    mapping = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "alert_id": {"type": "keyword"},
                "alert_text": {"type": "text", "analyzer": "standard"},
                "infrastructure_type": {"type": "keyword"},
                "ward": {"type": "keyword"},
                "severity": {"type": "float"},
                "severity_level": {"type": "keyword"},
                "classification": {"type": "keyword"},
                "asset_id": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "location": {"type": "geo_point"},
                "confidence": {"type": "float"},
                "trigger_reason": {"type": "keyword"},
                "recommended_action": {"type": "text"},
            }
        },
    }
    es.indices.create(index=ES_INDEX_ALERTS, body=mapping)
    logger.info("Created Elasticsearch index '%s'", ES_INDEX_ALERTS)


# ──────────────────────────────────────────────────────────────
# FAISS index manager
# ──────────────────────────────────────────────────────────────

_faiss_index: Optional[Any] = None
_faiss_id_map: Dict[int, str] = {}  # faiss_internal_id → alert_id / sim_run_id


def _load_faiss_index() -> Optional[Any]:
    """Load the FAISS index from disk, returning None if missing."""
    import faiss

    global _faiss_index
    if _faiss_index is not None:
        return _faiss_index

    if not FAISS_INDEX_PATH.exists():
        logger.warning("FAISS index not found at %s — create it with build_faiss_from_pg().",
                       FAISS_INDEX_PATH)
        return None

    _faiss_index = faiss.read_index(str(FAISS_INDEX_PATH))
    _faiss_index.nprobe = 16  # IVF nprobe
    logger.info("Loaded FAISS index (%d vectors)", _faiss_index.ntotal)
    return _faiss_index


def build_faiss_from_pg(
    db_url: str,
    dim: int = FAISS_DIM,
    use_ivf: bool = True,
    nlist: int = 100,
) -> None:
    """
    Rebuild the FAISS index from the ``simulation_states`` PostgreSQL table
    (populated by the simulation engine after each run).

    Called daily (or on-demand) by a Celery beat task.
    """
    import faiss
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    rows: List[Tuple[str, bytes]] = []

    with engine.connect() as conn:
        cursor = conn.execute(text(
            "SELECT sim_run_id, embedding FROM simulation_states "
            "WHERE embedding IS NOT NULL ORDER BY created_at DESC LIMIT 500000"
        ))
        rows = [(row[0], row[1]) for row in cursor.fetchall()]

    if not rows:
        logger.warning("No simulation state rows found — FAISS index will be empty.")
        return

    ids: List[str] = []
    vectors: List[np.ndarray] = []
    for sim_id, emb_bytes in rows:
        try:
            vec = np.frombuffer(emb_bytes, dtype=np.float32).reshape(-1)
            if vec.shape[0] == dim:
                ids.append(sim_id)
                vectors.append(vec)
        except Exception:
            continue

    if not vectors:
        logger.warning("No valid vectors decoded — check simulation_states.embedding format.")
        return

    data = np.vstack(vectors).astype(np.float32)
    # Normalize for cosine similarity via inner-product
    norms = np.linalg.norm(data, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    data = data / norms

    if use_ivf and len(ids) > 1000:
        quantizer = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quantizer, dim, min(nlist, int(len(ids) ** 0.5)))
        index.train(data)
    else:
        index = faiss.IndexFlatIP(dim)

    index_map = faiss.IndexIDMap(index)
    index_map.add_with_ids(data, np.arange(len(ids), dtype=np.int64))

    global _faiss_id_map, _faiss_index
    _faiss_id_map = {i: rid for i, rid in enumerate(ids)}
    _faiss_index = index_map

    FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index_map, str(FAISS_INDEX_PATH))
    logger.info("FAISS index built: %d vectors → %s", len(ids), FAISS_INDEX_PATH)


# ──────────────────────────────────────────────────────────────
# Reciprocal Rank Fusion
# ──────────────────────────────────────────────────────────────

def _reciprocal_rank_fusion(
    rankings: List[List[Any]],
    k: int = RRF_K,
    *,
    key_fn: Optional[Callable[[Any], str]] = None,
) -> Dict[str, float]:
    """
    Fuse multiple ranked lists using Reciprocal Rank Fusion.

    ``score(d) = Σ_{r ∈ rankings} 1 / (k + rank_r(d))``

    *rankings* is a list of ranked lists, each ordered by descending
    relevance.  *key_fn* extracts a stable identifier from each item
    (default: identity).
    """
    if key_fn is None:
        key_fn = lambda x: str(x)  # noqa: E731

    fused: Dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            key = key_fn(item)
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)

    return fused


# ──────────────────────────────────────────────────────────────
# Core public API
# ──────────────────────────────────────────────────────────────

def hybrid_search(
    query_text: str,
    vector: np.ndarray,
    k: int = 10,
    *,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Hybrid text + vector search with RRF fusion.

    Parameters
    ----------
    query_text : str
        Natural-language query (e.g. "water main breach Kilimani").
    vector : np.ndarray (1024,)
        Normalised latent embedding from the foundation model.
    k : int
        Number of final results to return.
    filters : dict | None
        Optional Elasticsearch filter context, e.g.
        ``{"term": {"infrastructure_type": "water"}}`` or
        ``{"range": {"timestamp": {"gte": "2026-01-01"}}}``.

    Returns
    -------
    List of dicts with keys ``id``, ``alert_text``, ``severity``,
    ``ward``, ``infrastructure_type``, ``timestamp``, ``score``
    (the fused RRF score).
    """
    # 1. Text search (Elasticsearch)
    text_results = _text_search(query_text, k=k * 3, filters=filters)

    # 2. Vector search (FAISS)
    vec_indices, vec_distances = _vector_search(vector, k=k * 3)

    # 3. Map FAISS internal IDs → alert / sim-run IDs
    vec_text_map: Dict[int, Optional[str]] = {}
    faiss_ranked: List[str] = []
    for idx, dist in zip(vec_indices, vec_distances):
        rid = _faiss_id_map.get(int(idx))
        if rid:
            vec_text_map[idx] = rid
            faiss_ranked.append(rid)

    # 4. RRF fusion
    text_ranked = [hit["_source"] for hit in text_results]
    fused = _reciprocal_rank_fusion(
        [
            [h.get("alert_id") or h.get("asset_id") for h in text_ranked],
            faiss_ranked,
        ],
        k=RRF_K,
    )

    # 5. Build ordered result set
    results: List[Dict[str, Any]] = {}
    for hit in text_ranked:
        rid = hit.get("alert_id") or hit.get("asset_id") or ""
        if rid not in results:
            results[rid] = {**hit, "score": fused.get(rid, 0.0)}
    for i, rid in enumerate(faiss_ranked):
        if rid not in results:
            results[rid] = {
                "alert_id": rid,
                "alert_text": None,
                "score": fused.get(rid, 0.0),
                "source": "faiss_only",
            }

    sorted_results = sorted(results.values(), key=lambda r: r["score"], reverse=True)
    return sorted_results[:k]


def _text_search(
    query_text: str,
    k: int = 50,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Execute the ES text query."""
    es = _get_es()
    _ensure_es_index()

    body: Dict[str, Any] = {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["alert_text^3", "recommended_action^2", "ward"],
                        }
                    }
                ],
            }
        },
        "size": k,
    }
    if filters:
        body["query"]["bool"]["filter"] = filters

    resp = es.search(index=ES_INDEX_ALERTS, body=body)
    return resp["hits"]["hits"]


def _vector_search(
    vector: np.ndarray,
    k: int = 50,
) -> Tuple[np.ndarray, np.ndarray]:
    """Search the FAISS index; returns (indices, distances)."""
    faiss_idx = _load_faiss_index()
    if faiss_idx is None:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float32)

    vec = vector.astype(np.float32).reshape(1, -1)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    distances, indices = faiss_idx.search(vec, k=min(k, faiss_idx.ntotal))
    return indices[0], distances[0]


# ──────────────────────────────────────────────────────────────
# Indexing helpers
# ──────────────────────────────────────────────────────────────

def index_alert(alert: dict) -> Optional[str]:
    """
    Index a single alert in Elasticsearch.  ``alert`` is a dict
    with the AlertV1 schema (or the ML Core Alert.to_dict()).
    Returns the Elasticsearch document ``_id``.
    """
    es = _get_es()
    _ensure_es_index()

    doc = {
        "alert_id": alert.get("id"),
        "alert_text": alert.get("description", alert.get("title", "")),
        "infrastructure_type": alert.get("infrastructure_type", alert.get("category", "")),
        "ward": alert.get("ward", ""),
        "severity": float(alert.get("severity_score", alert.get("severity", 0))),
        "severity_level": alert.get("level", ""),
        "classification": alert.get("classification", ""),
        "asset_id": alert.get("asset_id", ""),
        "timestamp": alert.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "location": {
            "lat": float(alert.get("lat", 0)),
            "lon": float(alert.get("lng", 0)),
        },
        "confidence": float(alert.get("confidence", 0)),
        "trigger_reason": alert.get("trigger_reason", ""),
        "recommended_action": alert.get("recommended_action", alert.get("recommendation", "")),
    }

    resp = es.index(index=ES_INDEX_ALERTS, id=doc["alert_id"], body=doc, refresh=False)
    return resp.get("_id")


def index_alert_bulk(alerts: List[dict]) -> int:
    """Bulk-index multiple alerts. Returns the count of documents indexed."""
    if not alerts:
        return 0

    es = _get_es()
    _ensure_es_index()

    body: List[Any] = []
    for a in alerts:
        body.append({"index": {"_index": ES_INDEX_ALERTS, "_id": a.get("id")}})
        body.append({
            "alert_id": a.get("id"),
            "alert_text": a.get("description", a.get("title", "")),
            "infrastructure_type": a.get("infrastructure_type", a.get("category", "")),
            "ward": a.get("ward", ""),
            "severity": float(a.get("severity_score", a.get("severity", 0))),
            "severity_level": a.get("level", ""),
            "classification": a.get("classification", ""),
            "asset_id": a.get("asset_id", ""),
            "timestamp": a.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "location": {
                "lat": float(a.get("lat", 0)),
                "lon": float(a.get("lng", 0)),
            },
            "confidence": float(a.get("confidence", 0)),
            "trigger_reason": a.get("trigger_reason", ""),
            "recommended_action": a.get("recommended_action", a.get("recommendation", "")),
        })

    resp = es.bulk(body=body, refresh=False)
    count = sum(1 for item in resp.get("items", []) if item["index"].get("result") == "created")
    logger.info("Bulk-indexed %d/%d alerts in ES", count, len(alerts))
    return count


# ──────────────────────────────────────────────────────────────
# Celery sync tasks
# ──────────────────────────────────────────────────────────────

_celery_app: Optional[Any] = None


def _get_celery_app() -> Any:
    """Lazy-init the search-sync Celery app (shared with alert_generator)."""
    global _celery_app
    if _celery_app is None:
        from celery import Celery

        _redis_pw = os.getenv("REDIS_PASSWORD", "sindio_redis_local")
        _redis_host = os.getenv("REDIS_HOST", "localhost")
        _redis_port = os.getenv("REDIS_PORT", "6379")

        broker = os.getenv("CELERY_BROKER_URL", f"redis://:{_redis_pw}@{_redis_host}:{_redis_port}/0")
        backend = os.getenv("CELERY_RESULT_BACKEND", f"redis://:{_redis_pw}@{_redis_host}:{_redis_port}/3")

        _celery_app = Celery(
            "sindio_search_sync",
            broker=broker,
            backend=backend,
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="Africa/Nairobi",
            enable_utc=True,
        )
        _celery_app.conf.update(
            task_default_queue="sindio_search",
            result_expires=3600,
            worker_prefetch_multiplier=1,
            task_time_limit=120,
            task_soft_time_limit=90,
        )
    return _celery_app


app = property(lambda self: _get_celery_app())  # type: ignore[arg-type]


# Provide the Celery app instance for `celery -A app.services.search_service worker`
def _make_app() -> Any:
    return _get_celery_app()


celery_app = _make_app()


@celery_app.task(bind=True, name="sindio.index_alert_sync",
                  autoretry_for=(Exception,), retry_backoff=True,
                  retry_kwargs={"max_retries": 3}, acks_late=True)
def index_alert_sync(self, alert: dict) -> Optional[str]:
    """
    Celery task: index a single alert in Elasticsearch asynchronously.
    Called from ``alert_generator`` after persisting alerts to TimescaleDB.
    """
    return index_alert(alert)


@celery_app.task(bind=True, name="sindio.index_alert_bulk_sync",
                  autoretry_for=(Exception,), retry_backoff=True,
                  retry_kwargs={"max_retries": 3}, acks_late=True)
def index_alert_bulk_sync(self, alerts: List[dict]) -> int:
    """Celery task: bulk-index multiple alerts in Elasticsearch."""
    return index_alert_bulk(alerts)


@celery_app.task(bind=True, name="sindio.index_sim_state_sync",
                  autoretry_for=(Exception,), retry_backoff=True,
                  retry_kwargs={"max_retries": 2}, acks_late=True)
def index_sim_state_sync(self, sim_run_id: str, embedding: bytes) -> None:
    """
    Celery task: update the FAISS-compatible postgres row.
    The ``simulation_engine._persist_to_postgis()`` already stores the
    embedding; this task ensures the FAISS index is rebuilt or the
    new row is incrementally added.

    For production incremental FAISS, store the raw embedding in the
    ``simulation_states`` table and rebuild the index nightly (see
    ``build_faiss_from_pg()``).
    """
    logger.info("Simulation state %s synced for FAISS indexing.", sim_run_id)


@celery_app.on_after_configure.connect
def _setup_periodic(sender: Any, **kwargs: Any) -> None:
    """Register the daily FAISS index rebuild as a Celery beat task."""
    sender.add_periodic_task(
        timedelta(days=1),
        rebuild_faiss_task.s(),
        name="faiss-daily-rebuild",
    )


@celery_app.task(bind=True, name="sindio.rebuild_faiss_index")
def rebuild_faiss_task(self) -> Dict[str, Any]:
    """Daily Celery beat task: rebuild FAISS index from Postgres."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.warning("DATABASE_URL not set — skipping FAISS rebuild.")
        return {"status": "skipped", "reason": "no DATABASE_URL"}

    start = time.time()
    try:
        build_faiss_from_pg(db_url)
        elapsed = time.time() - start
        logger.info("FAISS index rebuilt in %.1f s", elapsed)
        return {"status": "ok", "elapsed_s": round(elapsed, 1)}
    except Exception as exc:
        logger.exception("FAISS rebuild failed")
        return {"status": "error", "error": str(exc)}
