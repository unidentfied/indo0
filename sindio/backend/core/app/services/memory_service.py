"""
Persistent memory for the Sindio recommendation engine.

Long-term memory (PostgreSQL):
  - simulation_memory:  embeddings, planner feedback, observed outcomes
  - decision_memory:    planner actions + long-term outcomes
  - FAISS-backed vector search for similar past scenarios

Working memory (Redis, 7-day TTL):
  - Current simulation state per user  (Celery task_id → intermediate results)
  - Active agent workflow steps        (run_id → node state)

Memory recall (integrated into agent_workflow.py):
  - Before planning:  query simulation_memory for similar embedding
  - UPVOTE ≥ 2:       inject recommendation as 'historical precedent'
  - DOWNVOTE ≥ 2:      add warning 'avoid this approach — failed previously'
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.memory")

# ── Redis client (working memory) ────────────────────────────
_redis_client: Optional[Any] = None
WORKING_MEMORY_TTL = 7 * 24 * 60 * 60  # 7 days


def _get_redis() -> Any:
    global _redis_client
    if _redis_client is None:
        try:
            import redis as _r
            _redis_client = _r.Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
        except Exception:
            logger.warning("Redis not available — working memory disabled.")
            _redis_client = None
    return _redis_client


# ──────────────────────────────────────────────────────────────
# Working memory (Redis)
# ──────────────────────────────────────────────────────────────


def store_simulation_state(sim_task_id: str, state: dict) -> None:
    """Persist current simulation state in Redis (7-day TTL)."""
    r = _get_redis()
    if r is None:
        return
    key = f"sindio:sim_state:{sim_task_id}"
    r.setex(key, WORKING_MEMORY_TTL, json.dumps(state, default=str))


def get_simulation_state(sim_task_id: str) -> Optional[dict]:
    """Retrieve current simulation state from working memory."""
    r = _get_redis()
    if r is None:
        return None
    raw = r.get(f"sindio:sim_state:{sim_task_id}")
    return json.loads(raw) if raw else None


def store_agent_workflow_step(run_id: str, node_name: str, state: dict) -> None:
    """Persist the current agent workflow step in Redis."""
    r = _get_redis()
    if r is None:
        return
    key = f"sindio:agent_step:{run_id}:{node_name}"
    r.setex(key, WORKING_MEMORY_TTL, json.dumps(state, default=str))


def get_agent_workflow_step(run_id: str, node_name: str) -> Optional[dict]:
    """Retrieve a specific agent workflow step."""
    r = _get_redis()
    if r is None:
        return None
    raw = r.get(f"sindio:agent_step:{run_id}:{node_name}")
    return json.loads(raw) if raw else None


def get_agent_workflow_state(run_id: str) -> Dict[str, dict]:
    """Return all stored steps for a given agent run."""
    r = _get_redis()
    if r is None:
        return {}
    keys = r.keys(f"sindio:agent_step:{run_id}:*")
    result: Dict[str, dict] = {}
    for key in keys:
        node_name = key.split(":")[-1]
        raw = r.get(key)
        if raw:
            result[node_name] = json.loads(raw)
    return result


# ──────────────────────────────────────────────────────────────
# Long-term memory (PostgreSQL)
# ──────────────────────────────────────────────────────────────


def _get_pg_engine():
    from sqlalchemy import create_engine

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    return create_engine(db_url)


def store_simulation_memory(
    simulation_id: str,
    infrastructure_type: str,
    ward: str,
    embedding: np.ndarray,
    alert_id: Optional[str] = None,
    density_projection: Optional[dict] = None,
    planning_context: Optional[dict] = None,
    infrastructure_assets_affected: Optional[List[str]] = None,
    recommendation: Optional[dict] = None,
    research_findings: Optional[dict] = None,
    tags: Optional[List[str]] = None,
) -> Optional[str]:
    """Persist a simulation run in long-term memory. Returns the row UUID."""
    engine = _get_pg_engine()
    if engine is None:
        logger.warning("DATABASE_URL not set — skipping long-term memory persist.")
        return None

    from sqlalchemy import text

    embedding_bytes = embedding.astype(np.float32).tobytes()

    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """INSERT INTO simulation_memory
                       (simulation_id, infrastructure_type, ward, alert_id, embedding,
                        density_projection, planning_context, infrastructure_assets_affected,
                        recommendation, research_findings, tags)
                    VALUES
                       (:sid, :infra, :ward, :aid, :emb, :proj, :ctx, :assets, :rec, :findings, :tags)
                    RETURNING id"""
                ),
                {
                    "sid": simulation_id,
                    "infra": infrastructure_type,
                    "ward": ward,
                    "aid": alert_id,
                    "emb": embedding_bytes,
                    "proj": json.dumps(density_projection or {}),
                    "ctx": json.dumps(planning_context or {}),
                    "assets": infrastructure_assets_affected or [],
                    "rec": json.dumps(recommendation or {}),
                    "findings": json.dumps(research_findings or {}),
                    "tags": tags or [],
                },
            )
            row_id = str(result.fetchone()[0])
            logger.info("Stored simulation '%s' in long-term memory (id=%s)", simulation_id, row_id)
            return row_id
    except Exception as exc:
        logger.warning("Failed to store simulation memory: %s", exc)
        return None


def record_planner_feedback(
    memory_id: str,
    feedback: str,  # 'UPVOTE' or 'DOWNVOTE'
    comment: Optional[str] = None,
    feedback_by: Optional[str] = None,
) -> bool:
    """Record planner upvote/downvote on a simulation memory row."""
    engine = _get_pg_engine()
    if engine is None:
        return False

    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT adjust_simulation_weight(:id, :fb, :comment, :by)"),
                {"id": memory_id, "fb": feedback, "comment": comment, "by": feedback_by},
            )
        logger.info("Recorded %s feedback on memory %s", feedback, memory_id)
        return True
    except Exception as exc:
        logger.warning("Failed to record feedback: %s", exc)
        return False


def store_decision_memory(
    alert_id: str,
    planner_action_taken: str,
    simulation_memory_id: Optional[str] = None,
    asset_ids_affected: Optional[List[str]] = None,
    outcome_months_later: Optional[int] = None,
    outcome_description: Optional[str] = None,
    was_successful: Optional[bool] = None,
    cost_actual_kes: Optional[int] = None,
    notes: Optional[str] = None,
    recorded_by: Optional[str] = None,
) -> Optional[str]:
    """Persist a planner decision outcome."""
    engine = _get_pg_engine()
    if engine is None:
        return None

    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """INSERT INTO decision_memory
                       (alert_id, planner_action_taken, simulation_memory_id,
                        asset_ids_affected, outcome_months_later, outcome_description,
                        was_successful, cost_actual_kes, notes, recorded_by)
                    VALUES
                       (:aid, :action, :sim_mem, :assets, :months, :desc,
                        :success, :cost, :notes, :by)
                    RETURNING id"""
                ),
                {
                    "aid": alert_id,
                    "action": planner_action_taken,
                    "sim_mem": simulation_memory_id,
                    "assets": asset_ids_affected or [],
                    "months": outcome_months_later,
                    "desc": outcome_description,
                    "success": was_successful,
                    "cost": cost_actual_kes,
                    "notes": notes,
                    "by": recorded_by,
                },
            )
            return str(result.fetchone()[0])
    except Exception as exc:
        logger.warning("Failed to store decision memory: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# Memory retrieval (FAISS vector search in simulation_memory)
# ──────────────────────────────────────────────────────────────

_faiss_mem_index: Optional[Any] = None
_faiss_mem_ids: List[str] = []


def _build_memory_faiss_index(force: bool = False) -> Any:
    """Build/load a FAISS index from simulation_memory.embedding."""
    global _faiss_mem_index, _faiss_mem_ids

    if _faiss_mem_index is not None and not force:
        return _faiss_mem_index

    import faiss

    engine = _get_pg_engine()
    if engine is None:
        return _faiss_mem_index

    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, embedding FROM simulation_memory "
                    "WHERE embedding IS NOT NULL ORDER BY created_at DESC LIMIT 50000"
                )
            ).fetchall()
    except Exception as exc:
        logger.warning("Cannot load simulation_memory embeddings: %s", exc)
        return _faiss_mem_index

    if not rows:
        return _faiss_mem_index

    vectors: List[np.ndarray] = []
    ids: List[str] = []
    for row_id, emb_bytes in rows:
        try:
            vec = np.frombuffer(emb_bytes, dtype=np.float32).reshape(-1)
            if vec.shape[0] == 1024:
                ids.append(str(row_id))
                vectors.append(vec)
        except Exception:
            continue

    if not vectors:
        return _faiss_mem_index

    data = np.vstack(vectors).astype(np.float32)
    norms = np.linalg.norm(data, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    data = data / norms

    index = faiss.IndexFlatIP(1024)
    id_map = faiss.IndexIDMap(index)
    id_map.add_with_ids(data, np.arange(len(ids), dtype=np.int64))

    _faiss_mem_index = id_map
    _faiss_mem_ids = ids
    logger.info("Memory FAISS index: %d vectors", len(ids))
    return _faiss_mem_index


def recall_similar_simulations(
    embedding: np.ndarray,
    top_k: int = 5,
    *,
    min_upvotes: int = 2,
    min_downvotes: int = 2,
    infra_type_filter: Optional[str] = None,
) -> Dict[str, List[dict]]:
    """
    Search simulation_memory for similar past scenarios using FAISS.

    Returns a dict with two keys:
      - 'precedents':  rows with planner_feedback = 'UPVOTE' and ≥ *min_upvotes*
      - 'warnings':    rows with planner_feedback = 'DOWNVOTE' and ≥ *min_downvotes*

    Each entry is a dict with simulation_id, recommendation, ward, outcome, etc.
    """
    index = _build_memory_faiss_index()
    engine = _get_pg_engine()

    if index is None or engine is None or len(_faiss_mem_ids) == 0:
        return {"precedents": [], "warnings": []}

    vec = embedding.astype(np.float32).reshape(1, -1)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    k = min(top_k * 3, index.ntotal)
    distances, raw_indices = index.search(vec, k=k)

    # Map FAISS internal IDs to memory row UUIDs
    matched_ids = [_faiss_mem_ids[int(i)] for i in raw_indices[0] if int(i) < len(_faiss_mem_ids)]
    if not matched_ids:
        return {"precedents": [], "warnings": []}

    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """SELECT id, simulation_id, infrastructure_type, ward,
                          recommendation, planner_feedback, outcome_observed,
                          infrastructure_assets_affected, tags, research_findings
                   FROM simulation_memory
                   WHERE id = ANY(:ids)
                     AND planner_feedback != 'none'"""
            ),
            {"ids": matched_ids},
        ).fetchall()

    precedents: List[dict] = []
    warnings: List[dict] = []

    seen_upvote = 0
    seen_downvote = 0

    for row in rows:
        entry = {
            "memory_id": str(row.id),
            "simulation_id": row.simulation_id,
            "infrastructure_type": row.infrastructure_type,
            "ward": row.ward,
            "recommendation": row.recommendation or {},
            "outcome_observed": row.outcome_observed,
            "assets_affected": row.infrastructure_assets_affected or [],
            "tags": row.tags or [],
            "research_findings": row.research_findings or {},
        }

        if infra_type_filter and row.infrastructure_type != infra_type_filter:
            continue

        if row.planner_feedback == "UPVOTE":
            seen_upvote += 1
            entry["feedback"] = "UPVOTE"
            if seen_upvote <= min_upvotes:
                precedents.append(entry)
        elif row.planner_feedback == "DOWNVOTE":
            seen_downvote += 1
            entry["feedback"] = "DOWNVOTE"
            if seen_downvote <= min_downvotes:
                warnings.append(entry)

    logger.info(
        "Memory recall — %d precedents, %d warnings from %d FAISS hits",
        len(precedents), len(warnings), len(rows),
    )
    return {"precedents": precedents, "warnings": warnings}


def recall_similar_decisions(
    alert_id: str,
    infrastructure_type: Optional[str] = None,
) -> List[dict]:
    """Retrieve past planner decisions for a given alert or infra type."""
    engine = _get_pg_engine()
    if engine is None:
        return []

    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """SELECT dm.*, sm.ward, sm.infrastructure_type
                       FROM decision_memory dm
                       LEFT JOIN simulation_memory sm ON dm.simulation_memory_id = sm.id
                       WHERE dm.alert_id = :aid
                          OR (:infra IS NOT NULL AND sm.infrastructure_type = :infra)
                       ORDER BY dm.recorded_at DESC
                       LIMIT 20"""
                ),
                {"aid": alert_id, "infra": infrastructure_type},
            ).fetchall()

        return [
            {
                "id": str(row.id),
                "alert_id": str(row.alert_id) if row.alert_id else None,
                "action": row.planner_action_taken,
                "was_successful": row.was_successful,
                "outcome_description": row.outcome_description,
                "cost_actual_kes": row.cost_actual_kes,
                "ward": getattr(row, "ward", None),
                "infrastructure_type": getattr(row, "infrastructure_type", None),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Failed to recall decisions: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────
# Bulk rebuild (call periodically or via celery beat)
# ──────────────────────────────────────────────────────────────


def rebuild_memory_index() -> dict:
    """Force-rebuild the memory FAISS index. Call daily via Celery."""
    start = datetime.now(timezone.utc)
    try:
        global _faiss_mem_index
        _faiss_mem_index = None
        _build_memory_faiss_index(force=True)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        return {"status": "ok", "elapsed_s": round(elapsed, 1), "vectors": len(_faiss_mem_ids)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
