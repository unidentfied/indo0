"""
Hybrid Document Retriever
==========================

Fuses vector, spatial, and temporal signals with Reciprocal Rank Fusion (k=60)
then reranks the top candidates with a cross-encoder.

Entry point::

    results = hybrid_search(
        query="power grid overload Kilimani",
        bbox=shapely.Polygon([(36.7, -1.35), (36.9, -1.35), (36.9, -1.20), (36.7, -1.20)]),
        time_range=(date(2020, 1, 1), date(2026, 1, 1)),
        infrastructure_type="power",
    )
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sindio.retriever")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM = 1024
QDRANT_COLLECTION = "nairobi_planning_docs"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RRF_K = 60
VECTOR_LIMIT = 20
RERANK_TOP_K = 5

# ---------------------------------------------------------------------------
# Lazy-loaded singletons (matching project convention from rag_ingestion.py)
# ---------------------------------------------------------------------------

_embedding_model: Any = None
_cross_encoder: Any = None
_qdrant_client: Any = None


def _get_embedder() -> Any:
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    return _embedding_model


def _get_cross_encoder() -> Any:
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder: %s", RERANK_MODEL)
        _cross_encoder = CrossEncoder(RERANK_MODEL, max_length=512)
    return _cross_encoder


def _get_qdrant() -> Any:
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        host = os.getenv("QDRANT_HOST", "http://localhost:6333")
        api_key = os.getenv("QDRANT_API_KEY", "") or None
        _qdrant_client = QdrantClient(url=host, api_key=api_key, timeout=60)
    return _qdrant_client


def _get_pg_conn():
    """Return a raw connection from the SQLAlchemy pool (caller must close)."""
    from app.database import get_engine
    return get_engine().raw_connection()


# ---------------------------------------------------------------------------
# Stage 1 — Vector search (Qdrant)
# ---------------------------------------------------------------------------

def _vector_search(query: str, limit: int = VECTOR_LIMIT) -> List[Dict[str, Any]]:
    """Encode the query and retrieve top-k results from Qdrant."""
    embedder = _get_embedder()
    client = _get_qdrant()

    query_embedding = embedder.encode(
        query,
        normalize_embeddings=True,
    ).tolist()

    hits = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=query_embedding,
        limit=limit,
        with_payload=True,
    )

    results: List[Dict[str, Any]] = []
    for i, hit in enumerate(hits):
        payload = hit.payload or {}
        results.append({
            "rank": i + 1,
            "score": hit.score,
            "source": "vector",
            "id": hit.id,
            "text": payload.get("chunk_text", ""),
            "source_file": payload.get("source_file", ""),
            "page_num": payload.get("page_num"),
            "wards": payload.get("wards", []),
            "infrastructure_type": payload.get("infrastructure_type"),
            "year": payload.get("year"),
        })
    logger.info("Vector search: %d results (top score=%.4f)", len(results), results[0]["score"] if results else 0)
    return results


# ---------------------------------------------------------------------------
# Stage 2 — Spatial filter (PostGIS)
# ---------------------------------------------------------------------------

def _spatial_search(
    bbox_polygon,
    infrastructure_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query PostGIS for infrastructure alerts within the bounding polygon,
    then cross-reference with document_chunks via ward name.

    The bbox is a ``shapely.geometry.Polygon`` in EPSG:4326.
    Returns document-like result dicts for RRF fusion.
    """
    from shapely import wkt as shapely_wkt

    try:
        wkt_poly = bbox_polygon.wkt
    except AttributeError:
        logger.warning("bbox is not a shapely geometry — skipping spatial search")
        return []

    conn = _get_pg_conn()
    results: List[Dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            # 1. Find infrastructure nodes within the bbox
            cur.execute(
                """
                SELECT DISTINCT n.node_name, n.system_type, n.status,
                       ST_AsText(n.location) AS loc_wkt,
                       ST_Distance(n.location, ST_GeogFromText(%s)) AS proximity_m
                FROM infrastructure_nodes n
                WHERE ST_Within(n.location::geometry, ST_GeomFromText(%s, 4326))
                   OR ST_DWithin(n.location, ST_GeogFromText(%s), 5000)
                ORDER BY proximity_m
                LIMIT 50
                """,
                (wkt_poly, wkt_poly, wkt_poly),
            )
            node_rows = cur.fetchall()

            # 2. Find alerts within the bbox for ward context
            cur.execute(
                """
                SELECT DISTINCT a.title, a.level, a.category,
                       ST_AsText(a.location) AS loc_wkt,
                       a.created_at
                FROM alerts a
                WHERE ST_Within(a.location::geometry, ST_GeomFromText(%s, 4326))
                   OR ST_DWithin(a.location, ST_GeogFromText(%s), 5000)
                ORDER BY a.created_at DESC
                LIMIT 50
                """,
                (wkt_poly, wkt_poly),
            )
            alert_rows = cur.fetchall()

            # 3. Extract ward names from spatial hits to find matching document chunks
            ward_set: set = set()
            for row in node_rows:
                loc_wkt = row[2]
                if loc_wkt:
                    try:
                        point = shapely_wkt.loads(loc_wkt)
                        ward_set.add(_point_to_ward(point.y, point.x))
                    except Exception:
                        pass

            for row in alert_rows:
                loc_wkt = row[2]
                if loc_wkt:
                    try:
                        point = shapely_wkt.loads(loc_wkt)
                        ward_set.add(_point_to_ward(point.y, point.x))
                    except Exception:
                        pass

            ward_list = list(ward_set)
            logger.debug("Spatial search: %d nodes, %d alerts → %d wards",
                         len(node_rows), len(alert_rows), len(ward_list))

            # 4. Query document_chunks for any matching wards via PostgreSQL
            if ward_list:
                cur.execute(
                    """
                    SELECT id, source_file, page_num, chunk_text,
                           wards_mentioned, infrastructure_type, document_year
                    FROM document_chunks
                    WHERE wards_mentioned && %s::text[]
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (ward_list,),
                )
                pg_rows = cur.fetchall()
                for i, row in enumerate(pg_rows):
                    results.append({
                        "rank": i + 1,
                        "score": 0.6,  # Spatially-relevant baseline score
                        "source": "spatial",
                        "id": str(row[0]),
                        "text": row[3] or "",
                        "source_file": row[1] or "",
                        "page_num": row[2],
                        "wards": row[4] or [],
                        "infrastructure_type": row[5],
                        "year": row[6],
                    })
    except Exception as exc:
        logger.warning("Spatial search failed: %s", exc)
    finally:
        conn.close()

    logger.info("Spatial search: %d document chunks matched", len(results))
    return results


def _point_to_ward(lat: float, lng: float) -> str:
    """Map a lat/lon point to the nearest known Nairobi ward (simple proximity)."""
    wards_centroids = [
        ("Kilimani", -1.2900, 36.7850),
        ("Upper Hill", -1.2975, 36.8122),
        ("CBD", -1.2833, 36.8219),
        ("Westlands", -1.2670, 36.8090),
        ("Karen", -1.3800, 36.7200),
        ("Eastleigh", -1.2700, 36.8580),
        ("Langata", -1.3700, 36.7700),
        ("Parklands", -1.2600, 36.8000),
        ("Industrial Area", -1.3200, 36.8500),
        ("Ngong Road", -1.3000, 36.7900),
    ]
    best_ward, best_dist = "CBD", float("inf")
    for ward, wlat, wlng in wards_centroids:
        dist = ((lat - wlat) ** 2 + (lng - wlng) ** 2) ** 0.5
        if dist < best_dist:
            best_dist, best_ward = dist, ward
    return best_ward


# ---------------------------------------------------------------------------
# Stage 3 — Temporal filter
# ---------------------------------------------------------------------------

def _temporal_filter(
    results: List[Dict[str, Any]],
    time_range: Tuple[date, date],
) -> List[Dict[str, Any]]:
    """Keep only results whose ``year`` falls within ``time_range``."""
    start, end = time_range
    filtered: List[Dict[str, Any]] = []
    for r in results:
        yr = r.get("year")
        if yr is None:
            filtered.append(r)  # Keep results without year (don't penalize)
        elif start.year <= int(yr) <= end.year:
            filtered.append(r)
        else:
            logger.debug("Temporal filter dropped: year=%s (range %s–%s)", yr, start.year, end.year)
    logger.info("Temporal filter: %d → %d results", len(results), len(filtered))
    return filtered


# ---------------------------------------------------------------------------
# Stage 4 — Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

def _rrf(
    result_sets: List[List[Dict[str, Any]]],
    k: int = RRF_K,
) -> List[Dict[str, Any]]:
    """Fuse multiple ranked result lists into one via Reciprocal Rank Fusion.

    RRF score = Σ 1 / (k + rank_i)  for each list where the document appears.

    Args:
        result_sets: One list per retrieval source, each sorted by descending relevance.
        k: Smoothing parameter (default 60 as per TREC best-practice).

    Returns:
        Single fused list sorted by descending RRF score.
    """
    # Accumulate RRF scores by document ID
    scores: Dict[str, float] = {}
    docs: Dict[str, Dict[str, Any]] = {}

    for result_list in result_sets:
        for rank, doc in enumerate(result_list, start=1):
            doc_id = doc.get("id", str(hash(doc.get("text", "")[:200])))
            rrf_score = 1.0 / (k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in docs:
                docs[doc_id] = {**doc}

    # Build fused list
    fused = sorted(
        [
            {**docs[doc_id], "rrf_score": round(sc, 6), "id": doc_id}
            for doc_id, sc in scores.items()
        ],
        key=lambda d: d["rrf_score"],
        reverse=True,
    )

    logger.info("RRF fusion: %d result sets → %d unique docs (k=%d)",
                len(result_sets), len(fused), k)
    return fused


# ---------------------------------------------------------------------------
# Stage 5 — Cross-encoder rerank
# ---------------------------------------------------------------------------

def _rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int = RERANK_TOP_K,
) -> List[Dict[str, Any]]:
    """Re-score the top fused candidates with a cross-encoder.

    Uses ``cross-encoder/ms-marco-MiniLM-L-6-v2`` to produce fine-grained
    relevance scores, then returns the top_k.
    """
    if not candidates:
        return []

    model = _get_cross_encoder()
    texts = [doc.get("text", "")[:512] for doc in candidates]
    pairs = [(query, t) for t in texts]

    logger.info("Cross-encoder reranking %d candidates...", len(pairs))
    scores = model.predict(pairs, show_progress_bar=False)

    # Attach scores and sort
    for doc, score in zip(candidates, scores):
        doc["rerank_score"] = round(float(score), 4)

    ranked = sorted(candidates, key=lambda d: d.get("rerank_score", 0), reverse=True)
    top = ranked[:top_k]

    logger.info("Cross-encoder: top-5 scores = %s",
                [d.get("rerank_score") for d in top])
    return top


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hybrid_search(
    query: str,
    bbox: Optional[Any] = None,          # shapely.geometry.Polygon or None
    time_range: Optional[Tuple[date, date]] = None,
    infrastructure_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hybrid document retrieval fusing vector, spatial, and temporal signals.

    Pipeline:
        1. Vector search (Qdrant) → top 20
        2. Spatial filter (PostGIS) → documents intersecting bbox
        3. Temporal filter → subset within ``time_range``
        4. Reciprocal Rank Fusion (k=60) → fused list
        5. Cross-encoder rerank (ms-marco-MiniLM-L-6-v2) → top 5

    Args:
        query: Natural language query string.
        bbox: A ``shapely.geometry.Polygon`` in EPSG:4326, or None to skip spatial.
        time_range: A ``(date, date)`` tuple, or None to skip temporal filtering.
        infrastructure_type: Optional infrastructure type filter.

    Returns:
        List of ranked document dicts with keys:
        ``id``, ``text``, ``source_file``, ``page_num``, ``wards``,
        ``infrastructure_type``, ``year``, ``score``, ``source``,
        ``rrf_score``, ``rerank_score``.
    """
    result_sets: List[List[Dict[str, Any]]] = []

    # ── Stage 1: Vector search ──────────────────────────────────
    vector_results = _vector_search(query)
    result_sets.append(vector_results)

    # ── Stage 2: Spatial filter ─────────────────────────────────
    if bbox is not None:
        spatial_results = _spatial_search(bbox, infrastructure_type)
        result_sets.append(spatial_results)

    # ── Stage 3: Temporal filter (applied to vector results) ────
    temporal_results = vector_results
    if time_range is not None:
        temporal_results = _temporal_filter(vector_results, time_range)
        # Replace the unfiltered vector set in fusion
        result_sets[0] = temporal_results

    # ── Stage 4: Reciprocal Rank Fusion ─────────────────────────
    fused = _rrf(result_sets, k=RRF_K)

    # ── Stage 5: Cross-encoder rerank ───────────────────────────
    reranked = _rerank(query, fused, top_k=RERANK_TOP_K)

    return reranked


# ---------------------------------------------------------------------------
# Convenience: keyword-only fallback via PostgreSQL full-text search
# ---------------------------------------------------------------------------

def keyword_search(
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """PostgreSQL full-text search fallback when Qdrant is unavailable."""
    conn = _get_pg_conn()
    results: List[Dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            tsquery = " & ".join(
                w for w in query.split()
                if len(w) > 2 and w.lower() not in {"the", "and", "for", "with", "that", "this", "from"}
            )
            cur.execute(
                """
                SELECT id, source_file, page_num, chunk_text,
                       wards_mentioned, infrastructure_type, document_year,
                       ts_rank(to_tsvector('english', chunk_text), to_tsquery('english', %s)) AS rank
                FROM document_chunks
                WHERE to_tsvector('english', chunk_text) @@ to_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (tsquery, tsquery, limit),
            )
            for row in cur.fetchall():
                results.append({
                    "id": str(row[0]),
                    "source_file": row[1] or "",
                    "page_num": row[2],
                    "text": row[3] or "",
                    "wards": row[4] or [],
                    "infrastructure_type": row[5],
                    "year": row[6],
                    "ts_rank": float(row[7]) if row[7] else 0,
                    "source": "keyword",
                })
    except Exception as exc:
        logger.error("Keyword search failed: %s", exc)
    finally:
        conn.close()
    return results
