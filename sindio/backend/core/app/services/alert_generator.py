"""
Alert Generator — monitors simulation outputs and generates temporally spaced alerts.

Triggers:
  1. Sudden change:  stress increase > 0.2 in 24 hours
  2. Critical:       stress > 0.85
  3. Reclassification: classification_type changes (e.g. recurring → density_driven)

Stores in TimescaleDB hypertable `alerts` (5-year retention).
Publishes JSON alerts to Redis pub/sub channel `alerts:realtime` for WebSocket push.

Temporal spacing: per infrastructure type, alerts are throttled to the
natural cadence defined in INFRASTRUCTURE_INTERVALS.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.alert_gen")

# ──────────────────────────────────────────────────────────────
# Infrastructure-specific action templates — sourced from registry
# Detailed actions per tier, built from unified registry config.
# ──────────────────────────────────────────────────────────────
from app.services.monitor.registry import get_all_configs, get_config as get_infra_config

# Build RECOMMENDED_ACTIONS from registry (detailed per-tier lists)
RECOMMENDED_ACTIONS: Dict[str, Dict[str, List[str]]] = {}
TEMPORAL_SPACING: Dict[str, int] = {}

for c in get_all_configs():
    # Temporal spacing: convert days to seconds
    TEMPORAL_SPACING[c.name] = int(c.schedule.temporal_spacing_days * 86400)

    # Recommended actions: expand registry summary into detailed lists
    RECOMMENDED_ACTIONS[c.name] = {
        "low": [c.actions.low],
        "medium": [c.actions.medium],
        "high": [c.actions.high],
    }

# Enrich with domain-specific details that the registry summary doesn't cover
RECOMMENDED_ACTIONS["water"]["medium"] = [
    RECOMMENDED_ACTIONS["water"]["medium"][0],
    "Increase chlorine dosing at nearest treatment plant.",
]
RECOMMENDED_ACTIONS["water"]["high"] = [
    "Upsize pipe to 300 mm (Nairobi Water Master Plan pg. 42).",
    "Activate emergency inter-zone transfer valves.",
    "Deploy mobile water tankers to affected area.",
    "Trigger EPANET re-optimisation for pressure zone.",
]
RECOMMENDED_ACTIONS["power"]["medium"] = [
    RECOMMENDED_ACTIONS["power"]["medium"][0],
    "Re-route up to 15% load to adjacent feeders.",
]
RECOMMENDED_ACTIONS["power"]["high"] = [
    "Initiate load-shedding schedule for affected substation.",
    "Dispatch mobile generator units (200 kVA minimum).",
    "Notify Kenya Power regional control centre.",
    "Fast-track 66 kV feeder upgrade (Kenya Power Master Plan).",
]
RECOMMENDED_ACTIONS["roads"]["medium"] = [
    "Adjust signal timing plans on affected corridor.",
    "Deploy traffic marshals during peak hours.",
]
RECOMMENDED_ACTIONS["roads"]["high"] = [
    "Activate BRT feeder re-routing protocol.",
    "Implement contraflow lane during AM peak.",
    "Notify Nairobi Metropolitan Services (NMS) traffic control.",
    "Publish congestion advisory via Sindio dashboard.",
]
RECOMMENDED_ACTIONS["solid_waste"]["medium"] = [
    RECOMMENDED_ACTIONS["solid_waste"]["medium"][0],
    "Notify county environmental officers.",
]
RECOMMENDED_ACTIONS["solid_waste"]["high"] = [
    "Deploy emergency waste removal contractor.",
    "Activate Dandora dumpsite diversion protocol.",
    "Issue public health advisory for affected area.",
]
RECOMMENDED_ACTIONS["sidewalks"]["medium"] = [
    RECOMMENDED_ACTIONS["sidewalks"]["medium"][0],
    "Deploy temporary pedestrian barriers in high-wear zones.",
]
RECOMMENDED_ACTIONS["sidewalks"]["high"] = [
    "Close affected walkway section for emergency repair.",
    "Activate pedestrian diversion routing.",
    "Notify Nairobi County NMT coordinator.",
]
RECOMMENDED_ACTIONS["lrt"]["medium"] = [
    RECOMMENDED_ACTIONS["lrt"]["medium"][0],
    "Notify Kenya Railways LRT operations centre.",
]
RECOMMENDED_ACTIONS["lrt"]["high"] = [
    "Initiate emergency braking protocol on affected section.",
    "Dispatch mobile maintenance crew to track segment.",
    "Issue passenger advisory via station displays.",
]
RECOMMENDED_ACTIONS["sgr"]["medium"] = [
    "Schedule track geometry inspection within 48 hours.",
    RECOMMENDED_ACTIONS["sgr"]["medium"][0],
]
RECOMMENDED_ACTIONS["sgr"]["high"] = [
    "Halt all traffic on affected track section.",
    "Activate emergency response protocol (Kenya Railways SGR Ops).",
    "Notify NMS transit coordination centre.",
]
RECOMMENDED_ACTIONS["airports"]["medium"] = [
    "Schedule runway friction test within 24 hours.",
    "Notify air traffic control of reduced ops capacity.",
]
RECOMMENDED_ACTIONS["airports"]["high"] = [
    "Close affected runway for emergency inspection.",
    "Activate contingency flight plan (KCAA protocol).",
    "Notify Kenya Airports Authority emergency desk.",
    "Deploy mobile runway lighting system.",
]


# ──────────────────────────────────────────────────────────────
# Alert data class
# ──────────────────────────────────────────────────────────────


@dataclass
class Alert:
    infrastructure_type: str
    asset_id: str
    severity: float
    classification_type: Optional[str]
    classification_confidence: Optional[float]
    location_lon: float
    location_lat: float
    recommended_action: str
    previous_stress: float
    current_stress: float
    stress_delta_24h: float
    trigger_reason: str

    def to_dict(self) -> Dict[str, Any]:
        interval_seconds = TEMPORAL_SPACING.get(self.infrastructure_type, 86400)
        next_update = (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).isoformat()

        return {
            "id": str(uuid.uuid4()),
            "infrastructure_type": self.infrastructure_type,
            "asset_id": self.asset_id,
            "severity": round(self.severity, 4),
            "classification": {
                "type": self.classification_type or "unclassified",
                "confidence": round(self.classification_confidence or 0.0, 4),
            },
            "location": {
                "type": "Point",
                "coordinates": [round(self.location_lon, 6), round(self.location_lat, 6)],
            },
            "recommended_action": self.recommended_action,
            "temporal_spacing": {
                "interval_seconds": interval_seconds,
                "next_update": next_update,
            },
            "trigger_reason": self.trigger_reason,
            "stress_delta_24h": round(self.stress_delta_24h, 4),
        }


# ──────────────────────────────────────────────────────────────
# Alert Generator
# ──────────────────────────────────────────────────────────────


class AlertGenerator:
    """Generates temporally spaced alerts from simulation output.

    Compares current stress values against historical values stored
    in TimescaleDB to detect sudden changes, critical thresholds,
    and classification shifts.
    """

    SUDDEN_CHANGE_THRESHOLD = 0.2
    CRITICAL_STRESS_THRESHOLD = 0.85

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or self._get_db_url()
        self._redis: Any = None

    # ── Public API ───────────────────────────────────────────

    def poll_and_generate(self) -> List[Dict[str, Any]]:
        """Main entry point — poll simulation output and generate alerts.

        Called every 5 minutes by Celery Beat.
        Returns list of alert dicts suitable for API response.
        """
        logger.info("Polling simulation outputs for alert conditions…")

        # 1. Fetch latest simulation results
        current = self._fetch_latest_simulations()

        # 2. Fetch 24h-ago values for delta comparison
        previous = self._fetch_historical_simulations(
            since=datetime.now(timezone.utc) - timedelta(hours=24)
        )

        # 3. Fetch last known classification per asset
        last_classifications = self._fetch_last_classifications()

        # 4. Generate alerts
        alerts: List[Alert] = []

        for asset_id, curr_row in current.items():
            prev_row = previous.get(asset_id, {})

            curr_stress = float(curr_row.get("stress_physics", curr_row.get("stress_ml", 0.0)))
            prev_stress = float(prev_row.get("stress_physics", prev_row.get("stress_ml", curr_stress)))
            stress_delta = curr_stress - prev_stress

            infra_type = curr_row.get("asset_type", "water")

            # Trigger 1: Sudden change
            if abs(stress_delta) > self.SUDDEN_CHANGE_THRESHOLD:
                alert = self._build_alert(
                    asset_id=asset_id,
                    infra_type=infra_type,
                    curr_stress=curr_stress,
                    prev_stress=prev_stress,
                    stress_delta=stress_delta,
                    trigger_reason="sudden_change",
                    current_row=curr_row,
                    last_classifications=last_classifications,
                )
                alerts.append(alert)

            # Trigger 2: Critical threshold
            elif curr_stress > self.CRITICAL_STRESS_THRESHOLD:
                alert = self._build_alert(
                    asset_id=asset_id,
                    infra_type=infra_type,
                    curr_stress=curr_stress,
                    prev_stress=prev_stress,
                    stress_delta=stress_delta,
                    trigger_reason="critical_threshold",
                    current_row=curr_row,
                    last_classifications=last_classifications,
                )
                alerts.append(alert)

            # Trigger 3: Classification change
            curr_classification = curr_row.get("classification_type")
            prev_classification = last_classifications.get(asset_id, {}).get("classification_type")

            if (
                curr_classification
                and prev_classification
                and curr_classification != prev_classification
                and curr_classification != "unclassified"
            ):
                alert = self._build_alert(
                    asset_id=asset_id,
                    infra_type=infra_type,
                    curr_stress=curr_stress,
                    prev_stress=prev_stress,
                    stress_delta=stress_delta,
                    trigger_reason=f"reclassification:{prev_classification}→{curr_classification}",
                    current_row=curr_row,
                    last_classifications=last_classifications,
                )
                alerts.append(alert)

        if not alerts:
            logger.info("No alert conditions detected across %d assets.", len(current))
            return []

        # 4. Check temporal spacing — skip if too soon for this type
        last_alert_times = self._fetch_last_alert_timestamps()
        filtered: List[Alert] = []

        for alert in alerts:
            last_ts = last_alert_times.get(alert.asset_id)
            if last_ts is not None:
                interval = timedelta(seconds=TEMPORAL_SPACING.get(alert.infrastructure_type, 86400))
                if datetime.now(timezone.utc) - last_ts < interval:
                    logger.debug("Skipping alert for %s — still within spacing window.", alert.asset_id)
                    continue

            filtered.append(alert)

        # 5. Persist to TimescaleDB
        stored = self._store_alerts(filtered)

        # 6. Publish to Redis pub/sub
        alert_dicts = [a.to_dict() for a in filtered]
        self._publish_realtime(alert_dicts)

        # 6b. Index asynchronously in Elasticsearch for hybrid search
        self._index_alerts_async(alert_dicts)

        # 7. Generate RAG-based explanations for each alert
        for alert_d in alert_dicts:
            self._generate_explanation(alert_d)

        logger.info(
            "Generated %d alerts (%d stored, %d throttled).",
            len(filtered), stored, len(alerts) - len(filtered),
        )
        return alert_dicts

    # ── Alert construction ───────────────────────────────────

    def _build_alert(
        self,
        asset_id: str,
        infra_type: str,
        curr_stress: float,
        prev_stress: float,
        stress_delta: float,
        trigger_reason: str,
        current_row: Dict[str, Any],
        last_classifications: Dict[str, Dict[str, Any]],
    ) -> Alert:
        """Build an Alert object from a trigger condition."""
        severity = min(1.0, max(0.0, curr_stress))

        # Determine severity tier for action recommendation
        if severity > 0.85:
            tier = "high"
        elif severity > 0.5:
            tier = "medium"
        else:
            tier = "low"

        actions = RECOMMENDED_ACTIONS.get(infra_type, {}).get(tier, ["Investigate."])
        import random
        action = random.choice(actions)

        classification = current_row.get("classification_type")
        confidence = current_row.get("confidence")

        lat = float(current_row.get("lat", -1.29))
        lon = float(current_row.get("lon", 36.82))

        return Alert(
            infrastructure_type=infra_type,
            asset_id=asset_id,
            severity=severity,
            classification_type=classification,
            classification_confidence=confidence,
            location_lon=lon,
            location_lat=lat,
            recommended_action=action,
            previous_stress=prev_stress,
            current_stress=curr_stress,
            stress_delta_24h=stress_delta,
            trigger_reason=trigger_reason,
        )

    # ── TimescaleDB persistence ──────────────────────────────

    def _store_alerts(self, alerts: List[Alert]) -> int:
        """Batch-insert alerts into TimescaleDB hypertable."""
        if not alerts:
            return 0

        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            count = 0

            with engine.begin() as conn:
                for alert in alerts:
                    conn.execute(
                        text("""
                            INSERT INTO alerts
                                (id, level, category, title, description,
                                 infrastructure_type, asset_id, severity,
                                 classification_type, classification_confidence,
                                 location, recommended_action, temporal_spacing,
                                 previous_stress, current_stress, stress_delta_24h,
                                 trigger_reason, node_id, created_at)
                            VALUES
                                (:id, :level, :category, :title, :description,
                                 :infra_type, :asset_id, :severity,
                                 :class_type, :class_conf,
                                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                                 :action, :temporal_spacing::jsonb,
                                 :prev_stress, :curr_stress, :delta,
                                 :reason, :node_id, NOW())
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "level": "critical" if alert.severity >= 0.8 else ("warning" if alert.severity >= 0.5 else "advisory"),
                            "category": alert.infrastructure_type,
                            "title": f"{alert.infrastructure_type.title()} Stress Alert",
                            "description": alert.recommended_action or "",
                            "infra_type": alert.infrastructure_type,
                            "asset_id": alert.asset_id,
                            "severity": alert.severity,
                            "class_type": alert.classification_type,
                            "class_conf": alert.classification_confidence,
                            "lon": alert.location_lon,
                            "lat": alert.location_lat,
                            "action": alert.recommended_action,
                            "temporal_spacing": json.dumps(
                                alert.to_dict()["temporal_spacing"]
                            ),
                            "prev_stress": alert.previous_stress,
                            "curr_stress": alert.current_stress,
                            "delta": alert.stress_delta_24h,
                            "reason": alert.trigger_reason,
                            "node_id": alert.asset_id,  # FK to infrastructure_nodes
                        },
                    )
                    count += 1

            logger.info("Stored %d alerts in TimescaleDB.", count)
            return count

        except Exception as exc:
            logger.error("Failed to store alerts in TimescaleDB: %s", exc)
            return 0

    # ── RAG-based explanation ────────────────────────────────

    def _generate_explanation(self, alert_dict: Dict[str, Any]):
        """Generate and persist a RAG-based explanation for a fired alert.

        Retrieves similar historical alerts, planning docs, and maintenance
        records, then generates explanation text via LLM (or template fallback).
        """
        try:
            from app.services.explanation_generator import explain_alert

            interval = TEMPORAL_SPACING.get(
                alert_dict.get("infrastructure_type", "water"), 86400
            )
            explain_alert(alert_dict, temporal_spacing_seconds=interval)
        except Exception as exc:
            logger.warning("Explanation generation skipped for %s: %s",
                          alert_dict.get("id", "?"), exc)

    # ── Redis pub/sub ────────────────────────────────────────

    def _publish_realtime(self, alerts: List[Dict[str, Any]]):
        """Publish alerts to Redis pub/sub channel for WebSocket push."""
        if not alerts:
            return

        try:
            r = self._get_redis()
            channel = "alerts:realtime"
            for alert in alerts:
                payload = json.dumps(alert)
                r.publish(channel, payload)
            logger.info("Published %d alerts to Redis channel '%s'.", len(alerts), channel)
        except Exception as exc:
            logger.error("Redis publish failed: %s", exc)

    def _index_alerts_async(self, alerts: List[Dict[str, Any]]):
        """Fire-and-forget Celery task to index alerts in Elasticsearch."""
        if not alerts:
            return
        try:
            from .search_service import index_alert_bulk_sync

            if hasattr(index_alert_bulk_sync, 'delay'):
                index_alert_bulk_sync.delay(alerts)
            else:
                logger.debug("Celery not available — alert indexing skipped for %d alerts", len(alerts))
        except Exception as exc:
            logger.warning("Failed to enqueue ES indexing task: %s", exc)

    def _get_redis(self):
        if self._redis is None:
            import redis as redis_lib

            self._redis = redis_lib.Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
        return self._redis

    # ── TimescaleDB queries ──────────────────────────────────

    def _fetch_latest_simulations(self) -> Dict[str, Dict[str, Any]]:
        """Fetch the most recent simulation results per asset."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT DISTINCT ON (asset_id)
                            asset_id, asset_type, stress_physics, stress_ml,
                            ST_X(geometry::geometry) AS lon,
                            ST_Y(geometry::geometry) AS lat,
                            classification_type, confidence, failure_mode
                        FROM stress_classifications
                        ORDER BY asset_id, updated_at DESC
                    """)
                ).fetchall()

            return {
                row.asset_id: {
                    "asset_id": row.asset_id,
                    "asset_type": row.asset_type or "power",
                    "stress_physics": float(row.stress_physics or 0.0),
                    "stress_ml": float(row.stress_ml or 0.0),
                    "lon": float(row.lon or 36.82),
                    "lat": float(row.lat or -1.29),
                    "classification_type": row.classification_type,
                    "confidence": float(row.confidence or 0.0),
                    "failure_mode": row.failure_mode,
                }
                for row in rows
            }
        except Exception as exc:
            logger.warning("Failed to fetch latest simulations: %s", exc)
            return {}

    def _fetch_historical_simulations(
        self, since: datetime
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch simulation results from `since` for delta comparison."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT DISTINCT ON (asset_id)
                            asset_id, stress_physics, stress_ml, updated_at
                        FROM stress_classifications
                        WHERE updated_at <= :since
                        ORDER BY asset_id, updated_at DESC
                    """),
                    {"since": since},
                ).fetchall()

            return {
                row.asset_id: {
                    "stress_physics": float(row.stress_physics or 0.0),
                    "stress_ml": float(row.stress_ml or 0.0),
                    "updated_at": row.updated_at,
                }
                for row in rows
            }
        except Exception as exc:
            logger.warning("Failed to fetch historical simulations: %s", exc)
            return {}

    def _fetch_last_classifications(self) -> Dict[str, Dict[str, Any]]:
        """Fetch the second-most-recent classification per asset for change detection."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        WITH ranked AS (
                            SELECT
                                asset_id, classification_type, confidence,
                                ROW_NUMBER() OVER (
                                    PARTITION BY asset_id ORDER BY updated_at DESC
                                ) AS rn
                            FROM stress_classifications
                        )
                        SELECT asset_id, classification_type, confidence
                        FROM ranked WHERE rn = 2
                    """)
                ).fetchall()

            return {
                row.asset_id: {
                    "classification_type": row.classification_type,
                    "confidence": row.confidence,
                }
                for row in rows
            }
        except Exception as exc:
            logger.warning("Failed to fetch last classifications: %s", exc)
            return {}

    def _fetch_last_alert_timestamps(self) -> Dict[str, datetime]:
        """Fetch most recent alert timestamp per asset for temporal spacing."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT DISTINCT ON (asset_id)
                            asset_id, created_at
                        FROM alerts
                        ORDER BY asset_id, created_at DESC
                    """)
                ).fetchall()

            return {
                row.asset_id: row.created_at.replace(tzinfo=timezone.utc)
                for row in rows
                if row.created_at is not None
            }
        except Exception as exc:
            logger.warning("Failed to fetch last alert timestamps: %s", exc)
            return {}

    @staticmethod
    def _get_db_url() -> str:
        return os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )


# ──────────────────────────────────────────────────────────────
# Celery periodic task (graceful fallback when celery unavailable)
# ──────────────────────────────────────────────────────────────


def _get_alert_app():
    try:
        from celery import Celery
    except ImportError:
        return None

    broker = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    app = Celery(
        "sindio_alert_gen",
        broker=broker,
        backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
        task_serializer="json",
        accept_content=["json"],
    )
    app.conf.update(
        task_default_queue="sindio_alerts",
        timezone="Africa/Nairobi",
        enable_utc=True,
        beat_schedule={
            "poll-simulation-outputs": {
                "task": "sindio.generate_alerts",
                "schedule": timedelta(minutes=5),
                "options": {"queue": "sindio_alerts"},
            },
        },
    )
    return app


alert_app = _get_alert_app()


def _register_task(func):
    """Decorator that registers a Celery task if celery is available, else no-op."""
    if alert_app is None:
        return func
    return alert_app.task(
        bind=True,
        name="sindio.generate_alerts",
        max_retries=1,
        acks_late=True,
    )(func)


@_register_task
def generate_alerts_task(self=None) -> List[Dict[str, Any]]:
    """Celery task — poll simulation outputs and generate alerts."""
    generator = AlertGenerator()
    return generator.poll_and_generate()
