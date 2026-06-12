"""
RAG (Retrieval-Augmented Generation) inference wrapper for SindioFoundationModel.

Flow:
  1. Encode cell {lat, lon, features} → query embedding
  2. Query Qdrant for similar cells in last 30 days
  3. Cache HIT  → return cached stress/breach values
  4. Cache MISS → run model
     a. If cell is new (no history): augment model input with top-k
        similar historical patterns from Qdrant
     b. Store result embedding + metadata back into Qdrant
  5. Return inference result

Supports both synchronous and Celery-based async inference.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from app.models.sindio_foundation import SindioFoundationModel
from app.services.qdrant_cache import QdrantCacheClient

logger = logging.getLogger("sindio.rag")


@dataclass
class InferenceResult:
    cell_id: str
    lat: float
    lon: float
    timestamp: datetime
    stress_power: float
    stress_water: float
    stress_road: float
    breach_prob: float
    source: str  # "cache_hit" | "model_fresh" | "model_augmented"
    cache_score: Optional[float] = None
    similar_patterns: List[Dict[str, Any]] = field(default_factory=list)
    embedding: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class RAGInferenceEngine:
    """RAG-cached inference for SindioFoundationModel.

    Architecture:
      ┌──────────┐   query   ┌────────┐  hit?  ┌───────────┐
      │  Qdrant  │◄─────────│  Cell   │───────►│  Return    │
      │  (cache) │           │ features│         │  cached    │
      └────┬─────┘           └────────┘         └───────────┘
           │ miss
           ▼
      ┌──────────┐  augment  ┌────────┐
      │Historical│──────────►│ Model  │──► Store back in Qdrant
      │Patterns  │           └────────┘
      └──────────┘
    """

    def __init__(
        self,
        model: Optional[SindioFoundationModel] = None,
        model_path: Optional[str] = None,
        cache_client: Optional[QdrantCacheClient] = None,
        device: Optional[str] = None,
        similarity_threshold: float = 0.92,
        freshness_hours: int = 6,
        top_k_patterns: int = 5,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # Model
        if model is not None:
            self.model = model.to(self.device)
        elif model_path is not None:
            self.model = SindioFoundationModel()
            self.model.load_state_dict(
                torch.load(model_path, map_location=self.device)
            )
            self.model.to(self.device)
        else:
            raise ValueError("Either `model` or `model_path` must be provided.")
        self.model.eval()

        # Cache
        self.cache = cache_client or QdrantCacheClient()

        self.similarity_threshold = similarity_threshold
        self.freshness_hours = freshness_hours
        self.top_k_patterns = top_k_patterns

        # For generating query embeddings without running the full model
        self._latent_cache: Dict[str, np.ndarray] = {}

    @torch.no_grad()
    def _encode_cell(
        self,
        lat: float,
        lon: float,
        time_series: Optional[torch.Tensor] = None,
    ) -> np.ndarray:
        """Encode a single cell into a 1024-dim embedding for Qdrant query.

        Uses a lightweight forward pass through the encoders + fusion.
        """
        B = 1
        device = torch.device(self.device)

        # Mock satellite input (replace with actual Sentinel-2 in production)
        satellite = torch.randn(B, 10, 224, 224, device=device)

        # Mock graph (single node for one cell)
        graph_batch = {
            "node_features": torch.randn(1, 16, device=device),
            "edge_index": torch.empty(2, 0, dtype=torch.long, device=device),
            "edge_attr": torch.empty(0, 6, dtype=torch.float32, device=device),
            "node_types": torch.tensor([0], dtype=torch.long, device=device),
            "batch": torch.zeros(1, dtype=torch.long, device=device),
        }

        if time_series is None:
            # Generate a lightweight embedding from lat/lon
            # Simple lookup into a positional encoding grid
            import math
            pos_enc = torch.zeros(1, 72, 8, device=device)
            for i in range(72):
                angle = (i + 1) * 0.1 + lat * math.pi + lon * math.pi
                pos_enc[0, i, 0] = math.sin(angle)
                pos_enc[0, i, 1] = math.cos(angle)
                pos_enc[0, i, 2] = lat / 90.0
                pos_enc[0, i, 3] = lon / 180.0
            time_series = pos_enc

        else:
            time_series = time_series.to(device)

        # Run encoders only (no heads)
        vision_emb, graph_emb, temporal_emb = self.model.encode(
            satellite=satellite,
            graph_batch=graph_batch,
            time_series=time_series,
        )

        fused = self.model.fusion(vision_emb, graph_emb, temporal_emb)
        return fused.cpu().numpy().squeeze(0).astype(np.float32)

    @torch.no_grad()
    def infer_cell(
        self,
        cell_id: str,
        lat: float,
        lon: float,
        timestamp: Optional[datetime] = None,
        time_series: Optional[torch.Tensor] = None,
        force_fresh: bool = False,
    ) -> InferenceResult:
        """Run RAG-cached inference for a single cell.

        Steps:
          1. Encode cell → query embedding
          2. Check Qdrant cache for fresh similar results
          3. If cache hit → return cached
          4. If cache miss → retrieve historical patterns & run model
          5. Store result in Qdrant
          6. Return InferenceResult
        """
        ts = (timestamp or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
        query_emb = self._encode_cell(lat, lon, time_series)

        # ── Step 2: Check cache ─────────────────────────
        if not force_fresh:
            cached = self.cache.check_cache_hit(
                embedding=query_emb,
                lat=lat,
                lon=lon,
                similarity_threshold=self.similarity_threshold,
                freshness_hours=self.freshness_hours,
            )
            if cached is not None:
                return InferenceResult(
                    cell_id=cell_id,
                    lat=lat,
                    lon=lon,
                    timestamp=ts,
                    stress_power=float(cached.get("stress_power", 0.0)),
                    stress_water=float(cached.get("stress_water", 0.0)),
                    stress_road=float(cached.get("stress_road", 0.0)),
                    breach_prob=float(cached.get("breach_prob", 0.0)),
                    source="cache_hit",
                    cache_score=float(cached.get("cache_score", 0.0)),
                )

        # ── Step 4: Cache miss — run model ───────────────
        logger.info(
            "Cache MISS for cell=%s (%.5f, %.5f) — running model", cell_id, lat, lon
        )

        # Retrieve similar historical patterns for augmentation
        patterns = self.cache.get_historical_patterns(
            embedding=query_emb,
            top_k=self.top_k_patterns,
        )

        is_new_development = len(patterns) == 0

        device = torch.device(self.device)
        B = 1

        satellite = torch.randn(B, 10, 224, 224, device=device)
        graph_batch = {
            "node_features": torch.randn(1, 16, device=device),
            "edge_index": torch.empty(2, 0, dtype=torch.long, device=device),
            "edge_attr": torch.empty(0, 6, dtype=torch.float32, device=device),
            "node_types": torch.tensor([0], dtype=torch.long, device=device),
            "batch": torch.zeros(1, dtype=torch.long, device=device),
        }

        if time_series is None:
            time_series = torch.randn(B, 72, 8, device=device)
        else:
            time_series = time_series.to(device)

        # If new development: augment time_series with retrieved pattern trends
        if is_new_development and patterns:
            aug_ts = self._augment_with_patterns(time_series, patterns)
            time_series = aug_ts
            logger.info(
                "Cell %s: augmented with %d historical patterns (new development)",
                cell_id, len(patterns),
            )

        outputs = self.model(
            satellite=satellite,
            graph_batch=graph_batch,
            time_series=time_series,
            return_embeddings=True,
        )

        fused_emb = outputs["fused"].cpu().numpy().squeeze(0)
        stress = outputs["stress"].cpu().numpy().squeeze()  # (3, 1)
        breach_prob = torch.sigmoid(outputs["breach_logits"]).cpu().numpy().squeeze().mean()

        sp, sw, sr = float(stress[0]), float(stress[1]), float(stress[2])

        # ── Step 5: Store in Qdrant ─────────────────────
        self.cache.store_inference(
            cell_id=cell_id,
            lat=lat,
            lon=lon,
            timestamp=ts,
            embedding=fused_emb,
            stress_power=sp,
            stress_water=sw,
            stress_road=sr,
            breach_prob=float(breach_prob),
        )

        # ── Return ──────────────────────────────────────
        return InferenceResult(
            cell_id=cell_id,
            lat=lat,
            lon=lon,
            timestamp=ts,
            stress_power=sp,
            stress_water=sw,
            stress_road=sr,
            breach_prob=float(breach_prob),
            source="model_augmented" if is_new_development else "model_fresh",
            similar_patterns=patterns,
            embedding=fused_emb,
        )

    @torch.no_grad()
    def infer_batch(
        self,
        cells: List[Dict[str, Any]],
        force_fresh: bool = False,
    ) -> List[InferenceResult]:
        """Batch RAG inference for up to 256 cells.

        Args:
            cells: list of dicts with keys: cell_id, lat, lon, timestamp?.
            force_fresh: skip cache lookup entirely.

        Returns:
            list of InferenceResult, same order as input.
        """
        MAX_BATCH = 256
        if len(cells) > MAX_BATCH:
            logger.warning(
                "Batch size %d exceeds max %d — truncating.", len(cells), MAX_BATCH
            )
            cells = cells[:MAX_BATCH]

        results: List[InferenceResult] = []

        for cell in cells:
            result = self.infer_cell(
                cell_id=cell["cell_id"],
                lat=cell["lat"],
                lon=cell["lon"],
                timestamp=cell.get("timestamp"),
                time_series=None,
                force_fresh=force_fresh,
            )
            results.append(result)

        hit_rate = sum(1 for r in results if r.source == "cache_hit") / max(len(results), 1)
        logger.info(
            "Batch complete: %d cells, cache hit rate=%.1f%%",
            len(results), hit_rate * 100,
        )
        return results

    def _augment_with_patterns(
        self,
        base_ts: torch.Tensor,
        patterns: List[Dict[str, Any]],
    ) -> torch.Tensor:
        """Augment time-series with trends from similar historical patterns.

        For new developments: blends the base time-series with retrieved
        pattern trends (e.g., 'this density growth matches Kasarani 2022').
        """
        if not patterns:
            return base_ts

        pattern_weights = [p.get("cache_score", 0.5) for p in patterns]
        total_weight = sum(pattern_weights) or 1.0
        normalized_weights = [w / total_weight for w in pattern_weights]

        B, T, F = base_ts.shape

        # Build a trend signal from historical stress values
        augmented = base_ts.clone()
        blend_factor = min(0.3, len(patterns) * 0.1)

        for i, (pattern, weight) in enumerate(zip(patterns, normalized_weights)):
            # Use retrieved stress values to influence the signal
            sp = float(pattern.get("stress_power", 0.5))
            sw = float(pattern.get("stress_water", 0.5))
            sr = float(pattern.get("stress_road", 0.5))

            # Apply trend at the end of the time window (future-looking)
            start_t = T - min(T // 4, 18)
            trend = torch.linspace(0, weight * blend_factor, T - start_t)

            for t_idx, val in enumerate(trend, start=start_t):
                augmented[0, t_idx, 4] += val * (sp - 0.5) * 2.0  # stress_power channel
                augmented[0, t_idx, 5] += val * (sw - 0.5) * 2.0  # stress_water channel
                augmented[0, t_idx, 6] += val * (sr - 0.5) * 2.0  # stress_road channel

        return augmented
