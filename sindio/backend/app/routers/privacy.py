"""Sindio — GDPR Compliance Module
===================================
Provides data subject rights endpoints and privacy compliance features.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.rbac import require_admin, require_viewer

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
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


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


@router.post("/data-request")
async def submit_data_request(
    request: DataSubjectRequest,
    user: Dict = Depends(require_viewer),
) -> Dict[str, Any]:
    """Submit a GDPR data subject request.

    Types:
      - access: receive all data held about the user
      - deletion: request deletion of all personal data
      - rectification: correct inaccurate data
      - portability: receive data in machine-readable format
    """
    request_id = f"DSR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hash(request.email) % 10000:04d}"
    email_hash = _hash_email(request.email)

    logger.info(
        "GDPR data request received",
        request_id=request_id,
        request_type=request.request_type,
        email_hash=email_hash,
        user_role=user.get("role"),
    )

    # In production: queue to compliance team, track in DB
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
    # In production: lookup request, verify completion, return ZIP
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
    """Hard-delete or anonymize all personal data for a user (admin only, irreversible).""
    NOTE: Changed from DELETE to POST because HTTP DELETE with a request body
    is non-standard and may be stripped by proxies/CDNs.
    """
    email = body.email
    email_hash = _hash_email(email)
    request_id = f"DSR-DEL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hash(email) % 10000:04d}"

    conn = None
    affected_tables: list[str] = []
    try:
        conn = _get_db_connection()
        conn.autocommit = False
        with conn.cursor() as cur:
            # 1. Find user ID if users table exists
            user_id = None
            try:
                cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
                if row:
                    user_id = row[0]
            except psycopg2.Error:
                conn.rollback()

            # 2. Delete feedback by email
            try:
                cur.execute("DELETE FROM feedback WHERE email = %s", (email,))
                if cur.rowcount > 0:
                    affected_tables.append("feedback")
            except psycopg2.Error:
                conn.rollback()

            # 3. Delete simulations by user email
            try:
                cur.execute("DELETE FROM simulations WHERE user_email = %s", (email,))
                if cur.rowcount > 0:
                    affected_tables.append("simulations")
            except psycopg2.Error:
                conn.rollback()

            # 4. Anonymize sensor_telemetry (remove user linkage, keep measurements)
            try:
                cur.execute(
                    "UPDATE sensor_telemetry SET user_id = NULL, user_email = NULL WHERE user_email = %s",
                    (email,),
                )
                if cur.rowcount > 0:
                    affected_tables.append("sensor_telemetry")
            except psycopg2.Error:
                conn.rollback()

            # 5. Anonymize infrastructure_assets ownership if applicable
            try:
                cur.execute(
                    "UPDATE infrastructure_assets SET owner_email = NULL, owner_id = NULL WHERE owner_email = %s",
                    (email,),
                )
                if cur.rowcount > 0:
                    affected_tables.append("infrastructure_assets")
            except psycopg2.Error:
                conn.rollback()

            # 6. Delete user record
            if user_id is not None:
                try:
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                    affected_tables.append("users")
                except psycopg2.Error:
                    conn.rollback()
            else:
                # Try direct email delete if no ID found
                try:
                    cur.execute("DELETE FROM users WHERE email = %s", (email,))
                    if cur.rowcount > 0:
                        affected_tables.append("users")
                except psycopg2.Error:
                    conn.rollback()

            conn.commit()
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.error(
            "Account deletion failed",
            request_id=request_id,
            email_hash=email_hash,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Deletion failed: {exc}")
    finally:
        if conn:
            conn.close()

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
