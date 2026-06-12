"""
RAG-based explanation generator for Sindio alerts.

When an alert fires:
  1. Retrieve 5 most similar historical alerts from Qdrant
  2. Retrieve relevant planning document chunks
  3. Retrieve recent maintenance records (CSV / DB)
  4. Build context → small LLM (Phi-3-mini) → natural-language explanation
  5. Cache in Redis (TTL = alert temporal spacing)
  6. Persist to TimescaleDB alert_explanations table

Example output:
  "This is the 3rd density-driven alert on WM-0427 in 18 months.
   Population in 500m radius grew 22% since last upgrade.
   Nairobi Water Master Plan (2024) Section 4.2 recommends
   parallel line by 2027. Last maintenance: 2023-11-05 (routine).
   Consider budget allocation in FY 2026/2027."
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.explain")


COLLECTION_ALERTS_HISTORY = os.getenv(
    "QDRANT_COLLECTION_ALERTS", "sindio_alert_history"
)
COLLECTION_PLANNING = os.getenv(
    "QDRANT_COLLECTION_PLANNING", "sindio_planning_docs"
)
EXPLANATION_VECTOR_DIM = 384
RETRIEVAL_TOP_K_ALERTS = 5
RETRIEVAL_TOP_K_PLANNING = 3
DEFAULT_LLM_MODEL = "microsoft/Phi-3-mini-4k-instruct"


# ──────────────────────────────────────────────────────────────
# Maintenance record loader
# ──────────────────────────────────────────────────────────────


def _load_maintenance_records(
    asset_id: Optional[str] = None,
    infra_type: Optional[str] = None,
    csv_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load maintenance records from CSV or infrastructure_assets table.

    CSV columns: asset_id, infra_type, ward, maintenance_date, action, cost_kes, notes

    Falls back to simulated records if no CSV found.
    """
    path = csv_path or os.getenv(
        "MAINTENANCE_CSV_PATH", "data/raw/maintenance_records.csv"
    )

    try:
        import pandas as pd

        df = pd.read_csv(path)
        if asset_id:
            df = df[df["asset_id"] == asset_id]
        if infra_type:
            df = df[df["infra_type"] == infra_type]
        return df.tail(10).to_dict(orient="records")
    except Exception:
        logger.debug("Maintenance CSV not found — using simulated records.")
        return _simulated_maintenance(asset_id, infra_type)


def _simulated_maintenance(
    asset_id: Optional[str] = None,
    infra_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generate plausible maintenance records for demonstration."""
    import random

    random.seed(hash(asset_id or "default") % (2**31))
    records = []
    base_date = datetime(2023, 1, 1)
    types = ["routine", "emergency", "upgrade", "inspection"]

    for i in range(3):
        records.append({
            "asset_id": asset_id or "unknown",
            "infra_type": infra_type or "water",
            "maintenance_date": (base_date + timedelta(days=random.randint(0, 700))).strftime("%Y-%m-%d"),
            "action": random.choice(types),
            "cost_kes": random.randint(5000, 500000),
            "notes": random.choice([
                "Pipe section replaced due to corrosion.",
                "Pump impeller serviced — vibration within tolerance.",
                "Pressure regulator recalibrated.",
                "Transformer oil changed — dielectric test passed.",
                "Road surface patching — pothole repair.",
            ]),
        })
    return records


# ──────────────────────────────────────────────────────────────
# Qdrant-based retrieval
# ──────────────────────────────────────────────────────────────


def _get_qdrant_client():
    from qdrant_client import QdrantClient

    return QdrantClient(
        url=os.getenv("QDRANT_HOST", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        timeout=15,
    )


def _get_embedder():
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        return None


def _retrieve_similar_alerts(
    alert_dict: Dict[str, Any],
    top_k: int = RETRIEVAL_TOP_K_ALERTS,
) -> List[Dict[str, Any]]:
    """Search Qdrant for historically similar alerts."""
    try:
        embedder = _get_embedder()
        if embedder is None:
            return _fallback_historical_alerts(alert_dict)

        query_text = (
            f"{alert_dict.get('infrastructure_type', '')} "
            f"stress {alert_dict.get('severity', 0.0):.2f} "
            f"trigger {alert_dict.get('trigger_reason', '')} "
            f"asset {alert_dict.get('asset_id', '')}"
        )
        query_emb = embedder.encode(query_text, normalize_embeddings=True).tolist()

        client = _get_qdrant_client()
        results = client.search(
            collection_name=COLLECTION_ALERTS_HISTORY,
            query_vector=query_emb,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        return [
            {**hit.payload, "similarity_score": hit.score}
            for hit in results
            if hit.payload
        ]
    except Exception as exc:
        logger.warning("Qdrant search failed: %s — using fallback.", exc)
        return _fallback_historical_alerts(alert_dict)


def _fallback_historical_alerts(alert_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic fallback when Qdrant is unreachable.

    Queries TimescaleDB alerts table for the same asset type.
    """
    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        engine = create_engine(db_url)
        infra = alert_dict.get("infrastructure_type", "water")

        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, infrastructure_type, asset_id, severity,
                           trigger_reason, created_at, recommended_action
                    FROM alerts
                    WHERE infrastructure_type = :infra
                    ORDER BY created_at DESC
                    LIMIT :k
                """),
                {"infra": infra, "k": RETRIEVAL_TOP_K_ALERTS},
            ).fetchall()

        return [
            {
                "id": str(row.id),
                "infrastructure_type": row.infrastructure_type,
                "asset_id": row.asset_id,
                "severity": float(row.severity) if row.severity else 0.0,
                "trigger_reason": row.trigger_reason,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "recommended_action": row.recommended_action,
                "similarity_score": 0.5,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.debug("TimescaleDB fallback also failed: %s", exc)
        return []


def _retrieve_planning_docs(
    alert_dict: Dict[str, Any],
    top_k: int = RETRIEVAL_TOP_K_PLANNING,
) -> List[Dict[str, Any]]:
    """Retrieve relevant planning document chunks from Qdrant."""
    try:
        embedder = _get_embedder()
        if embedder is None:
            return _fallback_planning_docs(alert_dict)

        infra = alert_dict.get("infrastructure_type", "water")
        asset_id = alert_dict.get("asset_id", "")
        query_text = f"{infra} infrastructure {asset_id} Nairobi planning upgrade budget"

        query_emb = embedder.encode(query_text, normalize_embeddings=True).tolist()

        client = _get_qdrant_client()
        results = client.search(
            collection_name=COLLECTION_PLANNING,
            query_vector=query_emb,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        return [
            {**hit.payload, "similarity_score": hit.score}
            for hit in results
            if hit.payload
        ]
    except Exception as exc:
        logger.debug("Planning doc retrieval failed: %s", exc)
        return _fallback_planning_docs(alert_dict)


def _fallback_planning_docs(alert_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return relevant planning document snippets without Qdrant."""
    infra = alert_dict.get("infrastructure_type", "water")
    snippets = {
        "water": [
            {"title": "Nairobi Water Master Plan 2024", "section": "4.2 Infrastructure Upgrades",
             "text": "Recommends parallel transmission mains by 2027 in high-growth corridors."},
            {"title": "NIDP 2025/2026", "section": "Water Supply",
             "text": "KES 12B allocated for Northern Collector Tunnel Phase II."},
        ],
        "power": [
            {"title": "Kenya Power Master Plan 2020-2040", "section": "Nairobi Region",
             "text": "Nairobi peak demand forecast: 1,200 MW by 2030. Dandora 132kV upgrade scheduled."},
        ],
        "roads": [
            {"title": "Nairobi Metro 2030", "section": "BRT Network",
             "text": "BRT Line 3 (Dandora–CBD) and Line 4 (Eastlands Loop) with dedicated lanes."},
        ],
        "solid_waste": [
            {"title": "Nairobi County SWM Strategy", "section": "Collection Expansion",
             "text": "Supplementary collection shifts for high-density wards."},
        ],
    }
    return snippets.get(infra, snippets["water"])


# ──────────────────────────────────────────────────────────────
# LLM call (Phi-3-mini or fallback)
# ──────────────────────────────────────────────────────────────


def _call_explanation_llm(context: str) -> str:
    """Generate explanation text using a small LLM.

    Tries in order:
      1. Local Phi-3-mini via HuggingFace pipeline (if available)
      2. OpenAI-compatible endpoint (if OPENAI_API_KEY is set)
      3. Deterministic template-based fallback
    """
    # Try local Phi-3-mini
    try:
        from transformers import pipeline

        pipe = pipeline(
            "text-generation",
            model=DEFAULT_LLM_MODEL,
            trust_remote_code=True,
            device_map="auto",
            max_new_tokens=256,
            temperature=0.3,
        )
        prompt = (
            "<|system|>You are an urban infrastructure analyst for Nairobi, Kenya. "
            "Write a concise (2-4 sentence) explanation for the alert below. "
            "Reference specific planning documents, maintenance history, and growth patterns "
            "where relevant. Be factual and specific.<|end|>\n"
            f"<|user|>{context}<|end|>\n"
            "<|assistant|>"
        )
        result = pipe(prompt, max_new_tokens=200, do_sample=True)
        return result[0]["generated_text"].split("<|assistant|>")[-1].strip()
    except Exception:
        pass

    # Try OpenAI-compatible endpoint
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key and not api_key.startswith("sk-placeholder"):
        try:
            import openai

            client = openai.OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL", None), timeout=15.0)
            response = client.chat.completions.create(
                model=os.getenv("EXPLANATION_MODEL", "gpt-4o-mini"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an urban infrastructure analyst for Nairobi, Kenya. "
                            "Write a concise 2-4 sentence explanation for alerts. "
                            "Reference specific planning documents and growth patterns."
                        ),
                    },
                    {"role": "user", "content": context},
                ],
                temperature=0.3,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            pass

    return _template_explanation(context)


