"""
Cascade failure analysis for Nairobi infrastructure systems.

Maps infrastructure assets to wards/neighborhoods, models cross-sector
dependencies, and propagates failures through BFS to produce:
  - Cascade chain (ordered failure events with timestamps)
  - Affected wards (population, power, water, roads)
  - Critical facilities impact (hospitals, universities)
  - Summary with restoration estimates
"""

from __future__ import annotations

import logging
import random
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .physics.cascade_detector import CascadeDetector, Asset, AssetType, Dependency

logger = logging.getLogger("sindio.services.cascade_analyzer")

# ── Nairobi geography ──────────────────────────────────────────────────────────

WARD_POPULATIONS: Dict[str, int] = {
    "Central": 50000,
    "Westlands": 120000,
    "Langata": 200000,
    "Dagoretti North": 150000,
    "Dagoretti South": 150000,
    "Kasarani": 200000,
    "Roysambu": 150000,
    "Ruaraka": 150000,
    "Embakasi North": 150000,
    "Embakasi South": 150000,
    "Embakasi East": 250000,
    "Embakasi West": 150000,
    "Embakasi Central": 150000,
    "Starehe": 220000,
    "Mathare": 210000,
    "Kamukunji": 150000,
    "Makadara": 190000,
}

ALL_WARDS: List[str] = list(WARD_POPULATIONS.keys())


def _load_ward_populations(city_slug: str = "nairobi") -> Dict[str, int]:
    """Load ward populations from DB, fall back to city config or hardcoded."""
    try:
        from ..models.cascade import CascadeWardPopulation
        from sqlalchemy.orm import Session
        from ..database import get_engine
        with Session(bind=get_engine()) as session:
            rows = session.query(CascadeWardPopulation).filter_by(city_slug=city_slug).all()
            if rows:
                return {r.ward_name: r.population for r in rows}
    except Exception:
        pass
    try:
        from .city_config import get_city
        city = get_city(city_slug)
        if city and hasattr(city, "wards") and len(city.wards) > 0:
            return {w: 150000 for w in city.wards}
    except Exception:
        pass
    return WARD_POPULATIONS.copy()


# ── Power substations ─────────────────────────────────────────────────────────

POWER_SUBSTATIONS = {
    "ngong": {
        "name": "Ngong Substation",
        "lat": -1.2950,
        "lon": 36.7400,
        "serves_wards": ["Central", "Westlands", "Dagoretti North", "Dagoretti South", "Langata"],
        "capacity_mw": 120,
        "restoration_hours": 5,
    },
    "embakasi": {
        "name": "Embakasi Substation",
        "lat": -1.3250,
        "lon": 36.8900,
        "serves_wards": [
            "Kasarani", "Roysambu", "Ruaraka", "Embakasi North",
            "Embakasi South", "Embakasi East", "Embakasi West", "Embakasi Central",
        ],
        "capacity_mw": 150,
        "restoration_hours": 6,
    },
    "dandora": {
        "name": "Dandora Substation",
        "lat": -1.2500,
        "lon": 36.9100,
        "serves_wards": ["Starehe", "Mathare", "Kamukunji", "Makadara"],
        "capacity_mw": 100,
        "restoration_hours": 4,
    },
}

# ── Water pump stations ───────────────────────────────────────────────────────

WATER_PUMPS = {
    "kabete": {
        "name": "Kabete Pump Station",
        "lat": -1.2580,
        "lon": 36.7350,
        "powered_by": "ngong",
        "serves_wards": ["Westlands", "Dagoretti North"],
        "capacity_m3_day": 45000,
        "restoration_hours": 3,
    },
    "gigiri": {
        "name": "Gigiri Pump Station",
        "lat": -1.2350,
        "lon": 36.8200,
        "powered_by": "embakasi",
        "serves_wards": ["Roysambu", "Kasarani"],
        "capacity_m3_day": 38000,
        "restoration_hours": 3,
    },
    "karen": {
        "name": "Karen Pump Station",
        "lat": -1.3400,
        "lon": 36.7300,
        "powered_by": "ngong",
        "serves_wards": ["Langata", "Dagoretti South"],
        "capacity_m3_day": 32000,
        "restoration_hours": 4,
    },
    "industrial_area": {
        "name": "Industrial Area Pump Station",
        "lat": -1.3200,
        "lon": 36.8600,
        "powered_by": "embakasi",
        "serves_wards": ["Embakasi South", "Embakasi East", "Embakasi Central"],
        "capacity_m3_day": 50000,
        "restoration_hours": 3,
    },
    "dandora_pump": {
        "name": "Dandora Pump Station",
        "lat": -1.2480,
        "lon": 36.9050,
        "powered_by": "dandora",
        "serves_wards": ["Mathare", "Kamukunji", "Makadara", "Starehe", "Ruaraka"],
        "capacity_m3_day": 35000,
        "restoration_hours": 4,
    },
}

# ── Critical facilities ────────────────────────────────────────────────────────

CRITICAL_FACILITIES: List[Dict[str, Any]] = [
    {
        "name": "Kenyatta National Hospital",
        "type": "hospital",
        "ward": "Westlands",
        "lat": -1.3000, "lon": 36.8000,
        "beds": 1800,
    },
    {
        "name": "Mbagathi Hospital",
        "type": "hospital",
        "ward": "Langata",
        "lat": -1.3600, "lon": 36.7800,
        "beds": 500,
    },
    {
        "name": "Mathare Teaching & Referral Hospital",
        "type": "hospital",
        "ward": "Mathare",
        "lat": -1.2600, "lon": 36.8600,
        "beds": 600,
    },
    {
        "name": "Mama Lucy Kibaki Hospital",
        "type": "hospital",
        "ward": "Embakasi East",
        "lat": -1.3100, "lon": 36.9300,
        "beds": 400,
    },
    {
        "name": "Nairobi Hospital",
        "type": "hospital",
        "ward": "Central",
        "lat": -1.2900, "lon": 36.8100,
        "beds": 350,
    },
    {
        "name": "University of Nairobi",
        "type": "university",
        "ward": "Central",
        "lat": -1.2800, "lon": 36.8200,
        "students": 70000,
    },
    {
        "name": "Kenyatta University",
        "type": "university",
        "ward": "Kasarani",
        "lat": -1.1800, "lon": 36.9300,
        "students": 75000,
    },
    {
        "name": "Riara University",
        "type": "university",
        "ward": "Langata",
        "lat": -1.3500, "lon": 36.7700,
        "students": 5000,
    },
    {
        "name": "Daystar University",
        "type": "university",
        "ward": "Kamukunji",
        "lat": -1.2700, "lon": 36.8500,
        "students": 4000,
    },
    {
        "name": "Jomo Kenyatta International Airport",
        "type": "airport",
        "ward": "Embakasi East",
        "lat": -1.3190, "lon": 36.9278,
    },
]

# ── Utility ────────────────────────────────────────────────────────────────────


def _ward_for_substation(sub_id: str) -> str:
    sub = POWER_SUBSTATIONS.get(sub_id)
    if sub and sub["serves_wards"]:
        return sub["serves_wards"][0]
    return ""


def _ward_for_pump(pump_id: str) -> str:
    pump = WATER_PUMPS.get(pump_id)
    if pump and pump["serves_wards"]:
        return pump["serves_wards"][0]
    return ""


# ── Internal graph node ────────────────────────────────────────────────────────


@dataclass
class _CascadeNode:
    """Internal node for cascade propagation, more detailed than base Asset."""

    asset_id: str
    asset_type: str  # power_substation | water_pump | water_supply | traffic_signals | cell_tower | road_cell
    status: str = "operational"
    failure_cause: str = ""
    cascade_depth: int = 0
    time_offset_minutes: int = 0
    description: str = ""
    affected_wards: List[str] = field(default_factory=list)


# ── Analyzer ───────────────────────────────────────────────────────────────────


