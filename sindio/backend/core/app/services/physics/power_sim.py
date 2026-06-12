"""
AC power-flow solver using pandapower (Newton-Raphson).

Simulates an electricity distribution network:
  - Buses: voltage levels, loads
  - Lines: impedance, thermal rating
  - Generators: active/reactive power

If pandapower is unavailable, falls back to simplified
DC power-flow approximation (ignores reactive power, losses).

Output: dict of bus_id → {voltage_pu, p_mw, q_mvar, line_loading_pct, overloaded}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.physics.power")

try:
    import pandapower as pp
    import pandapower.networks as pnw

    HAS_PANDAPOWER = True
except ImportError:
    HAS_PANDAPOWER = False
    logger.warning("pandapower not installed — using DC power-flow fallback.")


@dataclass
class PowerBus:
    bus_id: str
    voltage_kv: float = 11.0
    load_mw: float = 0.0
    load_mvar: float = 0.0
    bus_type: str = "load"   # load | generator | slack

@dataclass
class PowerLine:
    line_id: str
    from_bus: str
    to_bus: str
    r_ohm_per_km: float = 0.2
    x_ohm_per_km: float = 0.3
    length_km: float = 1.0
    thermal_rating_mva: float = 30.0

@dataclass
class PowerGenerator:
    gen_id: str
    bus_id: str
    p_mw: float = 0.0
    q_mvar: float = 0.0
    max_p_mw: float = 20.0


# ──────────────────────────────────────────────────────────────
# pandapower path
# ──────────────────────────────────────────────────────────────


def _run_pandapower(
    buses: List[PowerBus],
    lines: List[PowerLine],
    generators: List[PowerGenerator],
) -> Dict[str, Dict[str, float]]:
    """Run Newton-Raphson AC power flow via pandapower."""
    net = pp.create_empty_network()

    bus_map: Dict[str, int] = {}
    for bus in buses:
        pp_bus = pp.create_bus(
            net,
            vn_kv=bus.voltage_kv,
            name=bus.bus_id,
        )
        bus_map[bus.bus_id] = pp_bus

        if bus.bus_type == "slack":
            pp.create_ext_grid(net, pp_bus, vm_pu=1.0, va_degree=0.0)
        elif bus.load_mw > 0:
            pp.create_load(
                net, pp_bus, p_mw=bus.load_mw, q_mvar=bus.load_mvar
            )

    for gen in generators:
        pp.create_gen(
            net,
            bus_map[gen.bus_id],
            p_mw=gen.p_mw,
            vm_pu=1.0,
            max_p_mw=gen.max_p_mw,
            name=gen.gen_id,
        )

    for line in lines:
        pp.create_line_from_parameters(
            net,
            from_bus=bus_map[line.from_bus],
            to_bus=bus_map[line.to_bus],
            length_km=line.length_km,
            r_ohm_per_km=line.r_ohm_per_km,
            x_ohm_per_km=line.x_ohm_per_km,
            max_i_ka=line.thermal_rating_mva / (line.voltage_kv * np.sqrt(3))
                     if hasattr(line, 'voltage_kv') else 1.0,
            c_nf_per_km=0.0,
            name=line.line_id,
        )

    pp.runpp(net, algorithm="nr", numba=False)

    results: Dict[str, Dict[str, float]] = {}

    # Bus results
    for bus_name, bus_idx in bus_map.items():
        res_bus = net.res_bus.iloc[bus_idx]
        results[bus_name] = {
            "voltage_pu": float(res_bus["vm_pu"]),
            "voltage_angle_deg": float(res_bus["va_degree"]),
            "p_mw": float(res_bus["p_mw"]) if "p_mw" in res_bus else 0.0,
            "line_loading_pct": 0.0,
            "overloaded": False,
        }

    # Line loadings
    if net.res_line is not None and not net.res_line.empty:
        for i, line in enumerate(lines):
            bus_id = line.from_bus
            loading = float(net.res_line.iloc[i]["loading_percent"])
            if bus_id in results:
                results[bus_id]["line_loading_pct"] = max(
                    results[bus_id].get("line_loading_pct", 0.0), loading
                )
            if line.to_bus in results:
                results[line.to_bus]["line_loading_pct"] = max(
                    results[line.to_bus].get("line_loading_pct", 0.0), loading
                )

    for bid in results:
        results[bid]["overloaded"] = results[bid]["line_loading_pct"] > 90.0

    return results


# ──────────────────────────────────────────────────────────────
# DC power-flow fallback
# ──────────────────────────────────────────────────────────────


def _run_dc_power_flow(
    buses: List[PowerBus],
    lines: List[PowerLine],
    generators: List[PowerGenerator],
) -> Dict[str, Dict[str, float]]:
    """Simplified DC power-flow (fast, linear approximation).

    Uses bus admittance matrix Y = G + jB, drops reactive terms.
    P = B * θ  (DC assumption: |V| ≈ 1 pu, small angles).
    """
    n = len(buses)
    bus_idx = {b.bus_id: i for i, b in enumerate(buses)}

    # Build susceptance matrix B (n×n)
    B = np.zeros((n, n))
    for line in lines:
        if line.from_bus in bus_idx and line.to_bus in bus_idx:
            i, j = bus_idx[line.from_bus], bus_idx[line.to_bus]
            x = line.x_ohm_per_km * line.length_km
            b = 1.0 / max(x, 0.001)
            B[i, i] += b
            B[j, j] += b
            B[i, j] -= b
            B[j, i] -= b

    # Find slack bus
    slack = next((b for b in buses if b.bus_type == "slack"), None)
    if slack is None:
        slack = buses[0]

    slack_idx = bus_idx[slack.bus_id]

    # Remove slack row/col
    mask = np.ones(n, dtype=bool)
    mask[slack_idx] = False
    B_red = B[mask][:, mask]
    B_red_inv = np.linalg.pinv(B_red) if B_red.size > 0 else np.zeros((0, 0))

    # Power injection vector (generation - load at each bus)
    p_inj = np.zeros(n)
    for gen in generators:
        if gen.bus_id in bus_idx:
            p_inj[bus_idx[gen.bus_id]] += gen.p_mw
    for bus in buses:
        p_inj[bus_idx[bus.bus_id]] -= bus.load_mw

    p_red = p_inj[mask]

    theta_red = B_red_inv @ p_red if B_red_inv.size > 0 else np.zeros_like(p_red)

    theta = np.zeros(n)
    theta[mask] = theta_red

    results: Dict[str, Dict[str, float]] = {}

    for bus in buses:
        idx = bus_idx[bus.bus_id]
        voltage_drop = max(0.0, 1.0 - abs(theta[idx]) * 0.01)
        results[bus.bus_id] = {
            "voltage_pu": round(voltage_drop, 4),
            "voltage_angle_deg": round(float(theta[idx]), 4),
            "p_mw": 0.0,
            "line_loading_pct": 0.0,
            "overloaded": voltage_drop < 0.92,
        }

    # Compute line flows
    for line in lines:
        if line.from_bus in bus_idx and line.to_bus in bus_idx:
            i, j = bus_idx[line.from_bus], bus_idx[line.to_bus]
            flow = abs((theta[i] - theta[j]) * B[i, j]) if B[i, j] != 0 else 0.0
            rating = line.thermal_rating_mva or 30.0
            loading = (flow / rating) * 100.0
            results[line.from_bus]["line_loading_pct"] = max(
                results[line.from_bus].get("line_loading_pct", 0.0), loading
            )
            results[line.to_bus]["line_loading_pct"] = max(
                results[line.to_bus].get("line_loading_pct", 0.0), loading
            )
            if loading > 90.0:
                results[line.from_bus]["overloaded"] = True
                results[line.to_bus]["overloaded"] = True

    return results


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


def simulate_power_network(
    buses: List[PowerBus],
    lines: List[PowerLine],
    generators: List[PowerGenerator],
    stress_factor: float = 1.0,
) -> Dict[str, Dict[str, float]]:
    """Run power-flow simulation.

    Multiplies all bus loads by stress_factor.
    A bus is overloaded if line loading > 90% or voltage < 0.92 pu.
    """
    for bus in buses:
        bus.load_mw *= stress_factor
        bus.load_mvar *= stress_factor

    if HAS_PANDAPOWER:
        try:
            return _run_pandapower(buses, lines, generators)
        except Exception as exc:
            logger.warning("pandapower failed (%s) — falling back to DC.", exc)

    return _run_dc_power_flow(buses, lines, generators)
