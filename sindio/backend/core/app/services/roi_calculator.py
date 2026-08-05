from __future__ import annotations

import logging
import threading
import uuid

logger = logging.getLogger("sindio.roi")

_KES_PER_USD = 145.0

INFRA_TYPES = (
    "power",
    "water",
    "roads",
    "solid_waste",
    "sidewalks",
    "lrt",
    "sgr",
    "airports",
)

COST_MODELS: dict[str, dict] = {
    "power": {
        "outage_cost_industrial_per_hour": 725000,
        "outage_cost_residential_per_1k_households_per_hour": 72500,
        "typical_outage_hours_per_year": 48,
        "typical_households_served": 5000,
        "maintenance_savings_pct": 0.15,
        "efficiency_gain_pct": 0.10,
    },
    "water": {
        "pipe_burst_repair_cost": 2175000,
        "water_trucking_cost_per_day": 290000,
        "typical_bursts_per_year": 4,
        "typical_repair_days": 7,
        "maintenance_savings_pct": 0.12,
        "efficiency_gain_pct": 0.08,
    },
    "roads": {
        "congestion_cost_per_vehicle_per_hour": 1160,
        "road_repair_cost_per_km": 7250000,
        "typical_daily_vehicles": 10000,
        "typical_congested_hours_per_day": 3,
        "maintenance_savings_pct": 0.20,
        "efficiency_gain_pct": 0.12,
    },
    "solid_waste": {
        "collection_failure_cost_per_route_per_day": 29000,
        "typical_routes": 50,
        "typical_failure_days_per_year": 30,
        "maintenance_savings_pct": 0.10,
        "efficiency_gain_pct": 0.06,
    },
    "sidewalks": {
        "detour_cost_per_person_per_day": 145,
        "typical_daily_pedestrians": 2000,
        "typical_blocked_days_per_year": 90,
        "maintenance_savings_pct": 0.08,
        "efficiency_gain_pct": 0.04,
    },
    "lrt": {
        "delay_cost_per_minute_per_500_passengers": 72500,
        "typical_delay_minutes_per_day": 15,
        "typical_operating_days_per_year": 345,
        "maintenance_savings_pct": 0.14,
        "efficiency_gain_pct": 0.09,
    },
    "sgr": {
        "freight_delay_cost_per_hour": 145000,
        "typical_delay_hours_per_year": 60,
        "maintenance_savings_pct": 0.13,
        "efficiency_gain_pct": 0.07,
    },
    "airports": {
        "flight_delay_cost_per_minute_per_flight": 10875,
        "typical_flights_per_day": 80,
        "typical_delay_minutes_per_flight": 8,
        "typical_delayed_flights_pct": 0.15,
        "maintenance_savings_pct": 0.11,
        "efficiency_gain_pct": 0.05,
    },
}


