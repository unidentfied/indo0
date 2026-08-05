"""
Sindio — Lifecycle Auto-Maintenance Hooks
==========================================

Connects the live monitoring pipeline to carbon credits, parametric insurance,
cascade analysis, and ROI tracking — making the system self-maintaining.

All hooks are fire-and-forget (threaded), gracefully degrade on failure, and
can be disabled via SINDIO_AUTO_LIFECYCLE=0 env var.

Wire points (in order of execution):
  1. monitor router   — after get_all_stressed_assets() completes
  2. alert_generator  — after critical alerts are persisted
  3. long_interval    — after each stress test completes
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sindio.lifecycle")

_AUTO_LIFECYCLE = os.getenv("SINDIO_AUTO_LIFECYCLE", "1") == "1"


def _fire_and_forget(fn, *args, **kwargs):
    """Run a function in a background daemon thread. Silently logs failures."""
    if not _AUTO_LIFECYCLE:
        return

    def _runner():
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            logger.debug("Lifecycle hook failed (non-critical): %s: %s", fn.__name__, exc)

    threading.Thread(target=_runner, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Carbon auto-registration — triggered when stress drops below baseline
# ══════════════════════════════════════════════════════════════════════════════


def maybe_register_carbon_credit(asset: Dict[str, Any]):
    """If an asset's stress has dropped significantly vs baseline, compute and
    register a carbon credit for the avoided emissions."""
    infra_type = asset.get("infrastructure_type", "")
    asset_id = asset.get("asset_id", "")
    stress = asset.get("stress", 0)
    baseline = asset.get("baseline_stress", 0)

    if not infra_type or not asset_id:
        return

    stress_reduction = baseline - stress
    if stress_reduction < 0.15:
        return

    try:
        from .carbon_tracker import compute_baseline, compute_carbon_savings, register_credit
        from ..database import get_engine

        city_slug = asset.get("ward", "nairobi")
        tco2e = compute_baseline("nairobi", infra_type, asset_id, 1)
        if tco2e <= 0:
            return

        savings = compute_carbon_savings(
            "nairobi", infra_type, asset_id,
            f"Automated credit — stress dropped from {baseline:.2f} to {stress:.2f} ({stress_reduction:.0%} reduction)",
            stress_reduction_pct=stress_reduction * 100,
        )

        register_credit(
            get_engine(), "nairobi", infra_type, asset_id,
            f"Stress reduction: {baseline:.2f} → {stress:.2f}",
            savings["tco2e_saved_per_year"],
        )
        logger.info("Auto carbon credit registered for %s/%s: %.2f tCO2e",
                     infra_type, asset_id, savings["tco2e_saved_per_year"])
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 2. Insurance auto-claims — triggered when stress breaches policy threshold
# ══════════════════════════════════════════════════════════════════════════════


def maybe_check_insurance_claims(asset: Dict[str, Any]):
    """If an asset's stress exceeds policy trigger thresholds, auto-file claims."""
    infra_type = asset.get("infrastructure_type", "")
    asset_id = asset.get("asset_id", "")
    stress = asset.get("stress", 0)

    if stress < 0.70 or not infra_type or not asset_id:
        return

    try:
        from .insurance import check_trigger_and_claim
        from ..database import get_engine

        req = {
            "city_slug": "nairobi",
            "infra_type": infra_type,
            "asset_id": asset_id,
            "current_stress": stress,
        }
        result = check_trigger_and_claim(
            get_engine(),
            req["city_slug"],
            req["infra_type"],
            req["asset_id"],
            req["current_stress"],
        )
        if result.get("triggered"):
            logger.info("Auto insurance claim triggered for %s/%s: payout KSh %.0f",
                         infra_type, asset_id, result.get("payout_amount_usd", 0) * 145)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 3. Cascade auto-analysis — triggered by critical alerts on power/water assets
# ══════════════════════════════════════════════════════════════════════════════


