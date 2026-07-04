"""Sindio — Field Operator Feedback Endpoint
=============================================
Allows Nairobi County engineers and field operators to submit
ground-truth corrections, flag incorrect predictions, and provide
operational context.

This closes the feedback loop between AI predictions and reality.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

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


_FEEDBACK_STORE: List[Dict[str, Any]] = []


@router.post("/submit")
async def submit_feedback(
    feedback: FeedbackSubmission,
    user: Dict = Depends(require_operator),
) -> Dict[str, Any]:
    """Submit field operator feedback.

    Feedback types:
      - incorrect_prediction: AI prediction didn't match reality
      - ground_truth: provide actual measured values
      - asset_condition: report physical state of infrastructure
      - maintenance_needed: flag urgent repairs needed
    """
    record = {
        "feedback_id": f"FBK-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(_FEEDBACK_STORE):06d}",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": user.get("sub", "unknown"),
        "user_role": user.get("role", "unknown"),
        "status": "open",
        **feedback.model_dump(),
    }

    _FEEDBACK_STORE.append(record)

    logger.info(
        "Feedback received: %s | type=%s | severity=%s | asset=%s",
        record["feedback_id"],
        feedback.feedback_type,
        feedback.severity,
        feedback.asset_id,
    )

    # In production: notify engineering team, create Jira ticket,
    # update model retraining queue if severity is critical

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
    filtered = [
        f for f in _FEEDBACK_STORE
        if (infrastructure_type is None or f["infrastructure_type"] == infrastructure_type)
        and (status is None or f["status"] == status)
    ]

    return {
        "count": len(filtered),
        "feedback": filtered[-50:],  # Last 50
    }


@router.post("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: str,
    resolution_notes: str = "",
    user: Dict = Depends(require_operator),
) -> Dict[str, Any]:
    """Mark feedback as resolved."""
    for f in _FEEDBACK_STORE:
        if f["feedback_id"] == feedback_id:
            f["status"] = "resolved"
            f["resolved_at"] = datetime.now(timezone.utc).isoformat()
            f["resolved_by"] = user.get("sub", "unknown")
            f["resolution_notes"] = resolution_notes
            return {"feedback_id": feedback_id, "status": "resolved"}

    raise HTTPException(404, f"Feedback {feedback_id} not found")
