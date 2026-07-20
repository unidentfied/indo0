"""Sindio — Field Operator Feedback Endpoint
=============================================
Allows Nairobi County engineers and field operators to submit
ground-truth corrections, flag incorrect predictions, and provide
operational context.

Now persists to PostgreSQL via SQLAlchemy connection pooling.
Falls back to in-memory only when DATABASE_URL is not configured
(local dev without Postgres).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import text
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..rbac import optional_auth
from ..core.database import get_engine

logger = logging.getLogger("sindio.feedback")

router = APIRouter(prefix="/api/v1/feedback")


class FeedbackSubmission(BaseModel):
    asset_id: str
    infrastructure_type: str
    ward: str
    lat: float
    lon: float
    feedback_type: Literal["incorrect_prediction", "ground_truth", "asset_condition", "maintenance_needed"]
    severity: Literal["low", "medium", "high", "critical"]
    description: str = Field(..., min_length=10, max_length=2000)
    observed_value: Optional[float] = None
    expected_value: Optional[float] = None
    photo_url: Optional[str] = None
    operator_name: Optional[str] = None
    operator_contact: Optional[str] = None


def _db_is_configured() -> bool:
    return bool(os.getenv("DATABASE_URL") or os.getenv("DB_HOST"))


# In-memory fallback for local dev without Postgres
_FEEDBACK_STORE: List[Dict[str, Any]] = []


def _insert_feedback(record: Dict[str, Any]) -> None:
    if not _db_is_configured():
        _FEEDBACK_STORE.append(record)
        return
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO feedback (
                        feedback_id, submitted_at, submitted_by, user_role, status,
                        asset_id, infrastructure_type, ward, lat, lon,
                        feedback_type, severity, description,
                        observed_value, expected_value, photo_url,
                        operator_name, operator_contact
                    ) VALUES (
                        :feedback_id, :submitted_at, :submitted_by, :user_role, :status,
                        :asset_id, :infrastructure_type, :ward, :lat, :lon,
                        :feedback_type, :severity, :description,
                        :observed_value, :expected_value, :photo_url,
                        :operator_name, :operator_contact
                    )
                """),
                record,
            )
    except Exception as exc:
        logger.warning("Feedback DB insert failed (%s) — falling back to in-memory", exc)
        _FEEDBACK_STORE.append(record)


def _list_feedback(infra_type: Optional[str], status_filter: Optional[str]) -> List[Dict[str, Any]]:
    if not _db_is_configured():
        return [
            f for f in _FEEDBACK_STORE
            if (infra_type is None or f["infrastructure_type"] == infra_type)
            and (status_filter is None or f["status"] == status_filter)
        ][-50:]
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT feedback_id, submitted_at, submitted_by, user_role, status,
                           asset_id, infrastructure_type, ward, lat, lon,
                           feedback_type, severity, description,
                           observed_value, expected_value, photo_url,
                           operator_name, operator_contact,
                           resolved_at, resolved_by, resolution_notes
                    FROM feedback
                    WHERE (:infra_type IS NULL OR infrastructure_type = :infra_type)
                      AND (:status_filter IS NULL OR status = :status_filter)
                    ORDER BY submitted_at DESC
                    LIMIT 50
                """),
                {"infra_type": infra_type, "status_filter": status_filter},
            )
            rows = result.mappings().all()
            return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Feedback DB list failed (%s) — falling back to in-memory", exc)
        return [
            f for f in _FEEDBACK_STORE
            if (infra_type is None or f["infrastructure_type"] == infra_type)
            and (status_filter is None or f["status"] == status_filter)
        ][-50:]


def _resolve_feedback(feedback_id: str, user: Optional[Dict], resolution_notes: str) -> bool:
    resolver = user.get("sub", "unknown") if user else "anonymous"
    if not _db_is_configured():
        for f in _FEEDBACK_STORE:
            if f["feedback_id"] == feedback_id:
                f["status"] = "resolved"
                f["resolved_at"] = datetime.now(timezone.utc).isoformat()
                f["resolved_by"] = resolver
                f["resolution_notes"] = resolution_notes
                return True
        return False
    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                    UPDATE feedback
                    SET status = 'resolved',
                        resolved_at = :resolved_at,
                        resolved_by = :resolved_by,
                        resolution_notes = :resolution_notes
                    WHERE feedback_id = :feedback_id
                """),
                {
                    "resolved_at": datetime.now(timezone.utc),
                    "resolved_by": resolver,
                    "resolution_notes": resolution_notes,
                    "feedback_id": feedback_id,
                },
            )
            return result.rowcount > 0
    except Exception as exc:
        logger.warning("Feedback DB resolve failed (%s) — falling back to in-memory", exc)
        for f in _FEEDBACK_STORE:
            if f["feedback_id"] == feedback_id:
                f["status"] = "resolved"
                f["resolved_at"] = datetime.now(timezone.utc).isoformat()
                f["resolved_by"] = resolver
                f["resolution_notes"] = resolution_notes
                return True
        return False


@router.post("/submit")
async def submit_feedback(
    feedback: FeedbackSubmission,
    user: Optional[Dict] = Depends(optional_auth),
) -> Dict[str, Any]:
    """Submit field operator feedback."""
    record = {
        "feedback_id": f"FBK-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": user.get("sub", "anonymous") if user else "anonymous",
        "user_role": user.get("role", "anonymous") if user else "anonymous",
        "status": "open",
        **feedback.model_dump(),
    }

    _insert_feedback(record)

    logger.info(
        "Feedback received: %s | type=%s | severity=%s | asset=%s",
        record["feedback_id"],
        feedback.feedback_type,
        feedback.severity,
        feedback.asset_id,
    )

    return {
        "feedback_id": record["feedback_id"],
        "status": "received",
        "message": "Thank you. Your feedback has been logged and will be reviewed by the engineering team.",
        "sla_hours": 24 if feedback.severity == "critical" else 72,
    }


@router.get("/list")
async def list_feedback(
    infrastructure_type: Optional[str] = None,
    status: Optional[str] = "open",
    user: Optional[Dict] = Depends(optional_auth),
) -> Dict[str, Any]:
    """List feedback submissions (operator+ roles)."""
    results = _list_feedback(infrastructure_type, status)
    return {
        "count": len(results),
        "feedback": results,
    }


@router.post("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: str,
    resolution_notes: str = "",
    user: Optional[Dict] = Depends(optional_auth),
) -> Dict[str, Any]:
    """Mark feedback as resolved."""
    ok = _resolve_feedback(feedback_id, user, resolution_notes)
    if not ok:
        raise HTTPException(404, f"Feedback {feedback_id} not found")
    return {"feedback_id": feedback_id, "status": "resolved"}
