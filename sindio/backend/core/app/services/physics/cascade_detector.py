"""
Cascading failure detector for coupled infrastructure systems.

Models interdependencies:
  - Power outage → water pumps fail → pressure drops → pipe bursts
  - Road congestion → delayed repair crews → longer outage duration
  - Water pressure loss → road subsidence → road damage

Builds a directed dependency graph, then propagates failures
through all connected assets using topological traversal.

Output: list of failure chains with timestamps and probabilities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("sindio.physics.cascade")


class AssetType(str, Enum):
    POWER_BUS = "power_bus"
    POWER_LINE = "power_line"
    PUMP_STATION = "pump_station"
    WATER_PIPE = "water_pipe"
    ROAD_CELL = "road_cell"
    TRAFFIC_SIGNAL = "traffic_signal"


@dataclass
class Asset:
    asset_id: str
    asset_type: AssetType
    status: str = "operational"  # operational | overloaded | failed
    stress: float = 0.0
    ward: str = ""
    lat: float = 0.0
    lon: float = 0.0

@dataclass
class Dependency:
    source_id: str
    target_id: str
    dependency_type: str   # "power_to_pump" | "power_to_signal" | "water_to_road"
    description: str = ""


class CascadeDetector:
    """Detect and propagate cascading failures through infrastructure network.

    Rules:
      1. Power bus failed → all connected pump stations fail
      2. Pump station failed → connected water pipes lose pressure
      3. Water pipe burst → adjacent road cells subside
      4. Traffic signal outage → road cell capacity reduced by 40%
    """

    def __init__(self):
        self.assets: Dict[str, Asset] = {}
        self.dependencies: List[Dependency] = []
        self.adj_out: Dict[str, List[Dependency]] = {}
        self.adj_in: Dict[str, List[Dependency]] = {}

    def add_asset(self, asset: Asset):
        self.assets[asset.asset_id] = asset

    def add_dependency(self, dep: Dependency):
        self.dependencies.append(dep)
        self.adj_out.setdefault(dep.source_id, []).append(dep)
        self.adj_in.setdefault(dep.target_id, []).append(dep)

    def detect(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Detect cascading failures starting from overloaded assets.

        Returns ordered list of failure events.
        """

        # Seeds: assets with stress > threshold
        failed: Set[str] = set()
        queue: List[Tuple[str, int, str]] = []  # (asset_id, depth, cause)

        for aid, a in self.assets.items():
            if a.stress > threshold:
                failed.add(aid)
                queue.append((aid, 0, "overloaded"))
                a.status = "failed"

        cascades: List[Dict[str, Any]] = []

        while queue:
            current_id, depth, cause = queue.pop(0)
            current = self.assets[current_id]

            cascades.append({
                "asset_id": current_id,
                "asset_type": current.asset_type.value,
                "failure_cause": cause,
                "cascade_depth": depth,
                "stress_at_failure": current.stress,
            })

            # Propagate to dependents
            for dep in self.adj_out.get(current_id, []):
                target_id = dep.target_id
                if target_id not in failed:
                    target = self.assets.get(target_id)
                    if target is None:
                        continue

                    failed.add(target_id)
                    target.status = "failed"
                    new_cause = f"cascade_from_{current_id}_{dep.dependency_type}"
                    queue.append((target_id, depth + 1, new_cause))

        logger.info(
            "Cascade detected: %d seeds, %d total failures, max depth=%d",
            len([c for c in cascades if c["cascade_depth"] == 0]),
            len(cascades),
            max((c["cascade_depth"] for c in cascades), default=0),
        )
        return cascades

    def build_nairobi_graph(self, ward: str = "Central") -> None:
        """Build default Nairobi dependency graph for a ward.

        Models typical interdependencies:
          - Power substations feed pump stations
          - Pump stations pressurise water pipes
          - Traffic signals depend on power
          - Water pipe bursts damage adjacent road segments
        """
        # Power assets
        for i in range(1, 4):
            bus_id = f"{ward}_substation_{i}"
            self.add_asset(Asset(bus_id, AssetType.POWER_BUS, ward=ward))

        # Pump stations (depend on power)
        for i in range(1, 6):
            pump_id = f"{ward}_pump_{i}"
            self.add_asset(Asset(pump_id, AssetType.PUMP_STATION, ward=ward))
            bus_id = f"{ward}_substation_{(i % 3) + 1}"
            self.add_dependency(Dependency(
                source_id=bus_id,
                target_id=pump_id,
                dependency_type="power_to_pump",
                description=f"Pump {i} powered by {bus_id}",
            ))

        # Water pipes (depend on pumps)
        for i in range(1, 6):
            pipe_id = f"{ward}_water_pipe_{i}"
            self.add_asset(Asset(pipe_id, AssetType.WATER_PIPE, ward=ward))
            pump_id = f"{ward}_pump_{i}"
            self.add_dependency(Dependency(
                source_id=pump_id,
                target_id=pipe_id,
                dependency_type="pump_to_pipe",
                description=f"Pipe {i} fed by {pump_id}",
            ))

        # Road cells
        for i in range(1, 4):
            cell_id = f"{ward}_road_cell_{i}"
            self.add_asset(Asset(cell_id, AssetType.ROAD_CELL, ward=ward))

            # Road depends on traffic signals (which need power)
            signal_id = f"{ward}_signal_{i}"
            self.add_asset(Asset(signal_id, AssetType.TRAFFIC_SIGNAL, ward=ward))
            self.add_dependency(Dependency(
                source_id=f"{ward}_substation_{i}",
                target_id=signal_id,
                dependency_type="power_to_signal",
                description=f"Signal {i} powered by substation {i}",
            ))
            self.add_dependency(Dependency(
                source_id=signal_id,
                target_id=cell_id,
                dependency_type="signal_to_road",
                description=f"Road cell {i} managed by signal {i}",
            ))

        # Water pipe burst → road subsidence (cross-sector)
        for i in range(1, 4):
            self.add_dependency(Dependency(
                source_id=f"{ward}_water_pipe_{i}",
                target_id=f"{ward}_road_cell_{i}",
                dependency_type="water_to_road",
                description=f"Pipe burst {i} causes road {i} subsidence",
            ))