def _template_explanation(context: str) -> str:
    """Deterministic template-based fallback explanation."""
    import re

    infra_match = re.search(r"Asset Type:\s*(\w+)", context)
    asset_match = re.search(r"Asset ID:\s*(\S+)", context)
    severity_match = re.search(r"Severity:\s*([\d.]+)", context)
    trigger_match = re.search(r"Trigger:\s*(\S+)", context)
    count_match = re.search(r"Historical Count:\s*(\d+)", context)

    infra = infra_match.group(1) if infra_match else "infrastructure"
    asset = asset_match.group(1) if asset_match else "this asset"
    severity = float(severity_match.group(1)) if severity_match else 0.0
    trigger = trigger_match.group(1) if trigger_match else "detected"
    count = int(count_match.group(1)) if count_match else 1

    parts = [f"Stress alert on {asset} ({infra}) at severity {severity:.2f}."]

    if trigger == "sudden_change":
        parts.append("Rapid deterioration detected — possible cascading failure risk.")
    elif trigger == "critical_threshold":
        parts.append("Asset has breached the critical safety threshold and requires immediate action.")
    elif "reclassification" in trigger:
        parts.append(f"Root cause has shifted — {trigger.replace('reclassification:', 'from ')}.")

    if count > 1:
        parts.append(f"This is the {count}th alert on this asset. Consider long-term infrastructure upgrade.")

    # Inject planning doc reference if available
    planning_match = re.search(r"Planning Doc:\s*(.+?)(?:\n|$)", context)
    if planning_match:
        parts.append(f"Refer to {planning_match.group(1).strip()} for guidance.")

    return " ".join(parts)


# ──────────────────────────────────────────────────────────────
# Context builder
# ──────────────────────────────────────────────────────────────


def _build_llm_context(
    alert_dict: Dict[str, Any],
    historical_alerts: List[Dict[str, Any]],
    planning_docs: List[Dict[str, Any]],
    maintenance_records: List[Dict[str, Any]],
) -> str:
    """Assemble retrieval results into a structured context string for the LLM."""
    parts = []

    # Current alert
    parts.append("## Current Alert")
    parts.append(f"Asset ID: {alert_dict.get('asset_id', '?')}")
    parts.append(f"Asset Type: {alert_dict.get('infrastructure_type', '?')}")
    parts.append(f"Severity: {alert_dict.get('severity', 0.0):.2f}")
    parts.append(f"Trigger: {alert_dict.get('trigger_reason', '?')}")
    classification = alert_dict.get("classification", {})
    if isinstance(classification, dict):
        parts.append(f"Classification: {classification.get('type', '?')} (confidence: {classification.get('confidence', 0.0):.2f})")

    # Historical alerts
    parts.append(f"\n## Historical Alerts ({len(historical_alerts)} similar found)")
    if historical_alerts:
        parts.append(f"Historical Count: {len(historical_alerts)}")
        for ha in historical_alerts[:3]:
            parts.append(
                f"- {ha.get('created_at', '?')[:10]}: severity={ha.get('severity', 0.0):.2f}, "
                f"trigger={ha.get('trigger_reason', '?')}"
            )
    else:
        parts.append("(No similar historical alerts found)")

    # Planning documents
    parts.append(f"\n## Relevant Planning Documents ({len(planning_docs)} found)")
    for pd_doc in planning_docs[:2]:
        parts.append(
            f"- {pd_doc.get('title', '?')}, {pd_doc.get('section', '?')}: "
            f"{pd_doc.get('text', '')[:200]}"
        )
    if planning_docs:
        pd_first = planning_docs[0]
        parts.append(f"Planning Doc: {pd_first.get('title', '?')} Section {pd_first.get('section', '?')}")

    # Maintenance records
    parts.append(f"\n## Maintenance History ({len(maintenance_records)} records)")
    for mr in maintenance_records[:3]:
        parts.append(
            f"- {mr.get('maintenance_date', '?')}: {mr.get('action', '?')} "
            f"(KES {mr.get('cost_kes', 0):,}) — {mr.get('notes', '')}"
        )

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────
# Redis cache
# ──────────────────────────────────────────────────────────────


def _get_redis():
    try:
        import redis as redis_lib

        return redis_lib.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=3,
        )
    except ImportError:
        return None


def _cache_explanation(alert_id: str, explanation: str, ttl_seconds: int):
    r = _get_redis()
    if r is None:
        return
    key = f"sindio:explanation:{alert_id}"
    r.setex(key, ttl_seconds, explanation)


def _get_cached_explanation(alert_id: str) -> Optional[str]:
    r = _get_redis()
    if r is None:
        return None
    return r.get(f"sindio:explanation:{alert_id}")


# ──────────────────────────────────────────────────────────────
# Main public function (called by alert_generator.py)
# ──────────────────────────────────────────────────────────────


def explain_alert(
    alert_dict: Dict[str, Any],
    temporal_spacing_seconds: int = 86400,
    skip_cache: bool = False,
) -> Dict[str, Any]:
    """Generate a RAG-based explanation for a single fired alert.

    Args:
        alert_dict: the alert JSON dict from AlertGenerator.
        temporal_spacing_seconds: TTL for Redis cache.
        skip_cache: bypass cache and regenerate.

    Returns:
        dict with keys: alert_id, explanation_text, historical_alerts,
                        planning_references, maintenance_context, llm_model,
                        generated_at, cached_until.
    """
    alert_id = alert_dict.get("id", "")

    if not alert_id:
        logger.warning("Alert dict missing 'id' — cannot generate explanation.")
        return {"alert_id": "", "explanation_text": ""}

    # ── Cache check ─────────────────────────────────────
    if not skip_cache:
        cached = _get_cached_explanation(alert_id)
        if cached is not None:
            logger.info("Explanation cache HIT for alert %s", alert_id)
            return {
                "alert_id": alert_id,
                "explanation_text": cached,
                "historical_alerts": [],
                "planning_references": [],
                "maintenance_context": "from-cache",
                "llm_model": "cache",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cached_until": (datetime.now(timezone.utc) + timedelta(seconds=temporal_spacing_seconds)).isoformat(),
            }

    # ── Retrieve context ────────────────────────────────
    device_id = alert_dict.get("asset_id", "")
    infra_type = alert_dict.get("infrastructure_type", "water")

    logger.info("Generating RAG explanation for alert %s (%s)", alert_id, device_id)

    historical = _retrieve_similar_alerts(alert_dict)
    planning = _retrieve_planning_docs(alert_dict)
    maintenance = _load_maintenance_records(asset_id=device_id, infra_type=infra_type)

    # ── Build context + call LLM ────────────────────────
    context = _build_llm_context(alert_dict, historical, planning, maintenance)

    model_used = "template"
    try:
        explanation = _call_explanation_llm(context)
        model_used = DEFAULT_LLM_MODEL if os.getenv("OPENAI_API_KEY") else "template"
    except Exception as exc:
        logger.error("LLM call failed: %s. Using template.", exc)
        explanation = _template_explanation(context)

    # ── Cache ───────────────────────────────────────────
    _cache_explanation(alert_id, explanation, temporal_spacing_seconds)

    result = {
        "alert_id": alert_id,
        "explanation_text": explanation,
        "historical_alerts": historical,
        "planning_references": planning,
        "maintenance_context": json.dumps(maintenance[:5], default=str),
        "llm_model": model_used,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached_until": (datetime.now(timezone.utc) + timedelta(seconds=temporal_spacing_seconds)).isoformat(),
    }

    # ── Persist to TimescaleDB ──────────────────────────
    _persist_explanation(result)

    return result


def _persist_explanation(result: Dict[str, Any]):
    """Store explanation in alert_explanations table."""
    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        engine = create_engine(db_url)

        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO alert_explanations
                        (alert_id, explanation_text, historical_alerts,
                         planning_references, maintenance_context, llm_model,
                         generated_at, cached_until)
                    VALUES
                        (:alert_id, :text, :historical::jsonb, :planning::jsonb,
                         :maintenance, :model, :gen_at, :cached_until)
                """),
                {
                    "alert_id": result["alert_id"],
                    "text": result["explanation_text"],
                    "historical": json.dumps(result.get("historical_alerts", []), default=str),
                    "planning": json.dumps(result.get("planning_references", []), default=str),
                    "maintenance": result.get("maintenance_context", ""),
                    "model": result.get("llm_model", "unknown"),
                    "gen_at": result["generated_at"],
                    "cached_until": result["cached_until"],
                },
            )
        logger.debug("Persisted explanation for alert %s", result["alert_id"])
    except Exception as exc:
        logger.warning("Failed to persist explanation: %s", exc)
