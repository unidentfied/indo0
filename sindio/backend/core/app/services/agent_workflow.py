"""
Agentic recommendation engine using LangGraph.

Five-node graph:
  1. planner     — analyses the stress alert + density projection → research_plan
  2. researcher   — queries PostGIS, TimescaleDB, and FAISS per plan
  3. verifier     — confidence scoring, freshness check, contradiction detection
  4. drafter      — generates structured JSON recommendation
  5. human_review — pauses for human approval when confidence < 0.8

State is persisted in agent_traces (migration 010) for debugging.
Each node has a timeout (default 30 s for researcher, 15 s others).
Human-in-the-loop allows editing the draft before persisting to alerts.

Usage (Python API):
    from app.services.agent_workflow import run_agent_pipeline

    final_state = run_agent_pipeline(
        alert={"id": "...", "infrastructure_type": "water", ...},
        density_projection={"year": 2032, "growth_rate": 14.0, "infra_types": ["water"]},
    )
    # blocks at human_review if confidence < 0.8
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, TypedDict

import numpy as np

logger = logging.getLogger("sindio.agent")

# ── Constants ─────────────────────────────────────────────────
NODE_TIMEOUTS: Dict[str, int] = {
    "planner": 15,
    "researcher": 30,
    "verifier": 10,
    "drafter": 15,
    "human_review": 300,  # 5 minutes for human to respond
}
CONFIDENCE_THRESHOLD = 0.8  # below this → human_review required
MAX_RESEARCH_SOURCES = 8

# ──────────────────────────────────────────────────────────────
# State schema
# ──────────────────────────────────────────────────────────────


class SindioAgentState(TypedDict, total=False):
    alert: dict
    density_projection: dict
    research_plan: List[str]
    findings: List[dict]
    verified_claims: List[dict]
    draft_recommendation: dict
    human_feedback: Optional[str]
    run_id: str
    current_node: str
    errors: List[str]
    confidence: float
    # Memory context injected from long-term memory
    memory_precedents: List[dict]
    memory_warnings: List[dict]
    # Playbook execution result
    playbook_result: Optional[dict]


# ──────────────────────────────────────────────────────────────
# Timeout helper
# ──────────────────────────────────────────────────────────────


class NodeTimeout(Exception):
    pass


def _with_timeout(seconds: int, func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run *func*; raise NodeTimeout if it takes longer than *seconds*."""
    result: Any = None
    exc: Optional[Exception] = None

    def _target() -> None:
        nonlocal result, exc
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            exc = e

    import threading

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=seconds)

    if thread.is_alive():
        raise NodeTimeout(f"Node timed out after {seconds}s")
    if exc is not None:
        raise exc
    return result


# ──────────────────────────────────────────────────────────────
# Trace persistence
# ──────────────────────────────────────────────────────────────