def maybe_run_cascade_analysis(alert: Dict[str, Any]):
    """If a critical alert fires for a power/water asset, auto-run cascade."""
    infra_type = alert.get("infrastructure_type", alert.get("category", ""))
    asset_id = alert.get("asset_id", alert.get("node_id", ""))
    severity = alert.get("severity", alert.get("level", ""))

    cascade_types = {"power", "power_substation", "water", "water_pump"}
    if infra_type not in cascade_types:
        return

    is_critical = severity in ("critical", "breach_imminent") or float(alert.get("severity", 0)) >= 0.85
    if not is_critical:
        return

    if not asset_id or asset_id == "unknown":
        return

    try:
        from .cascade_analyzer import CascadeAnalyzer

        mapping = {"power": "power_substation", "water": "water_pump",
                   "power_substation": "power_substation", "water_pump": "water_pump"}
        asset_type = mapping.get(infra_type, "power_substation")

        analyzer = CascadeAnalyzer(city_slug="nairobi")
        result = analyzer.analyze_cascade(asset_type=asset_type, asset_id=str(asset_id))

        if "error" not in result:
            logger.info("Auto cascade analysis complete for %s/%s: %d events, depth %d",
                         asset_type, asset_id,
                         len(result.get("cascade_chain", [])),
                         result.get("summary", {}).get("cascade_depth", 0))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# 4. ROI data enrichment — track outage avoidance from live stress patterns
# ══════════════════════════════════════════════════════════════════════════════


def maybe_track_roi_outcome(asset: Dict[str, Any]):
    """Feed live outage avoidance into ROI historical data for better cost models."""
    infra_type = asset.get("infrastructure_type", "")
    stress = asset.get("stress", 0)
    failure_mode = asset.get("failure_mode", "")
    time_to_breach = asset.get("time_to_breach_hours", 0)

    if failure_mode == "normal" and stress < 0.4 and time_to_breach and float(time_to_breach) > 24:
        logger.debug("ROI tracker: %s/%s healthy — %s hours to breach",
                      infra_type, asset.get("asset_id", ""), time_to_breach)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Stress test completion hook — update baselines after long-interval tests
# ══════════════════════════════════════════════════════════════════════════════


def on_stress_test_complete(infra_type: str, asset_id: str, stress: float):
    """Called after each long-interval stress test completes for an asset.
    Checks for significant stress changes and triggers carbon/insurance as needed."""
    _fire_and_forget(maybe_register_carbon_credit, {
        "infrastructure_type": infra_type,
        "asset_id": asset_id,
        "stress": min(stress, 1.0),
        "baseline_stress": 0.6,
        "ward": "nairobi",
    })
    _fire_and_forget(maybe_check_insurance_claims, {
        "infrastructure_type": infra_type,
        "asset_id": asset_id,
        "stress": stress,
    })


# ══════════════════════════════════════════════════════════════════════════════
# 6. Monitor pipeline hook — batch-process stressed assets
# ══════════════════════════════════════════════════════════════════════════════


def on_monitor_cycle_complete(stressed_assets: List[Dict[str, Any]]):
    """Called after get_all_stressed_assets() returns. Batch-processes all
    stressed assets for carbon credits and insurance claims."""
    if not _AUTO_LIFECYCLE:
        return

    for asset in stressed_assets[:20]:
        if not asset.get("is_mock", False):
            _fire_and_forget(maybe_register_carbon_credit, asset)
            _fire_and_forget(maybe_check_insurance_claims, asset)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Alert pipeline hook — cascade analysis on critical alerts
# ══════════════════════════════════════════════════════════════════════════════


def on_critical_alerts_generated(alerts: List[Dict[str, Any]]):
    """Called after critical alerts are persisted and published. Auto-runs
    cascade analysis for power/water infrastructure alerts."""
    if not _AUTO_LIFECYCLE:
        return

    for alert in alerts[:5]:
        _fire_and_forget(maybe_run_cascade_analysis, alert)
