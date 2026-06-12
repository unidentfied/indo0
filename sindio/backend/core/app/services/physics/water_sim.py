"""
EPANET water pressure solver wrapper using the epyt library.

Runs hydraulic simulation for a water distribution network:
  - Nodes: junctions, reservoirs, tanks
  - Pipes: links with diameter, roughness, length
  - Pumps: head-flow curves

If EPANET / epyt is unavailable, falls back to simplified
Darcy–Weisbach + Hazen–Williams hydraulic equations.

Output: dict of node_id → {pressure_m, flow_lps, head_m}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import log10, pi
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sindio.physics.water")

try:
    from epyt import epanet
    HAS_EPANET = True
except ImportError:
    HAS_EPANET = False
    logger.warning("epyt not installed — using hydraulic fallback equations.")


@dataclass
class WaterNode:
    node_id: str
    elevation_m: float = 0.0
    base_demand_lps: float = 0.0
    demand_multiplier: float = 1.0
    node_type: str = "junction"   # junction | reservoir | tank

@dataclass
class WaterPipe:
    pipe_id: str
    from_node: str
    to_node: str
    length_m: float
    diameter_mm: float
    roughness: float = 130.0      # Hazen–Williams C

@dataclass  
class WaterPump:
    pump_id: str
    from_node: str
    to_node: str
    power_kw: float = 75.0
    has_backup_power: bool = False


# ──────────────────────────────────────────────────────────────
# EPANET path
# ──────────────────────────────────────────────────────────────


def _run_epanet(
    nodes: List[WaterNode],
    pipes: List[WaterPipe],
    pumps: List[WaterPump],
    duration_hours: float = 24.0,
) -> Dict[str, Dict[str, float]]:
    """Run full EPANET hydraulic simulation."""
    if not HAS_EPANET:
        raise RuntimeError("epyt not installed")

    d = epanet("net1.inp")
    d = epanet()

    try:
        # Build INP model programmatically
        for node in nodes:
            d.addNode(node.node_id)
            d.setNodeJunctionData(node.node_id, [], [node.elevation_m, node.base_demand_lps * node.demand_multiplier, None, None])

        for pipe in pipes:
            d.addLink(pipe.pipe_id)
            d.setLinkPipeData(pipe.pipe_id, pipe.from_node, pipe.to_node, pipe.length_m, pipe.diameter_mm, pipe.roughness)

        for pump in pumps:
            d.addLink(pump.pump_id)
            d.setLinkPumpData(pump.pump_id, pump.from_node, pump.to_node, [pump.power_kw])

        d.solveCompleteHydraulics()

        results: Dict[str, Dict[str, float]] = {}
        for node in nodes:
            results[node.node_id] = {
                "pressure_m": d.getNodePressure(node.node_id),
                "flow_lps": d.getNodeActualDemand(node.node_id),
                "head_m": d.getNodeHydraulicHead(node.node_id),
            }
        return results
    finally:
        d.unload()


# ──────────────────────────────────────────────────────────────
# Hydraulic fallback (Hazen–Williams)
# ──────────────────────────────────────────────────────────────


def _hazen_williams_head_loss(
    q_lps: float, length_m: float, diameter_mm: float, c_factor: float,
) -> float:
    """Head loss in metres (Hazen–Williams equation)."""
    d_m = diameter_mm / 1000.0
    if d_m <= 0 or q_lps <= 0:
        return 0.0
    return 10.67 * length_m * (q_lps / 1000.0) ** 1.852 / (c_factor ** 1.852 * d_m ** 4.87)


def _run_hydraulic_fallback(
    nodes: List[WaterNode],
    pipes: List[WaterPipe],
    pumps: List[WaterPump],
    source_head_m: float = 80.0,
) -> Dict[str, Dict[str, float]]:
    """Simplified hydraulic model: assume gravity-fed from highest elevation node.

    Computes pressure at each junction by subtracting cumulative head loss
    along the path from the source reservoir.
    """
    results: Dict[str, Dict[str, float]] = {}

    # Build adjacency
    adj: Dict[str, List[Tuple[str, WaterPipe]]] = {}
    for p in pipes:
        adj.setdefault(p.from_node, []).append((p.to_node, p))

    # Find source (reservoir or highest elevation)
    reservoirs = [n for n in nodes if n.node_type == "reservoir"]
    source = reservoirs[0] if reservoirs else max(nodes, key=lambda n: n.elevation_m)
    source_head = source_head_m + source.elevation_m

    # Simple BFS with head-loss accumulation
    visited: Dict[str, float] = {source.node_id: source_head}
    q: List[str] = [source.node_id]

    while q:
        current = q.pop(0)
        curr_head = visited[current]

        for neighbor_id, pipe in adj.get(current, []):
            node = next((n for n in nodes if n.node_id == neighbor_id), None)
            if node is None or neighbor_id in visited:
                continue

            demand = node.base_demand_lps * node.demand_multiplier
            hl = _hazen_williams_head_loss(demand, pipe.length_m, pipe.diameter_mm, pipe.roughness)
            new_head = curr_head - hl

            # Pump boost
            pump = next((p for p in pumps if p.from_node == current and p.to_node == neighbor_id), None)
            if pump:
                new_head += pump.power_kw * 0.1  # approximate head gain

            visited[neighbor_id] = new_head
            q.append(neighbor_id)

    for node in nodes:
        head = visited.get(node.node_id, node.elevation_m)
        pressure_m = max(0.0, head - node.elevation_m)
        demand = node.base_demand_lps * node.demand_multiplier
        results[node.node_id] = {
            "pressure_m": round(pressure_m, 2),
            "flow_lps": round(demand, 2),
            "head_m": round(head, 2),
        }

    return results


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


def simulate_water_network(
    nodes: List[WaterNode],
    pipes: List[WaterPipe],
    pumps: List[WaterPump],
    stress_factor: float = 1.0,
    duration_hours: float = 24.0,
) -> Dict[str, Dict[str, float]]:
    """Run water network simulation.

    Multiplies base demand by stress_factor (≥1.0 for stress testing).
    Returns per-node pressure, flow, and head.

    A node is considered FAILED if pressure < 10 m (≈ 1 bar).
    """
    for node in nodes:
        node.demand_multiplier = stress_factor

    if HAS_EPANET:
        try:
            return _run_epanet(nodes, pipes, pumps, duration_hours)
        except Exception as exc:
            logger.warning("EPANET failed (%s) — falling back.", exc)

    return _run_hydraulic_fallback(nodes, pipes, pumps)
