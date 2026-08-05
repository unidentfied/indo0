from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import get_engine

logger = logging.getLogger("sindio.citizen_reports")

citizen_reports_router = APIRouter(prefix="/citizen-reports", tags=["citizen-reports"])


_CATEGORIES = "pothole, power_outage, water_leak, waste, sidewalk_damage, flooding, streetlight"


class CreateReportRequest(BaseModel):
    category: str = Field(..., description=_CATEGORIES)
    description: str = Field(default="")
    photo_url: str = Field(default="")
    lat: float = Field(...)
    lng: float = Field(...)
    ward: str = Field(default="")
    reporter_name: str = Field(default="")
    reporter_contact: str = Field(default="")
    severity: str = Field(default="medium")


class UpdateReportRequest(BaseModel):
    status: str | None = None
    resolution_notes: str | None = None
    severity: str | None = None


@citizen_reports_router.post("/")
async def create_report(body: CreateReportRequest):
    try:
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport, CitizenReportBase

        report_id = f"CR-{uuid.uuid4().hex[:10].upper()}"
        engine = get_engine()
        CitizenReportBase.metadata.create_all(bind=engine)

        with Session(bind=engine) as session:
            report = CitizenReport(
                report_id=report_id,
                category=body.category,
                description=body.description,
                photo_url=body.photo_url,
                lat=body.lat,
                lng=body.lng,
                ward=body.ward,
                reporter_name=body.reporter_name,
                reporter_contact=body.reporter_contact,
                status="reported",
                severity=body.severity,
            )
            session.add(report)
            session.commit()
            return {
                "report_id": report_id,
                "status": "reported",
                "message": "Report submitted successfully",
            }
    except Exception as e:
        logger.error("Failed to create report: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@citizen_reports_router.get("/")
async def list_reports(
    category: str | None = None,
    status: str | None = None,
    ward: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    try:
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport

        with Session(bind=get_engine()) as session:
            query = session.query(CitizenReport)
            if category:
                query = query.filter(CitizenReport.category == category)
            if status:
                query = query.filter(CitizenReport.status == status)
            if ward:
                query = query.filter(CitizenReport.ward == ward)

            total = query.count()
            reports = (
                query.order_by(CitizenReport.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "reports": [r.to_dict() for r in reports],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
    except Exception as e:
        logger.error("Failed to list reports: %s", e)
        return {"reports": [], "total": 0, "error": str(e)}


@citizen_reports_router.get("/geojson")
async def get_reports_geojson(
    category: str | None = None,
    status: str | None = "reported",
    limit: int = Query(200, le=1000),
):
    try:
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport

        with Session(bind=get_engine()) as session:
            query = session.query(CitizenReport)
            if category:
                query = query.filter(CitizenReport.category == category)
            if status:
                query = query.filter(CitizenReport.status == status)

            reports = query.order_by(CitizenReport.created_at.desc()).limit(limit).all()

            features = []
            for r in reports:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r.lng, r.lat]},
                    "properties": {
                        "report_id": r.report_id,
                        "category": r.category,
                        "description": r.description[:100],
                        "status": r.status,
                        "severity": r.severity,
                        "upvotes": r.upvotes,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    },
                })

            return {"type": "FeatureCollection", "features": features, "count": len(features)}
    except Exception as e:
        logger.error("Failed to get reports GeoJSON: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}


@citizen_reports_router.patch("/{report_id}")
async def update_report(report_id: str, body: UpdateReportRequest):
    try:
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport

        with Session(bind=get_engine()) as session:
            report = (
                session.query(CitizenReport)
                .filter(CitizenReport.report_id == report_id)
                .first()
            )
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")

            if body.status:
                report.status = body.status
                if body.status == "resolved":
                    report.resolved_at = datetime.now(timezone.utc)
            if body.resolution_notes:
                report.resolution_notes = body.resolution_notes
            if body.severity:
                report.severity = body.severity

            session.commit()
            return {"report_id": report_id, "updated": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@citizen_reports_router.post("/{report_id}/upvote")
async def upvote_report(report_id: str):
    try:
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport

        with Session(bind=get_engine()) as session:
            report = (
                session.query(CitizenReport)
                .filter(CitizenReport.report_id == report_id)
                .first()
            )
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            report.upvotes = (report.upvotes or 0) + 1
            session.commit()
            return {"report_id": report_id, "upvotes": report.upvotes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@citizen_reports_router.get("/stats")
async def get_report_stats():
    try:
        from sqlalchemy import func
        from sqlalchemy.orm import Session

        from ..models.citizen_report import CitizenReport

        with Session(bind=get_engine()) as session:
            total = session.query(func.count(CitizenReport.id)).scalar() or 0
            resolved = (
                session.query(func.count(CitizenReport.id))
                .filter(CitizenReport.status == "resolved")
                .scalar()
                or 0
            )
            by_category = {}
            cats = (
                session.query(CitizenReport.category, func.count(CitizenReport.id))
                .group_by(CitizenReport.category)
                .all()
            )
            for row in cats:
                by_category[row[0]] = row[1]
            by_status = {}
            sts = (
                session.query(CitizenReport.status, func.count(CitizenReport.id))
                .group_by(CitizenReport.status)
                .all()
            )
            for row in sts:
                by_status[row[0]] = row[1]

            return {
                "total_reports": total,
                "resolved": resolved,
                "resolution_rate_pct": round(resolved / total * 100, 1) if total > 0 else 0,
                "by_category": by_category,
                "by_status": by_status,
            }
    except Exception as e:
        return {"error": str(e)}