def _compute_avoided_outage(infra_type: str, model: dict) -> tuple[float, float, str]:
    if infra_type == "power":
        outage_cost_per_hour = (
            model["outage_cost_industrial_per_hour"]
            + model["outage_cost_residential_per_1k_households_per_hour"]
            * model["typical_households_served"]
            / 1000
        )
        annual_cost = outage_cost_per_hour * model["typical_outage_hours_per_year"]
        days = model["typical_outage_hours_per_year"] / 24
        desc = f"Avoided {model['typical_outage_hours_per_year']} outage-hours/year (industrial + residential)"
        return annual_cost, days, desc

    elif infra_type == "water":
        annual_cost = model["pipe_burst_repair_cost"] * model["typical_bursts_per_year"] + (
            model["water_trucking_cost_per_day"]
            * model["typical_repair_days"]
            * model["typical_bursts_per_year"]
        )
        days = model["typical_repair_days"] * model["typical_bursts_per_year"]
        desc = f"Avoided {model['typical_bursts_per_year']} pipe bursts/year at KES {model['pipe_burst_repair_cost']}/repair"
        return annual_cost, days, desc

    elif infra_type == "roads":
        annual_cost = (
            model["congestion_cost_per_vehicle_per_hour"]
            * model["typical_daily_vehicles"]
            * model["typical_congested_hours_per_day"]
            * 365
        )
        hours = model["typical_congested_hours_per_day"] * 365
        days = hours / 24
        desc = f"Reduced congestion for {model['typical_daily_vehicles']:,} vehicles/day at KES {model['congestion_cost_per_vehicle_per_hour']}/hr"
        return annual_cost, days, desc

    elif infra_type == "solid_waste":
        annual_cost = (
            model["collection_failure_cost_per_route_per_day"]
            * model["typical_routes"]
            * model["typical_failure_days_per_year"]
        )
        days = model["typical_failure_days_per_year"]
        desc = f"Avoided {model['typical_failure_days_per_year']} missed collection days across {model['typical_routes']} routes"
        return annual_cost, days, desc

    elif infra_type == "sidewalks":
        annual_cost = (
            model["detour_cost_per_person_per_day"]
            * model["typical_daily_pedestrians"]
            * model["typical_blocked_days_per_year"]
        )
        days = model["typical_blocked_days_per_year"]
        desc = f"Unblocked sidewalks for {model['typical_daily_pedestrians']:,} pedestrians/day over {model['typical_blocked_days_per_year']} days"
        return annual_cost, days, desc

    elif infra_type == "lrt":
        annual_cost = (
            model["delay_cost_per_minute_per_500_passengers"]
            * model["typical_delay_minutes_per_day"]
            * model["typical_operating_days_per_year"]
        )
        hours = model["typical_delay_minutes_per_day"] * model["typical_operating_days_per_year"]
        days = hours / 1440
        desc = f"Eliminated {model['typical_delay_minutes_per_day']} min/day train delays for 500 passengers"
        return annual_cost, days, desc

    elif infra_type == "sgr":
        annual_cost = model["freight_delay_cost_per_hour"] * model["typical_delay_hours_per_year"]
        days = model["typical_delay_hours_per_year"] / 24
        desc = f"Avoided {model['typical_delay_hours_per_year']} hours of freight delay at KES {model['freight_delay_cost_per_hour']}/hr"
        return annual_cost, days, desc

    elif infra_type == "airports":
        delayed = (
            model["typical_flights_per_day"]
            * 365
            * model["typical_delayed_flights_pct"]
        )
        annual_cost = (
            delayed
            * model["flight_delay_cost_per_minute_per_flight"]
            * model["typical_delay_minutes_per_flight"]
        )
        hours = delayed * model["typical_delay_minutes_per_flight"]
        days = hours / 1440
        desc = f"Reduced delays for {delayed:.0f} flights/year at KES {model['flight_delay_cost_per_minute_per_flight']}/min"
        return annual_cost, days, desc

    return 0.0, 0.0, "Unknown infrastructure type"


