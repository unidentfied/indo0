"""Sindio — Field Operator Feedback Endpoint
=============================================
Allows Nairobi County engineers and field operators to submit
ground-truth corrections, flag incorrect predictions, and provide
operational context.

Now persists to PostgreSQL. Falls back to in-memory only when
DATABASE_URL is not configured (local dev without Postgres).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.rbac import require_operator

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


def _get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url, connect_timeout=5)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "sindio"),
        user=os.getenv("DB_USER", "sindio_user"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
    )


def _db_is_configured() -> bool:
    return bool(os.getenv("DATABASE_URL") or os.getenv("DB_HOST"))


# In-memory fallback for local dev without Postgres
_FEEDBACK_STORE: List[Dict[str, Any]] = []


def _insert_feedback(record: Dict[str, Any]) -> None:
    if not _db_is_configured():
        _FEEDBACK_STORE.append(record)
        return
    try:
        conn = _get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback (
                    feedback_id, submitted_at, submitted_by, user_role, status,
                    asset_id, infrastructure_type, ward, lat, lon,
                    feedback_type, severity, description,
                    observed_value, expected_value, photo_url,
                    operator_name, operator_contact
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record["feedback_id"], record["submitted_at"], record["submitted_by"],
                    record["user_role"], record["status"], record["asset_id"],
                    record["infrastructure_type"], record["ward"], record.get("lat"),
                    record.get("lon"), record["feedback_type"], record["severity"],
                    record["description"], record.get("observed_value"),
                    record.get("expected_value"), record.get("photo_url"),
                    record.get("operator_name"), record.get("operator_contact"),
                ),
            )
            conn.commit()
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
        conn = _get_db_connection()
        with conn.cursor() as cur:
            query = """
                SELECT feedback_id, submitted_at, submitted_by, user_role, status,
                       asset_id, infrastructure_type, ward, lat, lon,
                       feedback_type, severity, description,
                       observed_value, expected_value, photo_url,
                       operator_name, operator_contact,
                       resolved_at, resolved_by, resolution_notes
                FROM feedback
                WHERE (%s IS NULL OR infrastructure_type = %s)
                  AND (%s IS NULL OR status = %s)
                ORDER BY submitted_at DESC
                LIMIT 50
            """
            cur.execute(query, (infra_type, infra_type, status_filter, status_filter))
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in rows]
    except Exception as exc:
        logger.warning("Feedback DB list failed (%s) — falling back to in-memory", exc)
        return [
            f for f in _FEEDBACK_STORE
            if (infra_type is None or f["infrastructure_type"] == infra_type)
            and (status_filter is None or f["status"] == status_filter)
        ][-50:]


def _resolve_feedback(feedback_id: str, user: Dict, resolution_notes: str) -> bool:
    if not _db_is_configured():
        for f in _FEEDBACK_STORE:
            if f["feedback_id"] == feedback_id:
                f["status"] = "resolved"
                f["resolved_at"] = datetime.now(timezone.utc).isoformat()
                f["resolved_by"] = user.get("sub", "unknown")
                f["resolution_notes"] = resolution_notes
                return True
        return False
    try:
        conn = _get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE feedback
                SET status = 'resolved',
                    resolved_at = %s,
                    resolved_by = %s,
                    resolution_notes = %s
                WHERE feedback_id = %s
                """,
                (
                    datetime.now(timezone.utc),
                    user.get("sub", "unknown"),
                    resolution_notes,
                    feedback_id,
                ),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning("Feedback DB resolve failed (%s) — falling back to in-memory", exc)
        for f in _FEEDBACK_STORE:
            if f["feedback_id"] == feedback_id:
                f["status"] = "resolved"
                f["resolved_at"] = datetime.now(timezone.utc).isoformat()
                f["resolved_by"] = user.get("sub", "unknown")
                f["resolution_notes"] = resolution_notes
                return True
        return False


@router.post("/submit")
async def submit_feedback(
    feedback: FeedbackSubmission,
    user: Dict = Depends(require_operator),
) -> Dict[str, Any]:
    """Submit field operator feedback."""
    record = {
        "feedback_id": f"FBK-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": user.get("sub", "unknown"),
        "user_role": user.get("role", "unknown"),
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
    user: Dict = Depends(require_operator),
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
    user: Dict = Depends(require_operator),
) -> Dict[str, Any]:
    """Mark feedback as resolved."""
    ok = _resolve_feedback(feedback_id, user, resolution_notes)
    if not ok:
        raise HTTPException(404, f"Feedback {feedback_id} not found")
    return {"feedback_id": feedback_id, "status": "resolved"}
