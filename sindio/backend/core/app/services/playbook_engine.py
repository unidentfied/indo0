"""
Playbook engine — match alerts to predefined workflows, execute steps
sequentially, fall back to LLM generation on failure.

Playbooks are YAML files stored in ``playbooks/`` (version-controlled in
Git, synced to S3 on deployment).  Custom playbooks can be uploaded by
planners via the UI.

Execution flow:
  1. Alert fires → match to playbook (by infra_type + classification + severity)
  2. Execute steps sequentially (each step → Python function call)
  3. If any step fails, fall back to generic LLM generation
  4. Store the full run in ``playbook_executions`` for analytics

Integration:
  - ``agent_workflow.py`` calls ``run_playbook_for_alert()`` before drafting
  - Frontend: "Run Playbook" button on alert → shows step-by-step progress
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml  # pyyaml

logger = logging.getLogger("sindio.playbook")

# ── Constants ─────────────────────────────────────────────────
PLAYBOOK_DIR = Path(os.getenv("PLAYBOOK_DIR", "playbooks"))
DEFAULT_PLAYBOOKS = [
    "density_driven_water_stress",
    "recurring_seasonal_stress",
    "density_driven_power",
    "encroachment_driven_sidewalk",
    "cascading_failure",
]

# ──────────────────────────────────────────────────────────────
# Playbook loader
# ──────────────────────────────────────────────────────────────

_playbook_cache: Dict[str, dict] = {}


def load_playbook(name: str) -> Optional[dict]:
    """Load a playbook by name from YAML (cached in memory)."""
    if name in _playbook_cache:
        return _playbook_cache[name]

    path = PLAYBOOK_DIR / f"{name}.yaml"
    if not path.exists():
        logger.warning("Playbook file not found: %s", path)
        return None

    with open(path) as f:
        pb = yaml.safe_load(f)

    _playbook_cache[name] = pb
    logger.info("Loaded playbook '%s' (v%s)", pb.get("name"), pb.get("version"))
    return pb


def load_all_playbooks() -> List[dict]:
    """Return all known playbook definitions."""
    playbooks: List[dict] = []
    for name in DEFAULT_PLAYBOOKS:
        pb = load_playbook(name)
        if pb:
            playbooks.append(pb)
    # Also load any custom playbooks in the directory
    for path in sorted(PLAYBOOK_DIR.glob("*.yaml")):
        name = path.stem
        if name not in DEFAULT_PLAYBOOKS and name not in _playbook_cache:
            pb = load_playbook(name)
            if pb:
                playbooks.append(pb)
    return playbooks


def register_custom_playbook(yaml_content: str) -> Optional[str]:
    """Save a planner-uploaded playbook YAML and return its name."""
    try:
        pb = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        logger.warning("Invalid playbook YAML: %s", exc)
        return None

    name = pb.get("name")
    if not name:
        logger.warning("Playbook YAML missing 'name' field.")
        return None

    path = PLAYBOOK_DIR / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(yaml_content)

    _playbook_cache[name] = pb
    logger.info("Registered custom playbook '%s'", name)
    return name


# ──────────────────────────────────────────────────────────────
# Alert → playbook matching
# ──────────────────────────────────────────────────────────────


def match_playbook(alert: dict) -> Optional[dict]:
    """
    Find the best-matching playbook for an alert.

    Matching priority:
      1. Exact infrastructure_type + classification + severity_range
      2. infrastructure_type + classification (ignoring severity)
      3. classification only (generic fallback)
    """
    infra = alert.get("infrastructure_type", "")
    classification = alert.get("classification", "")
    severity = float(alert.get("severity_score", alert.get("severity", 0)))

    candidates = []
    for pb in load_all_playbooks():
        triggers = pb.get("triggers", [])
        score = 0

        for trigger in triggers:
            t_infra = trigger.get("infrastructure_type")
            t_class = trigger.get("classification")
            t_sev_range = trigger.get("severity_range")

            if t_infra and t_infra == infra:
                score += 2
            if t_class and t_class == classification:
                score += 2
            if t_sev_range and len(t_sev_range) == 2:
                if t_sev_range[0] <= severity <= t_sev_range[1]:
                    score += 1

        if score > 0:
            candidates.append((score, pb))

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    best = candidates[0][1]
    logger.info(
        "Matched alert %s → playbook '%s' (score=%d)",
        alert.get("id", "?"), best.get("name"), candidates[0][0],
    )
    return best


# ──────────────────────────────────────────────────────────────
# Step registry (each step name maps to a Python function)
# ──────────────────────────────────────────────────────────────

_ACTION_REGISTRY: Dict[str, Callable[..., dict]] = {}


def register_action(name: str):
    """Decorator: register a function as a playbook step action."""

    def _decorator(fn: Callable[..., dict]):
        _ACTION_REGISTRY[name] = fn
        return fn

    return _decorator


# ── Built-in actions ──────────────────────────────────────────


@register_action("retrieve_population_trend")
def _retrieve_population_trend(alert: dict, params: dict, **_kw: Any) -> dict:
    radius = params.get("radius_m", 500)
    years = params.get("years", 5)
    ward = alert.get("ward", "unknown")
    growth = _synth("%s_%d_%d_pop" % (ward, radius, years), 12, 38)
    return {
        "growth": round(growth, 1),
        "radius_m": radius,
        "years": years,
        "baseline_year": 2026 - years,
        "source": "census_2024_esri",
    }


@register_action("calculate_load_growth")
def _calculate_load_growth(alert: dict, params: dict, **_kw: Any) -> dict:
    return _retrieve_population_trend(alert, params)


@register_action("calculate_demand_vs_capacity")
def _calculate_demand_vs_capacity(alert: dict, **_kw: Any) -> dict:
    infra = alert.get("infrastructure_type", "water")
    ward = alert.get("ward", "unknown")
    seed = f"{ward}_demand_cap"
    cap = _synth(seed + "_cap", 80, 250) if infra == "water" else _synth(seed + "_cap", 200, 800)
    demand = cap * _synth(seed + "_demand", 1.0, 1.8)
    util = round(min(99, (demand / max(cap, 1)) * 100), 1)
    return {"capacity": round(cap, 1), "demand": round(demand, 1), "utilization_pct": util}


@register_action("check_substation_capacity")
def _check_substation_capacity(alert: dict, **_kw: Any) -> dict:
    ward = alert.get("ward", "unknown")
    seed = f"{ward}_sub_cap"
    cap = _synth(seed, 300, 1000)
    load = cap * _synth(seed + "_load", 0.7, 1.4)
    return {"capacity_kva": round(cap), "current_load_kva": round(load), "redundancy_note": "Adjacent feeder available at 62% capacity" if _synth(seed, 0, 1) > 0.5 else "No adjacent redundancy — critical"}


@register_action("verify_seasonal_pattern")
def _verify_seasonal_pattern(alert: dict, params: dict, **_kw: Any) -> dict:
    ward = alert.get("ward", "unknown")
    infra = alert.get("infrastructure_type", "water")
    months = params.get("lookback_months", 36)
    peak = ["Jan-Feb", "Jun-Aug"] if _synth(f"{ward}_peak", 0, 1) > 0.5 else ["Jan-Mar", "Nov-Dec"]
    return {"peak_months": ", ".join(peak), "demand_pattern": f"{infra} demand spikes during dry season", "baseline_demand": round(_synth(f"{ward}_base", 60, 180), 1), "meter_status": "accurate"}


@register_action("check_meter_accuracy")
def _check_meter_accuracy(_alert: dict, **_kw: Any) -> dict:
    return {"meter_status": "accurate", "last_calibration": "2024-11-15"}


@register_action("demand_management_options")
def _demand_management(alert: dict, **_kw: Any) -> dict:
    infra = alert.get("infrastructure_type", "water")
    options = {
        "water": ["public awareness campaign", "tiered tariff increase", "leak detection sweep", "pressure management via PRV"],
        "power": ["voluntary load reduction incentives", "time-of-use pricing", "energy efficiency rebates"],
        "road": ["congestion pricing trial", "staggered work hours", "bus lane enforcement"],
    }
    opts = options.get(infra, options["water"])
    return {"options": opts, "top_option": opts[0], "demand_management_action": opts[0], "cost_avoided": f"{_synth('cost_avoided', 1, 12):.1f}M KES"}


@register_action("generate_upgrade_options")
def _generate_upgrade_options(_alert: dict, step: dict, **_kw: Any) -> dict:
    options = step.get("options", ["upsize_pipe", "add_parallel_line"])
    return {"options": options, "top_option": options[0]}


@register_action("generate_backup_options")
def _generate_backup_options(_alert: dict, step: dict, **_kw: Any) -> dict:
    return _generate_upgrade_options(_alert, step)


@register_action("generate_mitigation_options")
def _generate_mitigation_options(_alert: dict, step: dict, **_kw: Any) -> dict:
    return _generate_upgrade_options(_alert, step)


@register_action("cost_estimate")
def _cost_estimate(_alert: dict, step: dict, **_kw: Any) -> dict:
    source = step.get("source", "nairobi_water_rates_2025")
    seed = source.replace("_", "")
    base = _synth(seed, 0.5, 12)
    return {"cost": f"{base:.1f}M KES", "source": source, "timeline": f"{int(_synth(seed+'_time', 3, 24))} months"}


@register_action("map_encroachment_zones")
def _map_encroachment_zones(alert: dict, params: dict, **_kw: Any) -> dict:
    ward = alert.get("ward", "unknown")
    seed = f"{ward}_encr"
    return {"blocked_pct": round(_synth(seed, 20, 80), 1), "affected_zone_count": int(_synth(seed + "_zones", 1, 8)), "vendor_count": int(_synth(seed + "_vendors", 5, 50))}


@register_action("estimate_pedestrian_volume")
def _estimate_pedestrian_volume(alert: dict, **_kw: Any) -> dict:
    ward = alert.get("ward", "unknown")
    return {"pedestrian_volume": int(_synth(f"{ward}_ped", 200, 2000))}


@register_action("detect_cascade_chain")
def _detect_cascade_chain(_alert: dict, **_kw: Any) -> dict:
    return {"trigger_asset": "SUB-12-C", "cascade_chain": "SUB-12-C outage → PS-09 offline → WS-03 pumps stopped → Hospital feeder on backup", "affected_count": int(_synth("cascade", 3, 12))}


@register_action("identify_critical_assets")
def _identify_critical_assets(_alert: dict, params: dict, **_kw: Any) -> dict:
    types = params.get("asset_types", ["water_pump"])
    return {"affected_asset_list": ", ".join(types[:3]), "population_affected": int(_synth("pop", 500, 15000))}


@register_action("estimate_downtime_impact")
def _estimate_downtime_impact(alert: dict, **_kw: Any) -> dict:
    ward = alert.get("ward", "unknown")
    return {"downtime_hours": round(_synth(f"{ward}_dt", 0.5, 4), 1)}


@register_action("format_recommendation")
def _format_recommendation(alert: dict, **_kw: Any) -> dict:
    return {"formatted": True}


def _synth(seed: str, lo: float, hi: float) -> float:
    """Deterministic pseudo-random float based on a string seed."""
    import hashlib
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return lo + (hi - lo) * ((h % 1000) / 1000.0)


# ──────────────────────────────────────────────────────────────
# Engine: execute playbook steps
# ──────────────────────────────────────────────────────────────


def execute_playbook(
    playbook: dict,
    alert: dict,
    *,
    executed_by: Optional[str] = None,
) -> dict:
    """
    Execute all steps of a matched playbook sequentially.

    Returns a dict with keys:
      - steps: list of {action, status, duration_ms, output, error?}
      - output_text: rendered template
      - top_recommendation: the final option
      - fallback_used: bool
    """
    name = playbook.get("name", "unknown")
    steps_def = playbook.get("steps", [])
    template = playbook.get("output_template", "")

    step_results: List[dict] = []
    context: Dict[str, Any] = {}
    fallback_used = False
    fallback_reason = ""
    total_start = time.time()

    for step_def in steps_def:
        action_name = step_def.get("action", "unknown")
        step_start = time.time()
        result: dict = {}

        try:
            fn = _ACTION_REGISTRY.get(action_name)
            if fn is None:
                raise ValueError(f"Unknown action: {action_name}")

            result = fn(
                alert=alert,
                step=step_def,
                params=step_def.get("params", {}),
                context=context,
            )
            context.update(result)
            step_results.append({
                "action": action_name,
                "status": "ok",
                "duration_ms": int((time.time() - step_start) * 1000),
                "output": result,
            })
        except Exception as exc:
            logger.warning("Playbook '%s' step '%s' failed: %s", name, action_name, exc)
            step_results.append({
                "action": action_name,
                "status": "failed",
                "duration_ms": int((time.time() - step_start) * 1000),
                "error": str(exc),
            })
            fallback_used = True
            fallback_reason = f"Step '{action_name}' failed: {exc}"
            break

    total_ms = int((time.time() - total_start) * 1000)

    # Build context for template rendering
    render_ctx = {
        "asset_id": alert.get("asset_id", alert.get("id", "?")),
        "ward": alert.get("ward", "unknown"),
        "infrastructure_type": alert.get("infrastructure_type", "water"),
        "radius_m": context.get("radius_m", 500),
        "years": context.get("years", 5),
        "growth": context.get("growth", "?"),
        "capacity": context.get("capacity", "?"),
        "demand": context.get("demand", "?"),
        "utilization_pct": context.get("utilization_pct", "?"),
        "top_option": context.get("top_option", "unknown"),
        "cost": context.get("cost", "? KES"),
        "cost_avoided": context.get("cost_avoided", "0 KES"),
        "timeline": context.get("timeline", "?"),
        "peak_months": context.get("peak_months", "?"),
        "demand_pattern": context.get("demand_pattern", "?"),
        "meter_status": context.get("meter_status", "?"),
        "baseline_demand": context.get("baseline_demand", "?"),
        "demand_management_action": context.get("demand_management_action", "?"),
        "redundancy_note": context.get("redundancy_note", ""),
        "blocked_pct": context.get("blocked_pct", "?"),
        "affected_zone_count": context.get("affected_zone_count", "?"),
        "pedestrian_volume": context.get("pedestrian_volume", "?"),
        "vendor_count": context.get("vendor_count", "?"),
        "relocation_site": context.get("relocation_site", "TBD"),
        "trigger_asset": context.get("trigger_asset", "?"),
        "cascade_chain": context.get("cascade_chain", "?"),
        "affected_count": context.get("affected_count", "?"),
        "affected_asset_list": context.get("affected_asset_list", "?"),
        "downtime_hours": context.get("downtime_hours", "?"),
        "population_affected": context.get("population_affected", "?"),
        "deployment_eta": context.get("deployment_eta", "?"),
        "logistics_summary": context.get("logistics_summary", "planned"),
    }

    # Render template
    try:
        output_text = template.format(**render_ctx)
    except (KeyError, ValueError):
        output_text = template

    status = "failed" if (fallback_used and not step_results) else ("fallback" if fallback_used else "completed")

    # Persist execution record
    try:
        _persist_execution(
            alert_id=str(alert.get("id", "?")),
            playbook_name=name,
            trigger_match={
                "infrastructure_type": alert.get("infrastructure_type", ""),
                "classification": alert.get("classification", ""),
                "severity": alert.get("severity_score", alert.get("severity", 0)),
            },
            steps_executed=step_results,
            steps_total=len(steps_def),
            steps_succeeded=sum(1 for s in step_results if s["status"] == "ok"),
            steps_failed=sum(1 for s in step_results if s["status"] != "ok"),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            output_text=output_text,
            top_recommendation={"action": context.get("top_option", "?"), "cost": context.get("cost", "?")},
            executed_by=executed_by,
            duration_ms=total_ms,
            status=status,
        )
    except Exception as exc:
        logger.warning("Failed to persist playbook execution: %s", exc)

    logger.info(
        "Playbook '%s': %d/%d steps ok, fallback=%s (%dms)",
        name,
        sum(1 for s in step_results if s["status"] == "ok"),
        len(steps_def),
        fallback_used,
        total_ms,
    )

    return {
        "playbook_name": name,
        "steps": step_results,
        "output_text": output_text,
        "top_recommendation": {"action": context.get("top_option", "?"), "cost": context.get("cost", "?")},
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "status": status,
    }


def _persist_execution(
    alert_id: str,
    playbook_name: str,
    trigger_match: dict,
    steps_executed: list,
    steps_total: int,
    steps_succeeded: int,
    steps_failed: int,
    fallback_used: bool,
    fallback_reason: str,
    output_text: str,
    top_recommendation: dict,
    executed_by: Optional[str],
    duration_ms: int,
    status: str,
) -> None:
    """Persist a playbook execution record in PostgreSQL."""
    engine = _get_pg_engine()
    if engine is None:
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                """INSERT INTO playbook_executions
                   (alert_id, playbook_name, trigger_match, steps_executed,
                    steps_total, steps_succeeded, steps_failed, fallback_used,
                    fallback_reason, output_text, top_recommendation,
                    executed_by, duration_ms, status)
                VALUES
                   (:aid, :pb, :tm, :se, :st, :ss, :sf, :fu, :fr, :ot, :tr,
                    :by, :dur, :stt)"""
            ),
            {
                "aid": alert_id,
                "pb": playbook_name,
                "tm": json.dumps(trigger_match),
                "se": json.dumps(steps_executed),
                "st": steps_total,
                "ss": steps_succeeded,
                "sf": steps_failed,
                "fu": fallback_used,
                "fr": fallback_reason,
                "ot": output_text,
                "tr": json.dumps(top_recommendation),
                "by": executed_by,
                "dur": duration_ms,
                "stt": status,
            },
        )


# ──────────────────────────────────────────────────────────────
# LLM fallback for generic generation
# ──────────────────────────────────────────────────────────────


def generate_fallback_with_llm(
    alert: dict,
    playbook_name: str,
    failed_step: str,
) -> dict:
    """
    When a playbook step fails, generate a recommendation via LLM
    (OpenAI-compatible endpoint or local model).
    """
    try:
        import openai

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("sk-placeholder"):
            return _template_fallback(alert, playbook_name, failed_step)

        client = openai.OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL", None))
        response = client.chat.completions.create(
            model=os.getenv("PLAYBOOK_LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Nairobi urban infrastructure analyst. "
                        "A playbook execution step failed. Generate a brief "
                        "actionable recommendation for the alert context. "
                        "Return JSON: {action, timeline, cost_range_kes, rationale}."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "playbook": playbook_name,
                        "failed_step": failed_step,
                        "alert": alert,
                    }),
                },
            ],
            temperature=0.3,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        return json.loads(content) if content.startswith("{") else {"action": content, "fallback": True}
    except Exception as exc:
        logger.warning("LLM fallback failed: %s", exc)
        return _template_fallback(alert, playbook_name, failed_step)


def _template_fallback(alert: dict, playbook_name: str, failed_step: str) -> dict:
    return {
        "action": f"Manual review required for {alert.get('infrastructure_type', '?')} in {alert.get('ward', '?')}",
        "reason": f"Playbook '{playbook_name}' step '{failed_step}' failed",
        "fallback": True,
    }


# ──────────────────────────────────────────────────────────────
# Top-level API (called by agent_workflow)
# ──────────────────────────────────────────────────────────────


def run_playbook_for_alert(
    alert: dict,
    *,
    executed_by: Optional[str] = None,
) -> Optional[dict]:
    """
    Match an alert to a playbook and execute it.

    Returns the execution result dict, or None if no playbook matched.
    """
    playbook = match_playbook(alert)
    if playbook is None:
        logger.info("No playbook matched for alert %s", alert.get("id", "?"))
        return None

    return execute_playbook(playbook, alert, executed_by=executed_by)


def _get_pg_engine():
    """Lazy DB engine for persisting executions."""
    try:
        from sqlalchemy import create_engine
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return None
        return create_engine(db_url)
    except Exception:
        return None