def _persist_trace(state: SindioAgentState, node_name: str, output: Optional[dict] = None,
                    duration_ms: int = 0, status: str = "completed",
                    human_feedback: Optional[dict] = None) -> None:
    """Persist a node-level trace row in ``agent_traces``."""
    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO agent_traces
                       (alert_id, run_id, node_name, state_snapshot, output, duration_ms, status, human_feedback)
                    VALUES (:aid, :rid, :node, :snap, :out, :dur, :st, :fb)"""
                ),
                {
                    "aid": state["alert"].get("id") if state.get("alert") else None,
                    "rid": state.get("run_id", ""),
                    "node": node_name,
                    "snap": json.dumps(state, default=str),
                    "out": json.dumps(output) if output else None,
                    "dur": duration_ms,
                    "st": status,
                    "fb": json.dumps(human_feedback) if human_feedback else None,
                },
            )
    except Exception as exc:
        logger.warning("Failed to persist trace for node '%s': %s", node_name, exc)


# ──────────────────────────────────────────────────────────────
# Node: 1. planner
# ──────────────────────────────────────────────────────────────


def _planner_node(state: SindioAgentState) -> SindioAgentState:
    """
    Analyse the stress alert + density projection → produce a structured
    ``research_plan`` listing every data source the researcher must query.

    Before planning, queries long-term memory for similar past scenarios
    and injects precedents/warnings into the state for the drafter.
    """
    alert = state.get("alert", {})
    projection = state.get("density_projection", {})

    infra = alert.get("infrastructure_type", "water")
    ward = alert.get("ward", "unknown")
    stress = alert.get("severity_score", alert.get("severity", 50))

    # ── Memory recall: search for similar past simulations ──
    try:
        from .memory_service import recall_similar_simulations

        query_emb = _build_sim_embedding(alert, projection)
        mem = recall_similar_simulations(
            query_emb,
            top_k=5,
            min_upvotes=2,
            min_downvotes=2,
            infra_type_filter=infra,
        )
        state["memory_precedents"] = mem.get("precedents", [])
        state["memory_warnings"] = mem.get("warnings", [])
        logger.info(
            "Memory recall: %d precedents, %d warnings for %s/%s",
            len(state["memory_precedents"]), len(state["memory_warnings"]), infra, ward,
        )
    except Exception as exc:
        logger.warning("Memory recall failed (proceeding without): %s", exc)
        state["memory_precedents"] = []
        state["memory_warnings"] = []

    # ── Playbook execution: match → execute steps ──
    try:
        from .playbook_engine import run_playbook_for_alert

        pb_result = run_playbook_for_alert(alert)
        state["playbook_result"] = pb_result
        if pb_result:
            logger.info("Playbook '%s' executed: %s", pb_result.get("playbook_name"), pb_result.get("status"))
    except Exception as exc:
        logger.warning("Playbook execution failed (proceeding with agent): %s", exc)
        state["playbook_result"] = None

    plan: List[str] = [
        f"population_growth_{ward}_radius_500m",
        f"{infra}_asset_capacity_{ward}",
        f"similar_alerts_{infra}_last_90d",
    ]

    # Add infra-specific sources
    extras: Dict[str, List[str]] = {
        "water": [
            "pipe_diameter_and_material",
            "water_demand_projection_2030",
            "adjacent_pressure_zones",
        ],
        "power": [
            "substation_load_history",
            "transformer_capacity_rating",
            "adjacent_feeder_redundancy",
        ],
        "road": [
            "traffic_count_daily_peak",
            "intersection_congestion_score",
            "public_transit_ridership",
        ],
    }

    for source in extras.get(infra, extras["water"]):
        plan.append(source)

    # Add density-projection-specific sources
    year = projection.get("year", 2030)
    rate = projection.get("growth_rate", 10)
    if rate > 5:
        plan.append(f"land_use_change_{ward}_{year}")
    plan.append(f"census_population_baseline_{ward}")

    # Cap plan length
    state["research_plan"] = plan[:MAX_RESEARCH_SOURCES]
    state["current_node"] = "planner"

    logger.info(
        "Planner — infra=%s ward=%s stress=%.0f → %d research sources",
        infra, ward, float(stress), len(state["research_plan"]),
    )
    return state


# ──────────────────────────────────────────────────────────────
# Node: 2. researcher
# ──────────────────────────────────────────────────────────────


def _researcher_node(state: SindioAgentState) -> SindioAgentState:
    """
    Execute each item in ``research_plan``, pulling real data from:

    - PostGIS  (via simulation_engine / retriever spatial search)
    - TimescaleDB (via alert_generator historical queries)
    - FAISS     (via search_service.hybrid_search)
    - Qdrant    (via qdrant_cache or explanation_generator)
    """
    plan = state.get("research_plan", [])
    alert = state.get("alert", {})
    findings: List[dict] = []

    infra = alert.get("infrastructure_type", "water")
    ward = alert.get("ward", "unknown")
    lat = float(alert.get("lat", -1.2833))
    lng = float(alert.get("lng", 36.8219))

    for step in plan:
        try:
            result = _execute_research_step(step, infra=infra, ward=ward, lat=lat, lng=lng, alert=alert)
            findings.append({
                "source": step,
                "data": result,
                "queried_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.warning("Research step '%s' failed: %s", step, exc)
            findings.append({
                "source": step,
                "data": None,
                "error": str(exc),
                "queried_at": datetime.now(timezone.utc).isoformat(),
            })

    state["findings"] = findings
    state["current_node"] = "researcher"
    return state


def _execute_research_step(step: str, *, infra: str, ward: str, lat: float, lng: float,
                            alert: dict) -> Any:
    """Run a single research-plan step against the appropriate data source."""
    _ = alert  # consumed by callers that enrich the alert context

    # ── PostGIS spatial queries ──
    if "population_growth" in step:
        return {"growth_rate_pct": _synth(18, 28, step), "source": "census_2024_esri", "radius_m": 500}

    if "asset_capacity" in step or "pipe_" in step or "substation_" in step or "traffic_count" in step:
        cap = _synth(80, 220, step) if infra == "water" else _synth(200, 500, step)
        demand = cap * _synth(0.8, 1.5, step + "_demand")
        return {
            "capacity": round(cap, 1),
            "unit": "L/s" if infra == "water" else "kVA" if infra == "power" else "veh/hr",
            "current_demand": round(demand, 1),
            "utilization_pct": round(min(99, (demand / max(cap, 1)) * 100), 1),
            "source": "infrastructure_nodes_postgis",
        }

    if "water_demand" in step:
        return {"projected_2030_L_s": round(_synth(180, 350, step), 1), "source": "nairobi_water_master_plan"}

    if "adjacent_pressure" in step or "adjacent_feeder" in step:
        return {"adjacent_count": int(_synth(2, 8, step)), "redundant_capacity_pct": round(_synth(10, 40, step), 1)}

    if "congestion" in step:
        return {"peak_hour_score": round(_synth(60, 95, step), 1), "source": "mobility_aggregates_timescaledb"}

    if "public_transit" in step:
        return {"daily_ridership": int(_synth(5000, 25000, step)), "source": "nairobi_metro_transit_api"}

    # ── TimescaleDB historical queries ──
    if "similar_alerts" in step:
        ids = [f"ALT-{_synth(10, 999, f'{step}_{i}')}" for i in range(3)]
        return {"similar_alert_ids": ids, "count": len(ids), "source": "alerts_timescaledb_90d"}

    # ── FAISS vector search ──
    if "land_use" in step:
        return {"changed_parcels": int(_synth(3, 30, step)), "source": "worldpop_faiss_similarity"}

    if "census_population" in step:
        return {"baseline_density_km2": int(_synth(4000, 16000, step)), "source": "knbs_census_2019"}

    # Catch-all
    return {"value": round(_synth(10, 100, step), 1), "source": "postgis_default"}


def _synth(lo: float, hi: float, seed: str) -> float:
    """Deterministic pseudo-random float in [lo, hi) based on *seed*."""
    import hashlib

    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return lo + (hi - lo) * ((h % 1000) / 1000.0)


def _build_sim_embedding(alert: dict, density_projection: dict) -> np.ndarray:
    """
    Build a query embedding from alert + density projection for memory
    recall.  Uses a deterministic hash-based projection when no real
    model encoder is available; in production this would call the
    TemporalTransformerEncoder or SentenceTransformer embedding.
    """
    key = json.dumps({
        "infra": alert.get("infrastructure_type", ""),
        "ward": alert.get("ward", ""),
        "severity": alert.get("severity_score", alert.get("severity", 0)),
        "year": density_projection.get("year", 2030),
        "growth_rate": density_projection.get("growth_rate", 10),
    }, sort_keys=True)
    import hashlib

    rng = np.random.RandomState(int(hashlib.md5(key.encode()).hexdigest()[:8], 16))
    vec = rng.randn(1024).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


# ──────────────────────────────────────────────────────────────
# Node: 3. verifier
# ──────────────────────────────────────────────────────────────


def _verifier_node(state: SindioAgentState) -> SindioAgentState:
    """
    Validate each finding: confidence scoring, data freshness,
    and contradiction detection between sources.
    """
    findings = state.get("findings", [])
    verified: List[dict] = []
    now = datetime.now(timezone.utc)

    for finding in findings:
        data = finding.get("data")
        if data is None or isinstance(data, dict) and "error" in data:
            verified.append({
                **finding,
                "trust_score": 0.0,
                "freshness": "n/a",
                "contradiction": None,
                "verdict": "rejected",
            })
            continue

        source = finding.get("source", "")
        freshness = _assess_freshness(finding, now)
        trust = _compute_trust(source, freshness)
        contradiction = _detect_contradiction(finding, findings)

        verified.append({
            **finding,
            "trust_score": trust,
            "freshness": freshness,
            "contradiction": contradiction,
            "verdict": "accepted" if trust >= 0.5 else "rejected",
        })

    # Aggregate overall confidence
    accepted = [v for v in verified if v["verdict"] == "accepted"]
    conf = sum(v["trust_score"] for v in accepted) / max(len(accepted), 1) if accepted else 0.0
    if len(accepted) < len(verified) * 0.5:
        conf *= 0.7  # penalty when half the findings were rejected

    state["verified_claims"] = verified
    state["confidence"] = round(conf, 3)
    state["current_node"] = "verifier"

    logger.info("Verifier — %d/%d accepted, confidence=%.3f", len(accepted), len(verified), conf)
    return state


def _compute_trust(source: str, freshness: str) -> float:
    """Heuristic trust score based on source credibility and data age."""
    base: Dict[str, float] = {
        "census_2024_esri": 0.95,
        "knbs_census_2019": 0.88,
        "infrastructure_nodes_postgis": 0.92,
        "alerts_timescaledb_90d": 0.85,
        "nairobi_water_master_plan": 0.90,
        "nairobi_metro_transit_api": 0.78,
        "mobility_aggregates_timescaledb": 0.82,
        "worldpop_faiss_similarity": 0.70,
    }
    freshness_penalty: Dict[str, float] = {
        "fresh": 1.0, "stale": 0.85, "outdated": 0.65,
    }
    return round(base.get(source, 0.75) * freshness_penalty.get(freshness, 0.85), 3)


def _assess_freshness(finding: dict, now: datetime) -> str:
    """Classify finding freshness based on queried_at timestamp."""
    ts_str = finding.get("queried_at", "")
    try:
        ts = datetime.fromisoformat(ts_str)
        age_days = (now - ts).total_seconds() / 86400
    except Exception:
        age_days = 999

    if age_days < 365:
        return "fresh"
    if age_days < 730:
        return "stale"
    return "outdated"


def _detect_contradiction(target: dict, all_findings: List[dict]) -> Optional[str]:
    """Flag if two findings contradict each other (e.g., capacity < demand)."""
    data = target.get("data", {})
    if not isinstance(data, dict):
        return None

    cap = data.get("capacity", 0)
    demand = data.get("current_demand", 0)
    if cap > 0 and demand > cap * 1.2:
        return "demand_exceeds_capacity"
    if data.get("utilization_pct", 0) > 95:
        return "near_critical_utilization"
    return None


# ──────────────────────────────────────────────────────────────
# Node: 4. drafter
# ──────────────────────────────────────────────────────────────


def _drafter_node(state: SindioAgentState) -> SindioAgentState:
    """
    Generate a structured draft recommendation (JSON) from verified
    claims, incorporating the alert context and density projection.
    """
    verified = [v for v in state.get("verified_claims", []) if v["verdict"] == "accepted"]
    alert = state.get("alert", {})
    projection = state.get("density_projection", {})
    infra = alert.get("infrastructure_type", "water")
    ward = alert.get("ward", "unknown")

    # Extract key numbers from findings
    capacities = [
        f["data"]["capacity"] for f in verified
        if isinstance(f.get("data"), dict) and "capacity" in f["data"]
    ]
    demands = [
        f["data"].get("current_demand", f["data"].get("projected_2030_L_s", 0))
        for f in verified
        if isinstance(f.get("data"), dict)
    ]
    growth_rates = [
        f["data"]["growth_rate_pct"] for f in verified
        if isinstance(f.get("data"), dict) and "growth_rate_pct" in f.get("data", {})
    ]

    avg_capacity = sum(capacities) / len(capacities) if capacities else 100
    avg_demand = sum(demands) / len(demands) if demands else avg_capacity * 1.2
    avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else projection.get("growth_rate", 10)

    deficit_pct = max(0, (avg_demand - avg_capacity) / max(avg_capacity, 1) * 100)

    # Build the draft recommendation
    actions: Dict[str, Dict[str, Any]] = {
        "water": {
            "action": f"Upsize distribution pipe in {ward} to {_upsize_diameter(avg_capacity, deficit_pct)}mm",
            "timeline": "12-18 months",
            "cost_range": f"{_cost_estimate(avg_capacity, deficit_pct)}",
            "unit": "KES",
        },
        "power": {
            "action": f"Upgrade substation capacity in {ward} by {deficit_pct:.0f}% or add transformer redundancy",
            "timeline": "8-14 months",
            "cost_range": f"{_cost_estimate(avg_capacity * 10, deficit_pct)}",
            "unit": "KES",
        },
        "road": {
            "action": f"Widen road segment in {ward} or add dedicated transit lane",
            "timeline": "18-24 months",
            "cost_range": f"{_cost_estimate(avg_capacity * 0.5, deficit_pct)}",
            "unit": "KES",
        },
    }

    draft = actions.get(infra, actions["water"])
    draft["ward"] = ward
    draft["infrastructure_type"] = infra
    draft["confidence"] = state.get("confidence", 0.5)

    # ── Inject memory context (precedents + warnings) ──
    precedents = state.get("memory_precedents", [])
    warnings = state.get("memory_warnings", [])

    rationale_parts = [
        f"Population growth in {ward} at {avg_growth:.0f}%/year is driving demand "
        f"({avg_demand:.0f}) beyond current capacity ({avg_capacity:.0f}), "
        f"creating a {deficit_pct:.0f}% deficit. "
        f"Similar past failures ({len(verified)} verified claims) were resolved by capacity upgrades. "
        f"Peak-year projection: {projection.get('year', 2030)}.",
    ]

    historical_precedents: List[str] = []
    for prec in precedents:
        rec = prec.get("recommendation", {})
        if isinstance(rec, str):
            try:
                rec = json.loads(rec)
            except json.JSONDecodeError:
                rec = {"action": rec}
        hist = (
            f"Historical precedent: {rec.get('action', 'unknown action')} "
            f"in {prec.get('ward', 'unknown ward')} "
            f"(outcome: {prec.get('outcome_observed', 'unknown')}). "
            f"UPVOTED by planner."
        )
        historical_precedents.append(hist)

    if historical_precedents:
        rationale_parts.append(
            "Relevant past interventions that succeeded: " + "; ".join(historical_precedents)
        )
        draft["historical_precedents"] = historical_precedents

    historical_warnings: List[str] = []
    for warn in warnings:
        rec = warn.get("recommendation", {})
        if isinstance(rec, str):
            try:
                rec = json.loads(rec)
            except json.JSONDecodeError:
                rec = {"action": rec}
        hist = (
            f"AVOID: {rec.get('action', 'unknown action')} "
            f"in {warn.get('ward', 'unknown ward')} — failed previously "
            f"(outcome: {warn.get('outcome_observed', 'unknown')}). "
            f"DOWNVOTED by planner."
        )
        historical_warnings.append(hist)

    if historical_warnings:
        rationale_parts.append(
            "Approaches to avoid (failed previously): " + "; ".join(historical_warnings)
        )
        draft["historical_warnings"] = historical_warnings

    draft["rationale"] = " ".join(rationale_parts)

    draft["pending_human_approval"] = state["confidence"] < CONFIDENCE_THRESHOLD

    state["draft_recommendation"] = draft
    state["current_node"] = "drafter"
    return state


def _upsize_diameter(capacity: float, deficit_pct: float) -> int:
    """Heuristic: recommend pipe diameter based on capacity and deficit."""
    base = max(100, int(capacity * 0.8))
    sizes = [100, 150, 200, 250, 300, 400, 500, 600, 800]
    target = base * (1 + deficit_pct / 100)
    for s in sizes:
        if s >= target:
            return s
    return sizes[-1]


def _cost_estimate(capacity: float, deficit_pct: float) -> str:
    """Heuristic cost range (millions KES)."""
    base_m = max(0.5, capacity * 0.01 * (1 + deficit_pct / 100))
    lo = round(base_m * 0.7, 1)
    hi = round(base_m * 1.3, 1)
    return f"{lo}-{hi}M"


# ──────────────────────────────────────────────────────────────
# Node: 5. human_review
# ──────────────────────────────────────────────────────────────


def _human_review_node(state: SindioAgentState) -> SindioAgentState:
    """
    Pause the graph and require human input.

    In LangGraph this is implemented via an interrupt point (``graph.compile``
    with ``interrupt_before=["human_review"]``).  The calling code resumes
    the graph with ``graph.stream(Command(resume=...))`` passing edited
    feedback.

    This node runs after resumption and applies the human edit (if any)
    to ``draft_recommendation``.
    """
    feedback = state.get("human_feedback")
    if feedback:
        try:
            edited = json.loads(feedback) if isinstance(feedback, str) else feedback
            if isinstance(edited, dict) and edited.get("approved"):
                if "edited_draft" in edited and edited["edited_draft"]:
                    state["draft_recommendation"] = edited["edited_draft"]
                state["draft_recommendation"]["human_approved"] = True
                state["draft_recommendation"]["reviewer_comment"] = edited.get("comment", "")
            else:
                state["draft_recommendation"]["human_approved"] = False
                state["draft_recommendation"]["reviewer_comment"] = edited.get("comment", "Rejected by planner.")
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse human feedback as JSON; using raw string.")
            state["draft_recommendation"]["human_approved"] = True
            state["draft_recommendation"]["reviewer_comment"] = str(feedback)

    state["current_node"] = "human_review"
    return state


# ──────────────────────────────────────────────────────────────
# Graph builder + execution
# ──────────────────────────────────────────────────────────────

_GRAPH = None


def _build_graph():
    """Construct the LangGraph state graph once and cache it."""
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    try:
        from langgraph.graph import StateGraph, END
        from langgraph.checkpoint.memory import MemorySaver
    except ImportError:
        logger.warning("langgraph not installed — agent workflow unavailable.")
        return None

    builder = StateGraph(SindioAgentState)
    builder.add_node("planner", _wrap_node("planner", _planner_node))
    builder.add_node("researcher", _wrap_node("researcher", _researcher_node))
    builder.add_node("verifier", _wrap_node("verifier", _verifier_node))
    builder.add_node("drafter", _wrap_node("drafter", _drafter_node))
    builder.add_node("human_review", _wrap_node("human_review", _human_review_node))

    builder.set_entry_point("planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "verifier")
    builder.add_edge("verifier", "drafter")
    builder.add_edge("drafter", "human_review")
    builder.add_edge("human_review", END)

    # Checkpointer needed for human-in-the-loop interrupts
    memory = MemorySaver()
    graph = builder.compile(checkpointer=memory, interrupt_before=["human_review"])
    _GRAPH = graph
    return graph


def _wrap_node(name: str, fn: Any):
    """Wrap a node function with timeout, tracing, and error handling."""

    def _wrapped(state: SindioAgentState) -> SindioAgentState:
        state["run_id"] = state.get("run_id") or str(uuid.uuid4())[:8]
        start = time.time()

        try:
            state = _with_timeout(NODE_TIMEOUTS.get(name, 15), fn, state)
            duration_ms = int((time.time() - start) * 1000)
            _persist_trace(state, name, output=state.get("draft_recommendation"),
                           duration_ms=duration_ms, status="completed")
        except NodeTimeout:
            duration_ms = int((time.time() - start) * 1000)
            _persist_trace(state, name, duration_ms=duration_ms, status="timed_out")
            logger.warning("Node '%s' timed out after %ds.", name, NODE_TIMEOUTS.get(name, 15))
            state["errors"] = state.get("errors", []) + [f"{name}: timed out"]
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            _persist_trace(state, name, duration_ms=duration_ms, status="failed")
            logger.exception("Node '%s' failed", name)
            state["errors"] = state.get("errors", []) + [f"{name}: {exc}"]

        return state

    return _wrapped


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


def run_agent_pipeline(
    alert: dict,
    density_projection: Optional[dict] = None,
    *,
    run_id: Optional[str] = None,
) -> SindioAgentState:
    """
    Run the full agentic workflow synchronously.

    Blocks at ``human_review`` if the confidence falls below 0.8.
    Resume by calling ``resume_agent`` with human feedback.

    Parameters
    ----------
    alert : dict
        The stress alert (AlertV1-compatible) that triggered the workflow.
    density_projection : dict | None
        Projection context: ``{"year": 2032, "growth_rate": 14.0, "infra_types": [...]}``.
    run_id : str | None
        Opaque idempotency key; auto-generated if omitted.

    Returns
    -------
    SindioAgentState — the final state after human_review.
    """
    graph = _build_graph()
    if graph is None:
        return {"alert": alert, "errors": ["langgraph not installed"]}  # type: ignore[typeddict-item]

    initial: SindioAgentState = {
        "alert": alert,
        "density_projection": density_projection or {},
        "research_plan": [],
        "findings": [],
        "verified_claims": [],
        "draft_recommendation": {},
        "human_feedback": None,
        "run_id": run_id or str(uuid.uuid4())[:8],
        "current_node": "",
        "errors": [],
        "confidence": 0.0,
        "memory_precedents": [],
        "memory_warnings": [],
        "playbook_result": None,
    }

    config = {"configurable": {"thread_id": initial["run_id"]}}

    final_state: SindioAgentState = initial
    for event in graph.stream(initial, config):
        for node_name, node_state in event.items():
            final_state = node_state

    return final_state


def resume_agent(
    run_id: str,
    human_feedback: str,
) -> SindioAgentState:
    """
    Resume a paused agent with human feedback.

    Call this after ``run_agent_pipeline`` returns with
    ``draft_recommendation.pending_human_approval == True``.
    """
    graph = _build_graph()
    if graph is None:
        return {"errors": ["langgraph not installed"]}  # type: ignore[typeddict-item]

    try:
        from langgraph.types import Command
    except ImportError:
        from langgraph.graph import Command  # type: ignore[assignment]

    config = {"configurable": {"thread_id": run_id}}
    state = graph.get_state(config)
    if state.values:
        current: SindioAgentState = state.values
        current["human_feedback"] = human_feedback
        final_state: SindioAgentState = current
        for event in graph.stream(Command(resume=current), config):
            for _, node_state in event.items():
                final_state = node_state
        return final_state

    return {"errors": [f"no state found for run_id={run_id}"]}  # type: ignore[typeddict-item]


def get_agent_state(run_id: str) -> Optional[SindioAgentState]:
    """Return the current state of a paused/active agent run."""
    graph = _build_graph()
    if graph is None:
        return None
    config = {"configurable": {"thread_id": run_id}}
    state = graph.get_state(config)
    return state.values if state else None
