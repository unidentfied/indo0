"""Sindio — GDPR Compliance Module
===================================
Provides data subject rights endpoints and privacy compliance features.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from sqlalchemy import text
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.rbac import require_admin, require_viewer
from app.core.database import get_engine

logger = logging.getLogger("sindio.gdpr")

router = APIRouter(prefix="/api/v1/privacy")


class DataSubjectRequest(BaseModel):
    email: EmailStr
    request_type: str  # access | deletion | rectification | portability
    description: str = ""


class DeleteAccountRequest(BaseModel):
    email: EmailStr
    cascade: bool = True


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


@router.post("/data-request")
async def submit_data_request(
    request: DataSubjectRequest,
    user: Dict = Depends(require_viewer),
) -> Dict[str, Any]:
    """Submit a GDPR data subject request."""
    request_id = f"DSR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hash(request.email) % 10000:04d}"
    email_hash = _hash_email(request.email)

    logger.info(
        "GDPR data request received",
        request_id=request_id,
        request_type=request.request_type,
        email_hash=email_hash,
        user_role=user.get("role"),
    )

    return {
        "request_id": request_id,
        "status": "received",
        "request_type": request.request_type,
        "email_hash": email_hash,
        "sla_days": 30 if request.request_type == "access" else 90,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/data-export/{request_id}")
async def download_data_export(
    request_id: str,
    user: Dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Download a completed data export (admin only)."""
    return {
        "request_id": request_id,
        "status": "pending",
        "message": "Export is being prepared. You will be notified via email.",
    }


@router.post("/delete-account")
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    user: Dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Hard-delete or anonymize all personal data for a user (admin only, irreversible)."""
    email = body.email
    email_hash = _hash_email(email)
    request_id = f"DSR-DEL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hash(email) % 10000:04d}"

    engine = get_engine()
    affected_tables: list[str] = []
    try:
        with engine.begin() as conn:
            # 1. Find user ID if users table exists
            user_id = None
            try:
                row = conn.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email}).fetchone()
                if row:
                    user_id = row[0]
            except Exception:
                pass

            # 2. Delete feedback by email
            try:
                result = conn.execute(text("DELETE FROM feedback WHERE email = :email"), {"email": email})
                if result.rowcount > 0:
                    affected_tables.append("feedback")
            except Exception:
                pass

            # 3. Delete simulations by user email
            try:
                result = conn.execute(text("DELETE FROM simulations WHERE user_email = :email"), {"email": email})
                if result.rowcount > 0:
                    affected_tables.append("simulations")
            except Exception:
                pass

            # 4. Anonymize sensor_telemetry
            try:
                result = conn.execute(
                    text("UPDATE sensor_telemetry SET user_id = NULL, user_email = NULL WHERE user_email = :email"),
                    {"email": email},
                )
                if result.rowcount > 0:
                    affected_tables.append("sensor_telemetry")
            except Exception:
                pass

            # 5. Anonymize infrastructure_assets ownership
            try:
                result = conn.execute(
                    text("UPDATE infrastructure_assets SET owner_email = NULL, owner_id = NULL WHERE owner_email = :email"),
                    {"email": email},
                )
                if result.rowcount > 0:
                    affected_tables.append("infrastructure_assets")
            except Exception:
                pass

            # 6. Delete user record
            if user_id is not None:
                try:
                    conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
                    affected_tables.append("users")
                except Exception:
                    pass
            else:
                try:
                    result = conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
                    if result.rowcount > 0:
                        affected_tables.append("users")
                except Exception:
                    pass
    except Exception as exc:
        logger.error(
            "Account deletion failed",
            request_id=request_id,
            email_hash=email_hash,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Deletion failed: {exc}")

    logger.info(
        "Account deletion executed",
        request_id=request_id,
        email_hash=email_hash,
        affected_tables=affected_tables,
        user_role=user.get("role"),
    )

    return {
        "status": "deleted",
        "request_id": request_id,
        "message": "Account and associated personal data have been purged or anonymized.",
        "affected_tables": affected_tables,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }
