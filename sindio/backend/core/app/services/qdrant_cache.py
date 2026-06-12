"""
Qdrant client wrapper for Sindio inference caching.

Collection: sindio_inference_cache  |  Vector dims: 1024
Stores model latent embeddings + stress outputs with metadata.

Filter patterns:
  - Temporal:  timestamp >= now - 30d
  - Freshness:  timestamp >= now - 6h  (cache-hit threshold)
  - Spatial:    lat/lon bounding-box proximity
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv

from .retry_utils import retry_external

load_dotenv()

logger = logging.getLogger("sindio.qdrant")

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_CACHE", "sindio_inference_cache")
VECTOR_DIM = 1024
DISTANCE_METRIC = "Cosine"
CACHE_FRESHNESS_HOURS = 6
RETRIEVAL_WINDOW_DAYS = 30
RETRIEVAL_TOP_K = 10


class QdrantCacheClient:
    """Thin wrapper around Qdrant for RAG-style inference caching."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection: str = COLLECTION_NAME,
        vector_dim: int = VECTOR_DIM,
        prefer_grpc: bool = False,
    ):
        self.url = url or os.getenv("QDRANT_HOST", "http://localhost:6333")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY", "")
        self.collection = collection
        self.vector_dim = vector_dim

        self._client: Any = None
        self._async_client: Any = None

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key or None,
                prefer_grpc=False,
                timeout=30,
            )
        return self._client

    @property
    def async_client(self):
        if self._async_client is None:
            from qdrant_client import AsyncQdrantClient

            self._async_client = AsyncQdrantClient(
                url=self.url,
                api_key=self.api_key or None,
                prefer_grpc=False,
                timeout=30,
            )
        return self._async_client

    def ensure_collection(self) -> None:
        from qdrant_client.http.models import Distance, VectorParams

        collections = [
            c.name
            for c in self.client.get_collections().collections
        ]
        if self.collection not in collections:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.vector_dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection '%s' (dim=%d)", self.collection, self.vector_dim)
        else:
            logger.debug("Collection '%s' already exists.", self.collection)

    # ── Upsert ────────────────────────────────────────────

    def store_inference(
        self,
        cell_id: str,
        lat: float,
        lon: float,
        timestamp: datetime,
        embedding: np.ndarray,
        stress_power: float,
        stress_water: float,
        stress_road: float,
        breach_prob: float,
        ttl_days: int = 31,
    ) -> str:
        """Store a single inference result in Qdrant.

        Returns the Qdrant point ID.
        """
        from qdrant_client.http.models import PointStruct
        import uuid

        point_id = str(uuid.uuid4())
        self.ensure_collection()

        point = PointStruct(
            id=point_id,
            vector=embedding.tolist(),
            payload={
                "cell_id": cell_id,
                "lat": lat,
                "lon": lon,
                "timestamp": timestamp.isoformat(),
                "stress_power": float(stress_power),
                "stress_water": float(stress_water),
                "stress_road": float(stress_road),
                "breach_prob": float(breach_prob),
                "source": "model_inference",
            },
        )

        self.client.upsert(
            collection_name=self.collection,
            points=[point],
        )
        return point_id

    def store_batch(
        self, inferences: List[Dict[str, Any]]
    ) -> List[str]:
        """Batch upsert multiple inference results."""
        from qdrant_client.http.models import PointStruct
        import uuid

        self.ensure_collection()
        points = []
        ids = []

        for inf in inferences:
            pid = str(uuid.uuid4())
            ids.append(pid)
            points.append(
                PointStruct(
                    id=pid,
                    vector=inf["embedding"].tolist(),
                    payload={
                        "cell_id": inf["cell_id"],
                        "lat": float(inf["lat"]),
                        "lon": float(inf["lon"]),
                        "timestamp": (
                            inf["timestamp"].isoformat()
                            if isinstance(inf["timestamp"], datetime)
                            else inf["timestamp"]
                        ),
                        "stress_power": float(inf["stress_power"]),
                        "stress_water": float(inf["stress_water"]),
                        "stress_road": float(inf["stress_road"]),
                        "breach_prob": float(inf.get("breach_prob", 0.0)),
                        "source": inf.get("source", "model_inference"),
                    },
                )
            )

        self.client.upsert(
            collection_name=self.collection,
            points=points,
        )
        logger.info("Batch-stored %d inference results in Qdrant", len(inferences))
        return ids

    # ── Query ─────────────────────────────────────────────

    @retry_external(retries=3, backoff_base=1.0, label="qdrant_find_similar")
    def find_similar_cells(
        self,
        embedding: np.ndarray,
        lat: float,
        lon: float,
        top_k: int = RETRIEVAL_TOP_K,
        max_age_days: int = RETRIEVAL_WINDOW_DAYS,
    ) -> List[Dict[str, Any]]:
        """Find the top-k most similar cells within a spatial + temporal window."""
        from qdrant_client.http.models import (
            FieldCondition,
            Filter,
            MatchAny,
            Range,
        )

        self.ensure_collection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

        search_result = self.client.search(
            collection_name=self.collection,
            query_vector=embedding.tolist(),
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="timestamp",
                        range=Range(gte=cutoff),
                    ),
                ]
            ),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        results = []
        for hit in search_result:
            payload = hit.payload or {}
            results.append({
                "score": hit.score,
                **payload,
            })
        return results

    @retry_external(retries=3, backoff_base=1.0, label="qdrant_cache_hit")
    def check_cache_hit(
        self,
        embedding: np.ndarray,
        lat: float,
        lon: float,
        similarity_threshold: float = 0.92,
        freshness_hours: int = CACHE_FRESHNESS_HOURS,
    ) -> Optional[Dict[str, Any]]:
        """Check if a fresh (<6h) cached result exists for a nearly identical cell.

        Returns cached inference payload if found, else None.
        """
        from qdrant_client.http.models import FieldCondition, Filter, Range

        self.ensure_collection()
        freshness_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
        ).isoformat()

        search_result = self.client.search(
            collection_name=self.collection,
            query_vector=embedding.tolist(),
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="timestamp",
                        range=Range(gte=freshness_cutoff),
                    ),
                ]
            ),
            limit=3,
            score_threshold=similarity_threshold,
            with_payload=True,
            with_vectors=False,
        )

        if search_result:
            hit = search_result[0]
            score = hit.score
            payload = hit.payload or {}
            logger.info(
                "Cache HIT (score=%.4f, cell=%s, ts=%s)",
                score, payload.get("cell_id", "?"), payload.get("timestamp", "?"),
            )
            return {**payload, "cache_score": score, "cache_source": "qdrant_vector_similarity"}
        return None

    def get_historical_patterns(
        self,
        embedding: np.ndarray,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve similar historical patterns for edge-case augmentation.

        Used when a cell has no prior data (e.g., new development).
        Returns sorted list of {cell_id, lat, lon, timestamp, stress_*, breach_prob}.
        """
        return self.find_similar_cells(
            embedding=embedding,
            lat=0.0,
            lon=0.0,
            top_k=top_k,
            max_age_days=365,  # Full year for pattern matching
        )

    # ── Maintenance ───────────────────────────────────────

    def expire_old_entries(self, older_than_days: int = 31) -> int:
        """Delete entries older than `older_than_days`. Returns count deleted."""
        from qdrant_client.http.models import FieldCondition, Filter, Range

        self.ensure_collection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()

        result = self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="timestamp",
                        range=Range(lt=cutoff),
                    ),
                ]
            ),
        )
        deleted = result.status == "completed"
        logger.info("Expired entries older than %d days: %s", older_than_days, "ok" if deleted else "failed")
        return int(deleted)

    def collection_stats(self) -> Dict[str, Any]:
        self.ensure_collection()
        info = self.client.get_collection(self.collection)
        return {
            "name": self.collection,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": str(info.status),
        }