def calculate_roi(params: dict) -> dict:
    infra_type = params.get("infra_type", "power")
    upgrade_cost = float(params.get("upgrade_cost_kes", 36250000))
    description = params.get("upgrade_description", f"{infra_type} infrastructure upgrade")
    lifespan = int(params.get("asset_lifespan_years", 20))

    if infra_type not in INFRA_TYPES:
        valid = ", ".join(INFRA_TYPES)
        raise ValueError(f"Unknown infra_type '{infra_type}'. Valid types: {valid}")

    model = COST_MODELS[infra_type]

    outage_cost, outage_days, outage_desc = _compute_avoided_outage(infra_type, model)

    maintenance_savings = upgrade_cost * model["maintenance_savings_pct"]
    maintenance_desc = f"Reduced maintenance costs ({model['maintenance_savings_pct'] * 100:.0f}% of upgrade cost)"

    efficiency_gain = upgrade_cost * model["efficiency_gain_pct"]
    efficiency_desc = f"Operational efficiency gains ({model['efficiency_gain_pct'] * 100:.0f}% of upgrade cost)"

    annual_savings = outage_cost + maintenance_savings + efficiency_gain

    payback_years = upgrade_cost / annual_savings if annual_savings > 0 else float("inf")

    discount_rate = 0.05

    def _npv(years: int) -> float:
        total = 0.0
        for y in range(1, years + 1):
            total += annual_savings / ((1 + discount_rate) ** y)
        return round(total - upgrade_cost, 2)

    def _roi_pct(years: int) -> float:
        if upgrade_cost == 0:
            return 0.0
        return round(((annual_savings * years - upgrade_cost) / upgrade_cost) * 100, 1)

    npv = _npv(min(lifespan, 20))

    if annual_savings > upgrade_cost * 0.3:
        recommendation = "high"
    elif annual_savings > upgrade_cost * 0.1:
        recommendation = "medium"
    else:
        recommendation = "low"

    logger.info(
        "roi_calculated: infra_type=%s upgrade_cost=%s annual_savings=%s payback_years=%s recommendation=%s",
        infra_type, upgrade_cost, round(annual_savings, 2), round(payback_years, 2), recommendation,
    )

    result = {
        "upgrade_cost_kes": upgrade_cost,
        "upgrade_description": description,
        "asset_lifespan_years": lifespan,
        "estimated_annual_savings_kes": round(annual_savings, 2),
        "payback_period_years": round(payback_years, 2),
        "5yr_roi_pct": _roi_pct(5),
        "10yr_roi_pct": _roi_pct(10),
        "20yr_roi_pct": _roi_pct(20),
        "five_year_roi_pct": _roi_pct(5),
        "ten_year_roi_pct": _roi_pct(10),
        "twenty_year_roi_pct": _roi_pct(20),
        "avoided_outage_days_per_year": round(outage_days, 1),
        "avoided_outage_cost_per_year_kes": round(outage_cost, 2),
        "maintenance_savings_per_year_kes": round(maintenance_savings, 2),
        "efficiency_gain_savings_per_year_kes": round(efficiency_gain, 2),
        "npv_kes": npv,
        "recommendation": recommendation,
        "breakdown": {
            "outage_costs": {
                "annual": round(outage_cost, 2),
                "description": outage_desc,
            },
            "maintenance_savings": {
                "annual": round(maintenance_savings, 2),
                "description": maintenance_desc,
            },
            "efficiency_gains": {
                "annual": round(efficiency_gain, 2),
                "description": efficiency_desc,
            },
        },
    }

    city = params.get("city_slug", "nairobi")
    threading.Thread(
        target=_persist_roi,
        args=(result, params, city),
        daemon=True,
    ).start()

    return result


def list_upgrade_options(infra_type: str) -> list[dict]:
    """Return upgrade options for a given infrastructure type. DB-first, fallback to hardcoded."""
    if infra_type not in INFRA_TYPES:
        valid = ", ".join(INFRA_TYPES)
        raise ValueError(f"Unknown infra_type '{infra_type}'. Valid types: {valid}")

    try:
        from ..models.roi import UpgradeOption
        from sqlalchemy.orm import Session
        from ..database import get_engine
        with Session(bind=get_engine()) as session:
            rows = session.query(UpgradeOption).filter_by(infra_type=infra_type).all()
            if rows:
                return [{
                    "asset_id": r.asset_id,
                    "name": r.name,
                    "typical_cost_kes": r.typical_cost_kes,
                    "typical_annual_savings_kes": r.typical_annual_savings_kes,
                    "description": r.description,
                    "payback_years": r.payback_years,
                } for r in rows]
    except Exception:
        pass

    _K = _KES_PER_USD
    options = {
        "power": [
            {"asset_id": "power-substation-001", "name": "Substation Transformer Upgrade",
             "typical_cost_kes": 180000 * _K, "typical_annual_savings_kes": 55000 * _K,
             "description": "Replace aging transformer to reduce unplanned outages and improve voltage stability.", "payback_years": 3.0},
            {"asset_id": "power-substation-002", "name": "Distribution Line Reconductoring",
             "typical_cost_kes": 120000 * _K, "typical_annual_savings_kes": 40000 * _K,
             "description": "Upgrade distribution lines to reduce line losses and outage frequency.", "payback_years": 2.7},
            {"asset_id": "power-grid-automation", "name": "SCADA & Grid Automation",
             "typical_cost_kes": 350000 * _K, "typical_annual_savings_kes": 95000 * _K,
             "description": "Install remote monitoring and automated switching to reduce outage duration by 60%.", "payback_years": 3.7},
        ],
        "water": [
            {"asset_id": "water-pipeline-001", "name": "Pipeline Replacement (PVC to HDPE)",
             "typical_cost_kes": 200000 * _K, "typical_annual_savings_kes": 45000 * _K,
             "description": "Replace old PVC pipes with HDPE to reduce burst frequency and water loss.", "payback_years": 4.4},
            {"asset_id": "water-treatment-001", "name": "Treatment Plant Capacity Expansion",
             "typical_cost_kes": 500000 * _K, "typical_annual_savings_kes": 80000 * _K,
             "description": "Expand treatment capacity to meet growing demand and reduce rationing events.", "payback_years": 6.3},
            {"asset_id": "water-smart-meters", "name": "Smart Water Meter Network",
             "typical_cost_kes": 150000 * _K, "typical_annual_savings_kes": 35000 * _K,
             "description": "Deploy smart meters to detect leaks early and reduce non-revenue water.", "payback_years": 4.3},
        ],
        "roads": [
            {"asset_id": "road-intersection-001", "name": "Intersection Signal Optimization",
             "typical_cost_kes": 80000 * _K, "typical_annual_savings_kes": 60000 * _K,
             "description": "Install adaptive traffic signals to reduce peak-hour congestion by 25%.", "payback_years": 1.3},
            {"asset_id": "road-resurface-001", "name": "Road Resurfacing (10 km)",
             "typical_cost_kes": 500000 * _K, "typical_annual_savings_kes": 90000 * _K,
             "description": "Full resurfacing of arterial road to reduce vehicle operating costs and travel time.", "payback_years": 5.6},
            {"asset_id": "road-drainage-001", "name": "Stormwater Drainage Upgrade",
             "typical_cost_kes": 250000 * _K, "typical_annual_savings_kes": 40000 * _K,
             "description": "Improve drainage to prevent road flooding and pothole formation during rain events.", "payback_years": 6.3},
        ],
        "solid_waste": [
            {"asset_id": "waste-compactor-001", "name": "Compactor Truck Fleet Renewal",
             "typical_cost_kes": 300000 * _K, "typical_annual_savings_kes": 50000 * _K,
             "description": "Replace aging compactor trucks to reduce breakdowns and missed collection routes.", "payback_years": 6.0},
            {"asset_id": "waste-transfer-001", "name": "Transfer Station Modernization",
             "typical_cost_kes": 450000 * _K, "typical_annual_savings_kes": 70000 * _K,
             "description": "Upgrade transfer station with sorting lines to reduce landfill volume and increase recycling.", "payback_years": 6.4},
        ],
        "sidewalks": [
            {"asset_id": "sidewalk-corridor-001", "name": "Complete Streets Corridor Upgrade",
             "typical_cost_kes": 180000 * _K, "typical_annual_savings_kes": 25000 * _K,
             "description": "Widen sidewalks, add ramps, and improve crossings along a major pedestrian corridor.", "payback_years": 7.2},
            {"asset_id": "sidewalk-network-001", "name": "Neighborhood Sidewalk Gap Closure",
             "typical_cost_kes": 320000 * _K, "typical_annual_savings_kes": 40000 * _K,
             "description": "Fill missing sidewalk segments across a neighborhood to create a complete pedestrian network.", "payback_years": 8.0},
        ],
        "lrt": [
            {"asset_id": "lrt-signaling-001", "name": "CBTC Signaling Upgrade",
             "typical_cost_kes": 2500000 * _K, "typical_annual_savings_kes": 350000 * _K,
             "description": "Upgrade to communications-based train control to increase frequency by 30%.", "payback_years": 7.1},
            {"asset_id": "lrt-station-001", "name": "Station Platform Extension",
             "typical_cost_kes": 800000 * _K, "typical_annual_savings_kes": 120000 * _K,
             "description": "Extend platforms to accommodate longer trains and increase per-trip capacity.", "payback_years": 6.7},
        ],
        "sgr": [
            {"asset_id": "sgr-rail-section-001", "name": "Rail Section Replacement (50 km)",
             "typical_cost_kes": 3000000 * _K, "typical_annual_savings_kes": 400000 * _K,
             "description": "Replace worn rail sections to reduce speed restrictions and maintenance interventions.", "payback_years": 7.5},
            {"asset_id": "sgr-freight-terminal-001", "name": "Freight Terminal Expansion",
             "typical_cost_kes": 5000000 * _K, "typical_annual_savings_kes": 600000 * _K,
             "description": "Expand freight handling capacity to reduce dwell time and increase throughput.", "payback_years": 8.3},
        ],
        "airports": [
            {"asset_id": "airport-runway-001", "name": "Runway Surface Rehabilitation",
             "typical_cost_kes": 4000000 * _K, "typical_annual_savings_kes": 700000 * _K,
             "description": "Rehabilitate runway surface to reduce closure hours and flight diversion events.", "payback_years": 5.7},
            {"asset_id": "airport-terminal-001", "name": "Terminal Baggage System Upgrade",
             "typical_cost_kes": 1200000 * _K, "typical_annual_savings_kes": 250000 * _K,
             "description": "Replace baggage handling system to reduce turnaround delays and lost baggage claims.", "payback_years": 4.8},
            {"asset_id": "airport-ils-001", "name": "ILS/Navigation Equipment Upgrade",
             "typical_cost_kes": 2000000 * _K, "typical_annual_savings_kes": 400000 * _K,
             "description": "Upgrade instrument landing system to reduce weather-related diversions and delays.", "payback_years": 5.0},
        ],
    }

    if infra_type not in options:
        valid = ", ".join(INFRA_TYPES)
        raise ValueError(f"Unknown infra_type '{infra_type}'. Valid types: {valid}")

    return options[infra_type]