class CascadeAnalyzer:
    def __init__(self, city_slug: str = "nairobi"):
        self.city_slug = city_slug
        self.detector = CascadeDetector()
        self._nodes: Dict[str, _CascadeNode] = {}
        self._adj_out: Dict[str, List[Tuple[str, str]]] = {}
        self._rng = random.Random(42)

    # ── Build graph ────────────────────────────────────────────────────────

    def _build_nairobi_graph(self) -> None:
        """Build the full Nairobi infrastructure dependency graph."""
        self._nodes.clear()
        self._adj_out.clear()

        substations, pumps = self._load_db_assets()

        for sub_id, sub in substations.items():
            self._nodes[sub_id] = _CascadeNode(
                asset_id=sub_id,
                asset_type="power_substation",
                description=sub["name"],
                affected_wards=list(sub["serves_wards"]),
            )
            for ward in sub["serves_wards"]:
                power_ward_id = f"power_ward_{ward.lower().replace(' ', '_')}"
                self._nodes[power_ward_id] = _CascadeNode(
                    asset_id=power_ward_id,
                    asset_type="power_supply",
                    description=f"Power supply to {ward}",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(sub_id, []).append(
                    (power_ward_id, "power_to_ward")
                )

            for ward in sub["serves_wards"]:
                tower_id = f"cell_tower_{ward.lower().replace(' ', '_')}"
                power_ward_id = f"power_ward_{ward.lower().replace(' ', '_')}"
                self._nodes[tower_id] = _CascadeNode(
                    asset_id=tower_id,
                    asset_type="cell_tower",
                    description=f"Cell towers in {ward}",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(power_ward_id, []).append(
                    (tower_id, "power_to_tower")
                )

            for ward in sub["serves_wards"]:
                signal_id = f"signals_{ward.lower().replace(' ', '_')}"
                power_ward_id = f"power_ward_{ward.lower().replace(' ', '_')}"
                self._nodes[signal_id] = _CascadeNode(
                    asset_id=signal_id,
                    asset_type="traffic_signals",
                    description=f"Traffic signals in {ward}",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(power_ward_id, []).append(
                    (signal_id, "power_to_signals")
                )

            for ward in sub["serves_wards"]:
                road_id = f"road_congestion_{ward.lower().replace(' ', '_')}"
                signal_id = f"signals_{ward.lower().replace(' ', '_')}"
                self._nodes[road_id] = _CascadeNode(
                    asset_id=road_id,
                    asset_type="road_congestion",
                    description=f"Road congestion in {ward}",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(signal_id, []).append(
                    (road_id, "signals_to_road")
                )

        for pump_id, pump in pumps.items():
            self._nodes[pump_id] = _CascadeNode(
                asset_id=pump_id,
                asset_type="water_pump",
                description=pump["name"],
                affected_wards=list(pump["serves_wards"]),
            )
            sub_id = pump["powered_by"]
            self._adj_out.setdefault(sub_id, []).append(
                (pump_id, "power_to_pump")
            )

            for ward in pump["serves_wards"]:
                water_ward_id = f"water_ward_{ward.lower().replace(' ', '_')}"
                self._nodes[water_ward_id] = _CascadeNode(
                    asset_id=water_ward_id,
                    asset_type="water_supply",
                    description=f"Water supply to {ward}",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(pump_id, []).append(
                    (water_ward_id, "pump_to_water")
                )

            for ward in pump["serves_wards"]:
                subsidence_id = f"road_subsidence_{ward.lower().replace(' ', '_')}"
                water_ward_id = f"water_ward_{ward.lower().replace(' ', '_')}"
                self._nodes[subsidence_id] = _CascadeNode(
                    asset_id=subsidence_id,
                    asset_type="road_subsidence",
                    description=f"Road subsidence risk in {ward} from water pipe burst",
                    affected_wards=[ward],
                )
                self._adj_out.setdefault(water_ward_id, []).append(
                    (subsidence_id, "water_to_subsidence")
                )

        logger.info(
            "Nairobi cascade graph built: %d nodes, %d edges",
            len(self._nodes),
            sum(len(v) for v in self._adj_out.values()),
        )

    def _load_db_assets(self):
        try:
            from ..models.cascade import CascadeAsset
            from sqlalchemy.orm import Session
            from ..database import get_engine
            with Session(bind=get_engine()) as session:
                rows = session.query(CascadeAsset).filter_by(city_slug=self.city_slug).all()
                if rows:
                    subs = {}
                    pumps = {}
                    for a in rows:
                        d = {"name": a.name, "serves_wards": a.serves_wards or []}
                        if a.asset_type == "power_substation":
                            d.update({"lat": a.lat, "lon": a.lon,
                                      "capacity_mw": a.capacity_mw,
                                      "restoration_hours": a.restoration_hours})
                            subs[a.asset_id] = d
                        elif a.asset_type == "water_pump":
                            d.update({"lat": a.lat, "lon": a.lon,
                                      "capacity_m3_day": a.capacity_m3_day,
                                      "powered_by": a.powered_by,
                                      "restoration_hours": a.restoration_hours})
                            pumps[a.asset_id] = d
                    if subs and pumps:
                        return subs, pumps
        except Exception as e:
            logger.warning("Cascade assets DB load failed: %s. Using hardcoded.", e)
        return POWER_SUBSTATIONS, WATER_PUMPS

    @staticmethod
    def _time_offset_for(asset_type: str, parent_depth: int) -> int:
        """Estimate minutes until this asset fails after parent failure."""
        offsets = {
            "power_substation": 0,
            "power_supply": 0,
            "cell_tower": 15,
            "traffic_signals": 0,
            "water_pump": 60,
            "water_supply": 90,
            "road_congestion": 30,
            "road_subsidence": 120,
        }
        base = offsets.get(asset_type, 30)
        return base + parent_depth * 5

    # ── Propagation ────────────────────────────────────────────────────────

    def _propagate(self, seed_id: str) -> Tuple[List[Dict[str, Any]], Set[str], int]:
        """BFS propagation from seed. Returns (events, total_wards_affected, max_depth)."""
        failed: Set[str] = set()
        events: List[Dict[str, Any]] = []
        queue: List[Tuple[str, int, str, int]] = []

        seed = self._nodes.get(seed_id)
        if not seed:
            return events, set(), 0

        failed.add(seed_id)
        seed.status = "failed"
        seed.failure_cause = "initial_failure"
        seed.time_offset_minutes = 0

        events.append({
            "step": 1,
            "asset_id": seed_id,
            "asset_type": seed.asset_type,
            "description": seed.description,
            "failure_cause": "Initial failure trigger",
            "time_offset_minutes": 0,
            "affected_wards": list(seed.affected_wards),
            "cascade_depth": 0,
        })

        wards_affected: Set[str] = set(seed.affected_wards)

        for dep_id, dep_type in self._adj_out.get(seed_id, []):
            if dep_id not in failed:
                failed.add(dep_id)
                target = self._nodes.get(dep_id)
                if target:
                    target.status = "failed"
                    target.cascade_depth = 1
                    target.failure_cause = f"cascade_from_{seed_id}_{dep_type}"
                    target.time_offset_minutes = self._time_offset_for(target.asset_type, 0)
                    queue.append((dep_id, 1, f"cascade_from_{seed_id}_{dep_type}", target.time_offset_minutes))
                    wards_affected.update(target.affected_wards)

        while queue:
            current_id, depth, cause, time_offset = queue.pop(0)
            current = self._nodes.get(current_id)
            if not current:
                continue

            events.append({
                "step": len(events) + 1,
                "asset_id": current_id,
                "asset_type": current.asset_type,
                "description": current.description,
                "failure_cause": cause,
                "time_offset_minutes": time_offset,
                "affected_wards": list(current.affected_wards),
                "cascade_depth": depth,
            })

            wards_affected.update(current.affected_wards)

            for child_id, dep_type in self._adj_out.get(current_id, []):
                if child_id not in failed:
                    failed.add(child_id)
                    child = self._nodes.get(child_id)
                    if child:
                        child.status = "failed"
                        child.cascade_depth = depth + 1
                        child.failure_cause = f"cascade_from_{current_id}_{dep_type}"
                        child.time_offset_minutes = self._time_offset_for(child.asset_type, depth)
                        queue.append((child_id, depth + 1, f"cascade_from_{current_id}_{dep_type}", child.time_offset_minutes))
                        wards_affected.update(child.affected_wards)

        events.sort(key=lambda e: e["time_offset_minutes"])
        for i, ev in enumerate(events):
            ev["step"] = i + 1

        return events, wards_affected, max((e["cascade_depth"] for e in events), default=0)

    # ── Result assembly ────────────────────────────────────────────────────

    def _build_affected_wards(
        self, events: List[Dict[str, Any]], seed_asset_type: str, city_slug: str = "nairobi"
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate event data into per-ward impact summary."""
        ward_power: Set[str] = set()
        ward_water: Set[str] = set()
        ward_roads: Set[str] = set()
        ward_towers: Set[str] = set()

        for ev in events:
            t = ev["asset_type"]
            for w in ev["affected_wards"]:
                if t == "power_supply":
                    ward_power.add(w)
                elif t == "water_supply":
                    ward_water.add(w)
                elif t in ("road_congestion", "road_subsidence"):
                    ward_roads.add(w)
                elif t == "cell_tower":
                    ward_towers.add(w)

            if t == "power_substation":
                for w in ev["affected_wards"]:
                    ward_power.add(w)

        # Collect all unique wards from all affected sets
        all_wards = ward_power | ward_water | ward_roads | ward_towers

        ward_pops = _load_ward_populations(city_slug)
        result: Dict[str, Dict[str, Any]] = {}
        for ward in all_wards:
            pop = ward_pops.get(ward, 150000)
            power_out_ratio = 1.0 if ward in ward_power else 0.0
            water_out_ratio = 1.0 if ward in ward_water else (0.3 if ward in ward_power else 0.0)

            result[ward] = {
                "pop_affected": int(pop * max(power_out_ratio, water_out_ratio)),
                "total_population": pop,
                "power_out": ward in ward_power,
                "water_out": ward in ward_water or (ward in ward_power and ward not in ward_water),
                "roads_blocked": ward in ward_roads,
                "communication_down": ward in ward_towers,
                "estimated_restoration_hours": self._estimate_ward_restoration(
                    ward, power_out_ratio, water_out_ratio, city_slug
                ),
            }

        return result

    def _estimate_ward_restoration(self, ward: str, power_ratio: float, water_ratio: float, city_slug: str = "nairobi") -> float:
        """Estimate hours to restore services in a ward."""
        hours = 0.0
        if power_ratio > 0 and power_ratio < 1:
            hours += 2.0
        if water_ratio > 0:
            hours += 3.0
        if power_ratio >= 1.0:
            hours += 4.0
        if water_ratio >= 1.0:
            hours += 4.0
        ward_pops = _load_ward_populations(city_slug)
        return round(hours + ward_pops.get(ward, 150000) / 100000, 1)

    def _build_critical_facilities(
        self, affected_wards: Set[str]
    ) -> List[Dict[str, Any]]:
        """Identify critical facilities in affected wards. DB-first, fallback to hardcoded."""
        facilities_data = CRITICAL_FACILITIES
        try:
            from ..models.cascade import CascadeCriticalFacility
            from sqlalchemy.orm import Session
            from ..database import get_engine
            with Session(bind=get_engine()) as session:
                rows = session.query(CascadeCriticalFacility).filter_by(
                    city_slug=self.city_slug).all()
                if rows:
                    facilities_data = [{
                        "name": f.name, "type": f.facility_type, "ward": f.ward,
                        "lat": f.lat, "lon": f.lon,
                        "beds": f.beds, "students": f.students,
                        "annual_passengers": f.annual_passengers,
                    } for f in rows]
        except Exception:
            pass

        impacted = []
        for facility in facilities_data:
            if facility["ward"] in affected_wards:
                entry = dict(facility)
                entry["impacts"] = []
                if facility["ward"] in affected_wards:
                    entry["impacts"].append("power_outage")
                    if facility["type"] == "hospital":
                        entry["impacts"].append("backup_generator_required")
                impacted.append(entry)
        return impacted

    def _build_summary(
        self,
        events: List[Dict[str, Any]],
        affected_wards: Dict[str, Dict[str, Any]],
        critical_facilities: List[Dict[str, Any]],
        seed_id: str,
        seed_asset_type: str,
    ) -> Dict[str, Any]:
        """Produce the high-level summary."""
        total_pop = sum(w["total_population"] for w in affected_wards.values())
        total_affected = sum(w["pop_affected"] for w in affected_wards.values())
        wards_with_power_out = sum(1 for w in affected_wards.values() if w["power_out"])
        wards_with_water_out = sum(1 for w in affected_wards.values() if w["water_out"])
        wards_with_roads = sum(1 for w in affected_wards.values() if w["roads_blocked"])
        hospitals = [f for f in critical_facilities if f["type"] == "hospital"]
        universities = [f for f in critical_facilities if f["type"] == "university"]

        sectors = {"power"}
        if any(w["water_out"] for w in affected_wards.values()):
            sectors.add("water")
        if any(w["roads_blocked"] for w in affected_wards.values()):
            sectors.add("roads")
        if any(w["communication_down"] for w in affected_wards.values()):
            sectors.add("communications")

        max_restoration = max(
            (w["estimated_restoration_hours"] for w in affected_wards.values()),
            default=0,
        )

        seed_name = (
            POWER_SUBSTATIONS.get(seed_id, {}).get("name", seed_id)
            if seed_asset_type == "power_substation"
            else WATER_PUMPS.get(seed_id, {}).get("name", seed_id)
        )

        return {
            "trigger_asset": seed_name,
            "trigger_asset_type": seed_asset_type,
            "total_population_in_area": total_pop,
            "total_pop_affected": total_affected,
            "wards_affected": len(affected_wards),
            "wards_with_power_out": wards_with_power_out,
            "wards_with_water_out": wards_with_water_out,
            "wards_with_road_congestion": wards_with_roads,
            "sectors_impacted": sorted(sectors),
            "hospitals_affected": len(hospitals),
            "universities_affected": len(universities),
            "critical_facilities_count": len(critical_facilities),
            "estimated_restoration_hours": max_restoration,
            "estimated_full_restoration_hours": max_restoration + 2.0,
            "cascade_depth": max((e["cascade_depth"] for e in events), default=0),
            "total_failure_events": len(events),
            # Frontend-compatible aliases
            "asset_name": seed_name,
            "asset_type": seed_asset_type,
            "total_population_affected": total_affected,
            "wards": sorted(affected_wards.keys()),
        }

    # ── Public API ─────────────────────────────────────────────────────────

    def analyze_cascade(
        self, asset_type: str, asset_id: str, city_slug: str = "nairobi"
    ) -> Dict[str, Any]:
        """Run full cascade failure analysis.

        Args:
            asset_type: One of power_substation, water_pump, water_pipe, traffic_signal
            asset_id: Specific asset identifier (e.g. ngong, kabete)
            city_slug: City to analyze (nairobi only for now)

        Returns:
            Dict with cascade_chain, affected_wards, critical_facilities, summary
        """
        if city_slug != "nairobi":
            return {
                "error": f"City '{city_slug}' is not yet supported for cascade analysis",
                "supported_cities": ["nairobi"],
            }

        self._build_nairobi_graph()

        valid_types = {"power_substation", "water_pump", "water_pipe", "traffic_signal"}
        if asset_type not in valid_types:
            return {
                "error": f"Unsupported asset type: {asset_type}",
                "valid_types": sorted(valid_types),
            }

        # Validate the asset exists
        if asset_type == "power_substation" and asset_id not in POWER_SUBSTATIONS:
            valid = list(POWER_SUBSTATIONS.keys())
            return {
                "error": f"Unknown power substation: {asset_id}",
                "valid_asset_ids": valid,
            }

        if asset_type == "water_pump" and asset_id not in WATER_PUMPS:
            valid = list(WATER_PUMPS.keys())
            return {
                "error": f"Unknown water pump: {asset_id}",
                "valid_asset_ids": valid,
            }

        if asset_type not in ("power_substation", "water_pump"):
            return {
                "error": f"Cascade analysis for {asset_type} requires a seed power_substation "
                f"or water_pump as the initial failure",
                "valid_types": ["power_substation", "water_pump"],
            }

        if asset_id not in self._nodes:
            return {
                "error": f"Asset '{asset_id}' not found in the cascade graph",
            }

        logger.info("Starting cascade analysis for %s/%s", asset_type, asset_id)

        events, wards_affected, _max_depth = self._propagate(asset_id)

        affected_wards_data = self._build_affected_wards(events, asset_type, city_slug)
        critical_facilities = self._build_critical_facilities(set(affected_wards_data.keys()))
        summary = self._build_summary(events, affected_wards_data, critical_facilities, asset_id, asset_type)

        result = {
            "city": city_slug,
            "cascade_chain": events,
            "affected_wards": affected_wards_data,
            "critical_facilities": critical_facilities,
            "summary": summary,
        }

        threading.Thread(
            target=_persist_analysis, args=(result, city_slug, asset_type, asset_id), daemon=True
        ).start()

        return result

    def list_assets(self, city_slug: str = "nairobi") -> Dict[str, Any]:
        """Return all analyzable assets grouped by type. DB-first, fallback to hardcoded."""
        if city_slug != "nairobi":
            return {"error": f"City '{city_slug}' not supported", "supported_cities": ["nairobi"]}

        try:
            from ..models.cascade import CascadeAsset, CascadeCriticalFacility
            from sqlalchemy.orm import Session
            from ..database import get_engine
            with Session(bind=get_engine()) as session:
                db_assets = session.query(CascadeAsset).filter_by(city_slug=city_slug).all()
                db_facilities = session.query(CascadeCriticalFacility).filter_by(city_slug=city_slug).all()

                if db_assets:
                    substations = []
                    pumps = []
                    for a in db_assets:
                        item = {
                            "asset_id": a.asset_id, "name": a.name, "type": a.asset_type,
                            "lat": a.lat, "lon": a.lon,
                            "serves_wards": a.serves_wards or [],
                            "wards_count": len(a.serves_wards or []),
                        }
                        if a.asset_type == "power_substation":
                            item["capacity_mw"] = a.capacity_mw
                            substations.append(item)
                        elif a.asset_type == "water_pump":
                            item["capacity_m3_day"] = a.capacity_m3_day
                            item["powered_by"] = a.powered_by
                            pumps.append(item)

                    facilities = [{
                        "name": f.name, "type": f.facility_type, "ward": f.ward,
                        "lat": f.lat, "lon": f.lon,
                        "beds": f.beds, "students": f.students,
                        "annual_passengers": f.annual_passengers,
                    } for f in db_facilities]

                    wards = _load_ward_populations(city_slug)

                    return {
                        "city": city_slug, "source": "database",
                        "assets": {"power_substations": substations, "water_pumps": pumps},
                        "critical_facilities": facilities,
                        "wards": [{"name": w, "population": p} for w, p in sorted(wards.items())],
                    }
        except Exception:
            pass

        return {
            "city": city_slug,
            "assets": {
                "power_substations": [
                    {
                        "asset_id": sid,
                        "name": s["name"],
                        "type": "power_substation",
                        "capacity_mw": s["capacity_mw"],
                        "serves_wards": s["serves_wards"],
                        "wards_count": len(s["serves_wards"]),
                        "lat": s["lat"],
                        "lon": s["lon"],
                    }
                    for sid, s in POWER_SUBSTATIONS.items()
                ],
                "water_pumps": [
                    {
                        "asset_id": pid,
                        "name": p["name"],
                        "type": "water_pump",
                        "powered_by": p["powered_by"],
                        "serves_wards": p["serves_wards"],
                        "wards_count": len(p["serves_wards"]),
                        "capacity_m3_day": p["capacity_m3_day"],
                        "lat": p["lat"],
                        "lon": p["lon"],
                    }
                    for pid, p in WATER_PUMPS.items()
                ],
            },
            "critical_facilities": CRITICAL_FACILITIES,
            "wards": [{"name": w, "population": p} for w, p in sorted(WARD_POPULATIONS.items())],
        }

    def get_dependencies(self, asset_id: str, city_slug: str = "nairobi") -> Dict[str, Any]:
        """Return the dependency graph for a specific asset."""
        if city_slug != "nairobi":
            return {"error": f"City '{city_slug}' not supported"}

        self._build_nairobi_graph()

        if asset_id not in self._nodes:
            return {
                "error": f"Asset '{asset_id}' not found",
                "available_assets": sorted(self._nodes.keys()),
            }

        node = self._nodes[asset_id]
        deps_out = [
            {
                "target_id": target,
                "dependency_type": dtype,
                "target_type": self._nodes[target].asset_type if target in self._nodes else "unknown",
                "target_description": self._nodes[target].description if target in self._nodes else "",
            }
            for target, dtype in self._adj_out.get(asset_id, [])
        ]

        deps_in = []
        for src, edges in self._adj_out.items():
            for target, dtype in edges:
                if target == asset_id:
                    deps_in.append({
                        "source_id": src,
                        "dependency_type": dtype,
                        "source_type": self._nodes[src].asset_type if src in self._nodes else "unknown",
                        "source_description": self._nodes[src].description if src in self._nodes else "",
                    })

        return {
            "asset_id": asset_id,
            "asset_type": node.asset_type,
            "description": node.description,
            "affected_wards": node.affected_wards,
            "dependents": deps_out,
            "depends_on": deps_in,
            "total_dependents": len(deps_out),
            "total_dependencies": len(deps_in),
        }


def _persist_analysis(result: Dict[str, Any], city_slug: str, asset_type: str, asset_id: str) -> None:
    """Persist cascade analysis result to database."""
    try:
        from ..models.cascade import CascadeBase, CascadeAnalysis
        from sqlalchemy.orm import Session
        from ..database import get_engine

        engine = get_engine()
        CascadeBase.metadata.create_all(bind=engine)

        analysis_id = f"CA-{uuid.uuid4().hex[:12].upper()}"
        summary = result.get("summary", {})

        with Session(bind=engine) as session:
            analysis = CascadeAnalysis(
                analysis_id=analysis_id,
                city_slug=city_slug,
                trigger_asset_type=asset_type,
                trigger_asset_id=asset_id,
                cascade_chain=result.get("cascade_chain", []),
                affected_wards=result.get("affected_wards", {}),
                critical_facilities=result.get("critical_facilities", []),
                summary=summary,
                total_events=summary.get("total_failure_events", 0),
                total_pop_affected=summary.get("total_pop_affected", 0),
                cascade_depth=summary.get("cascade_depth", 0),
            )
            session.add(analysis)
            session.commit()
            logger.info("Cascade analysis persisted: %s", analysis_id)
    except Exception as exc:
        logger.warning("Failed to persist cascade analysis: %s", exc)


def get_cascade_history(city_slug: str = "nairobi", limit: int = 20) -> list[dict]:
    """Retrieve past cascade analyses from database."""
    try:
        from ..models.cascade import CascadeAnalysis
        from sqlalchemy.orm import Session
        from sqlalchemy import desc
        from ..database import get_engine

        with Session(bind=get_engine()) as session:
            analyses = (
                session.query(CascadeAnalysis)
                .filter(CascadeAnalysis.city_slug == city_slug)
                .order_by(desc(CascadeAnalysis.created_at))
                .limit(limit)
                .all()
            )
            return [a.to_dict() for a in analyses]
    except Exception as exc:
        logger.warning("Failed to retrieve cascade history: %s", exc)
        return []
