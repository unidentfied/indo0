"""
Cell Transmission Model (CTM) for road traffic simulation.

The road network is discretised into cells of equal length.
Each cell obeys the conservation law:

  n_i(t+1) = n_i(t) + y_i(t) - y_{i+1}(t)

Where:
  n_i = number of vehicles in cell i
  y_i = outflow from cell i to i+1 (limited by sending + receiving capacity)

Outflow is the minimum of:
  - What cell i can send: min(n_i, Q_i * dt)
  - What cell i+1 can receive: w / vf * N_{i+1} - n_{i+1} (triangle FD)

References:
  Daganzo, C.F. (1994). "The cell transmission model."

Output per cell: {density_veh_km, speed_kmh, flow_veh_h, congested}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger("sindio.physics.road")


@dataclass
class RoadCell:
    cell_id: str
    length_m: float = 100.0
    capacity_veh_h: float = 2000.0        # max flow Q_m
    jam_density_veh_km: float = 150.0     # max density N
    freeflow_speed_kmh: float = 50.0      # v_f
    backward_wave_speed_kmh: float = 15.0  # w
    initial_vehicles: int = 0

    @property
    def max_vehicles(self) -> int:
        return int(self.jam_density_veh_km * self.length_m / 1000.0)

    @property
    def capacity_per_dt(self) -> int:
        """Max outflow per time-step (vehicles)."""
        dt = 1.0 / 12  # 5-second time step
        return int(self.capacity_veh_h * dt)


@dataclass
class RoadLink:
    link_id: str
    from_cell: str
    to_cell: str
    split_ratio: float = 1.0   # fraction of outflow to this link
    signal_timing: float = 0.5  # green/cycle ratio


class CellTransmissionModel:
    """Discrete-time CTM for a linear road network."""

    def __init__(
        self,
        cells: List[RoadCell],
        links: List[RoadLink],
        dt_hours: float = 1.0 / 720.0,  # 5 seconds
    ):
        self.cells = {c.cell_id: c for c in cells}
        self.links = links
        self.dt = dt_hours

        self.n: Dict[str, int] = {
            c.cell_id: c.initial_vehicles for c in cells
        }

        # Build adjacency: incoming links per cell
        self.incoming: Dict[str, List[RoadLink]] = {}
        self.outgoing: Dict[str, List[RoadLink]] = {}
        for ln in links:
            self.incoming.setdefault(ln.to_cell, []).append(ln)
            self.outgoing.setdefault(ln.from_cell, []).append(ln)

        # History
        self.history: Dict[str, List[int]] = {c.cell_id: [] for c in cells}

    def step(self, steps: int = 1) -> Dict[str, Dict[str, float]]:
        """Advance the CTM by `steps` time steps.

        Returns per-cell state: {density, speed, flow, congested}.
        """
        for _ in range(steps):
            self._step_once()

        return self.get_state()

    def _step_once(self):
        """One CTM time-step."""
        new_n = self.n.copy()

        for cell_id, cell in self.cells.items():
            # Demand (what this cell can send)
            demand = min(self.n.get(cell_id, 0), cell.capacity_per_dt)

            # Distribute demand across outgoing links
            out_links = self.outgoing.get(cell_id, [])
            total_split = sum(ln.split_ratio for ln in out_links) or 1.0

            for ln in out_links:
                next_cell = self.cells.get(ln.to_cell)
                if next_cell is None:
                    continue

                # Supply (what next cell can receive)
                supply = max(0, next_cell.max_vehicles - self.n.get(ln.to_cell, 0))

                # Actual flow
                flow = min(
                    int(demand * ln.split_ratio / total_split),
                    int(supply * ln.signal_timing),
                )

                flow = max(0, flow)
                new_n[cell_id] = new_n.get(cell_id, 0) - flow
                new_n[ln.to_cell] = new_n.get(ln.to_cell, 0) + flow

        self.n = new_n
        for cid in self.cells:
            self.history[cid].append(self.n.get(cid, 0))

    def get_state(self) -> Dict[str, Dict[str, float]]:
        """Current state of all cells."""
        state = {}
        for cid, cell in self.cells.items():
            vehs = max(0, self.n.get(cid, 0))
            density = vehs / (cell.length_m / 1000.0) if cell.length_m > 0 else 0.0

            if density < 0.5:
                speed = cell.freeflow_speed_kmh
            elif density >= cell.jam_density_kmh:
                speed = 0.0
            else:
                speed = cell.freeflow_speed_kmh * (1.0 - density / cell.jam_density_kmh)

            flow = density * speed

            # Outflow in last step (veh/h)
            outflow = sum(
                min(self.n.get(ln.from_cell, 0), cell.capacity_per_dt) * ln.split_ratio
                for ln in self.outgoing.get(cid, [])
            )

            state[cid] = {
                "density_veh_km": round(density, 2),
                "speed_kmh": round(speed, 2),
                "flow_veh_h": round(flow, 2),
                "vehicles": vehs,
                "max_vehicles": cell.max_vehicles,
                "congested": bool(density > 0.85 * cell.jam_density_kmh),
                "congestion_index": round(
                    speed / max(cell.freeflow_speed_kmh, 1.0), 4
                ),
            }
        return state

    def apply_stress(self, factor: float):
        """Increase inflow as a stress test.

        Multiplier on demand entering boundary cells.
        """
        for cid in self.cells:
            cell = self.cells[cid]
            cell.initial_vehicles = int(cell.initial_vehicles * factor)


def simulate_road_network(
    cells: List[RoadCell],
    links: List[RoadLink],
    stress_factor: float = 1.0,
    simulation_hours: float = 1.0,
    dt_hours: float = 1.0 / 720.0,
) -> Dict[str, Dict[str, float]]:
    """Run CTM simulation for a road network.

    Steps the model for `simulation_hours` and returns final cell states.
    """
    ctm = CellTransmissionModel(cells, links, dt_hours=dt_hours)
    ctm.apply_stress(stress_factor)

    steps = int(simulation_hours / dt_hours)
    state = ctm.step(steps)

    logger.info(
        "CTM: %d cells, %d steps, congested=%d",
        len(cells),
        steps,
        sum(1 for s in state.values() if s["congested"]),
    )
    return state