def _persist_roi(result: dict, params: dict, city_slug: str) -> None:
    """Persist ROI calculation result to database."""
    try:
        from ..models.roi import RoiBase, RoiCalculation
        from sqlalchemy.orm import Session
        from ..database import get_engine

        engine = get_engine()
        RoiBase.metadata.create_all(bind=engine)

        calc_id = f"ROI-{uuid.uuid4().hex[:12].upper()}"

        with Session(bind=engine) as session:
            calc = RoiCalculation(
                calculation_id=calc_id,
                city_slug=city_slug,
                infra_type=params.get("infra_type", "power"),
                asset_id=params.get("asset_id", "unknown"),
                upgrade_description=params.get("upgrade_description", ""),
                upgrade_cost_usd=result["upgrade_cost_kes"],
                asset_lifespan_years=result["asset_lifespan_years"],
                estimated_annual_savings_usd=result["estimated_annual_savings_kes"],
                payback_period_years=result["payback_period_years"],
                five_year_roi_pct=result["5yr_roi_pct"],
                ten_year_roi_pct=result["10yr_roi_pct"],
                twenty_year_roi_pct=result["20yr_roi_pct"],
                npv_usd=result["npv_kes"],
                avoided_outage_days_per_year=result["avoided_outage_days_per_year"],
                avoided_outage_cost_per_year_usd=result["avoided_outage_cost_per_year_kes"],
                maintenance_savings_per_year_usd=result["maintenance_savings_per_year_kes"],
                efficiency_gain_savings_per_year_usd=result["efficiency_gain_savings_per_year_kes"],
                recommendation=result["recommendation"],
                breakdown=result["breakdown"],
            )
            session.add(calc)
            session.commit()
            logger.info("ROI calculation persisted", calculation_id=calc_id)
    except Exception as exc:
        logger.warning("Failed to persist ROI calculation: %s", exc)


def get_roi_history(city_slug: str = "nairobi", limit: int = 20) -> list[dict]:
    """Retrieve past ROI calculations from database."""
    try:
        from ..models.roi import RoiCalculation
        from sqlalchemy.orm import Session
        from sqlalchemy import desc
        from ..database import get_engine

        with Session(bind=get_engine()) as session:
            calcs = (
                session.query(RoiCalculation)
                .filter(RoiCalculation.city_slug == city_slug)
                .order_by(desc(RoiCalculation.created_at))
                .limit(limit)
                .all()
            )
            return [c.to_dict() for c in calcs]
    except Exception as exc:
        logger.warning("Failed to retrieve ROI history: %s", exc)
        return []
