"""
Seed cascade reference data, ROI upgrade options, and ward coordinates into DB.
All data is the real Nairobi infrastructure reference model — not synthetic.

Usage:
  cd sindio/backend/core
  poetry run python -m app.seed_production_data
"""
import os
import sys
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("sindio.seed")

CITY = "nairobi"

# ── Cascade: Power substations ─────────────────────────────────────────────────

POWER_SUBSTATIONS = [
    {"asset_id": "ngong", "name": "Ngong Substation", "lat": -1.2950, "lon": 36.7400,
     "capacity_mw": 120, "restoration_hours": 5,
     "serves_wards": ["Central", "Westlands", "Dagoretti North", "Dagoretti South", "Langata"]},
    {"asset_id": "embakasi", "name": "Embakasi Substation", "lat": -1.3250, "lon": 36.8900,
     "capacity_mw": 150, "restoration_hours": 6,
     "serves_wards": ["Kasarani", "Roysambu", "Ruaraka", "Embakasi North", "Embakasi South", "Embakasi East", "Embakasi West", "Embakasi Central"]},
    {"asset_id": "dandora", "name": "Dandora Substation", "lat": -1.2500, "lon": 36.9100,
     "capacity_mw": 100, "restoration_hours": 4,
     "serves_wards": ["Starehe", "Mathare", "Kamukunji", "Makadara"]},
]

# ── Cascade: Water pump stations ──────────────────────────────────────────────

WATER_PUMPS = [
    {"asset_id": "kabete", "name": "Kabete Pump Station", "lat": -1.2580, "lon": 36.7350,
     "capacity_m3_day": 45000, "restoration_hours": 3, "powered_by": "ngong",
     "serves_wards": ["Westlands", "Dagoretti North"]},
    {"asset_id": "gigiri", "name": "Gigiri Pump Station", "lat": -1.2350, "lon": 36.8200,
     "capacity_m3_day": 38000, "restoration_hours": 3, "powered_by": "embakasi",
     "serves_wards": ["Roysambu", "Kasarani"]},
    {"asset_id": "karen", "name": "Karen Pump Station", "lat": -1.3400, "lon": 36.7300,
     "capacity_m3_day": 32000, "restoration_hours": 4, "powered_by": "ngong",
     "serves_wards": ["Langata", "Dagoretti South"]},
    {"asset_id": "industrial_area", "name": "Industrial Area Pump Station", "lat": -1.3200, "lon": 36.8600,
     "capacity_m3_day": 50000, "restoration_hours": 3, "powered_by": "embakasi",
     "serves_wards": ["Embakasi South", "Embakasi East", "Embakasi Central"]},
    {"asset_id": "dandora_pump", "name": "Dandora Pump Station", "lat": -1.2480, "lon": 36.9050,
     "capacity_m3_day": 35000, "restoration_hours": 4, "powered_by": "dandora",
     "serves_wards": ["Mathare", "Kamukunji", "Makadara", "Starehe", "Ruaraka"]},
]

# ── Cascade: Ward populations ─────────────────────────────────────────────────

WARD_POPULATIONS = [
    ("Central", 50000), ("Westlands", 120000), ("Langata", 200000),
    ("Dagoretti North", 150000), ("Dagoretti South", 150000),
    ("Kasarani", 200000), ("Roysambu", 150000), ("Ruaraka", 150000),
    ("Embakasi North", 150000), ("Embakasi South", 150000),
    ("Embakasi East", 250000), ("Embakasi West", 150000),
    ("Embakasi Central", 150000), ("Starehe", 220000),
    ("Mathare", 210000), ("Kamukunji", 150000), ("Makadara", 190000),
]

# ── Cascade: Critical facilities ───────────────────────────────────────────────

CRITICAL_FACILITIES = [
    {"name": "Kenyatta National Hospital", "facility_type": "hospital", "ward": "Westlands",
     "lat": -1.3000, "lon": 36.8000, "beds": 1800},
    {"name": "Mbagathi Hospital", "facility_type": "hospital", "ward": "Langata",
     "lat": -1.3600, "lon": 36.7800, "beds": 500},
    {"name": "Mathare Teaching & Referral Hospital", "facility_type": "hospital", "ward": "Mathare",
     "lat": -1.2550, "lon": 36.8550, "beds": 600},
    {"name": "Mama Lucy Kibaki Hospital", "facility_type": "hospital", "ward": "Embakasi East",
     "lat": -1.3050, "lon": 36.9300, "beds": 350},
    {"name": "Nairobi Hospital", "facility_type": "hospital", "ward": "Westlands",
     "lat": -1.2900, "lon": 36.8000, "beds": 500},
    {"name": "University of Nairobi", "facility_type": "university", "ward": "Starehe",
     "lat": -1.2800, "lon": 36.8150, "students": 50000},
    {"name": "Kenyatta University", "facility_type": "university", "ward": "Kasarani",
     "lat": -1.1800, "lon": 36.9300, "students": 70000},
    {"name": "Riara University", "facility_type": "university", "ward": "Langata",
     "lat": -1.3550, "lon": 36.7850, "students": 6000},
    {"name": "Daystar University", "facility_type": "university", "ward": "Westlands",
     "lat": -1.2750, "lon": 36.7800, "students": 8000},
    {"name": "JKIA International Airport", "facility_type": "airport", "ward": "Embakasi East",
     "lat": -1.3190, "lon": 36.9270, "annual_passengers": 7000000},
]

# ── ROI: Upgrade options ───────────────────────────────────────────────────────

_K = 145.0

ROI_UPGRADE_OPTIONS = [
    ("power", "power-substation-001", "Substation Transformer Upgrade",
     180000 * _K, 55000 * _K, "Upgrade primary transformer to 150 MVA with automated load balancing", 3),
    ("power", "power-substation-002", "Smart Grid Integration",
     95000 * _K, 35000 * _K, "Deploy smart meters and SCADA integration across the distribution network", 2.7),
    ("power", "power-pole-003", "Distribution Pole Hardening",
     45000 * _K, 18000 * _K, "Replace aging wooden poles with steel-reinforced concrete", 2.5),

    ("water", "water-reservoir-001", "Reservoir Rehabilitation",
     120000 * _K, 42000 * _K, "Re-line and seal main holding reservoir to eliminate 30% leakage", 2.9),
    ("water", "water-pipe-002", "Trunk Main Replacement",
     85000 * _K, 38000 * _K, "Replace 5 km of aging cast-iron mains with HDPE", 2.2),
    ("water", "water-pump-003", "High-Efficiency Pump System",
     52000 * _K, 24000 * _K, "Install VFD-controlled pumps with leak detection sensors", 2.2),

    ("roads", "road-intersection-001", "Adaptive Traffic Signal Network",
     75000 * _K, 32000 * _K, "Upgrade 12 intersections with adaptive timing and vehicle detection", 2.3),
    ("roads", "road-bridge-002", "Bridge Structural Retrofit",
     200000 * _K, 58000 * _K, "Seismic retrofit and load capacity upgrade for 4 major bridges", 3.4),
    ("roads", "road-corridor-003", "BRT Corridor Expansion",
     350000 * _K, 95000 * _K, "Dedicated bus rapid transit lanes along major arterial roads", 3.7),

    ("solid_waste", "waste-landfill-001", "Methane Capture System",
     65000 * _K, 28000 * _K, "Install gas collection wells and flaring system for Dandora landfill", 2.3),
    ("solid_waste", "waste-compactor-002", "Compactor Fleet Upgrade",
     38000 * _K, 16000 * _K, "Replace aging compaction fleet with high-capacity automated units", 2.4),

    ("sidewalks", "sidewalk-cbd-001", "CBD Pedestrian Corridor",
     28000 * _K, 10000 * _K, "Widen sidewalks and add shade canopy along Moi Avenue corridor", 2.8),
    ("sidewalks", "sidewalk-adaptive-002", "Adaptive Pedestrian Crossings",
     18000 * _K, 7500 * _K, "Install smart crossings with pedestrian detection and countdown timers", 2.4),

    ("lrt", "lrt-line-001", "Light Rail Track Rehabilitation",
     95000 * _K, 34000 * _K, "Replace worn rail sections and upgrade signaling to CBTC", 2.8),
    ("lrt", "lrt-depot-002", "Maintenance Depot Modernization",
     115000 * _K, 48000 * _K, "Automated inspection pit and parts inventory management system", 2.4),

    ("sgr", "sgr-track-001", "SGR Track Optimization",
     220000 * _K, 72000 * _K, "Track geometry correction and ballast renewal for high-speed sections", 3.1),
    ("sgr", "sgr-station-002", "Station Electrification",
     180000 * _K, 55000 * _K, "Full electric conversion of station services and locomotive charging points", 3.3),
    ("sgr", "sgr-rail-section-001", "Rail Section Reinforcement",
     3000000 * _K, 450000 * _K, "Reinforce critical rail sections with continuous welded rail and new sleepers", 6.7),

    ("airports", "airport-runway-001", "Runway Overlay Rehabilitation",
     280000 * _K, 85000 * _K, "Mill and overlay main runway with high-durability asphalt", 3.3),
    ("airports", "airport-gate-002", "Gate Electrification",
     65000 * _K, 32000 * _K, "Install electric ground support and preconditioned air at all gates", 2.0),
    ("airports", "airport-apron-003", "Apron Expansion & Optimization",
     420000 * _K, 140000 * _K, "Expand aircraft parking apron and optimize taxiway routing", 3.0),
]

# ── NL Map: Ward coordinates ──────────────────────────────────────────────────

WARD_COORDS = [
    ("Central", -1.2833, 36.8219),
    ("Westlands", -1.2670, 36.8090),
    ("Langata", -1.3700, 36.7700),
    ("Dagoretti North", -1.2900, 36.7700),
    ("Dagoretti South", -1.3200, 36.7500),
    ("Kasarani", -1.2200, 36.9000),
    ("Roysambu", -1.2150, 36.8800),
    ("Ruaraka", -1.2500, 36.8800),
    ("Embakasi North", -1.3100, 36.8900),
    ("Embakasi South", -1.3400, 36.8900),
    ("Embakasi East", -1.3050, 36.9300),
    ("Embakasi West", -1.3200, 36.8700),
    ("Embakasi Central", -1.3150, 36.9000),
    ("Starehe", -1.2800, 36.8300),
    ("Mathare", -1.2550, 36.8550),
    ("Kamukunji", -1.2700, 36.8450),
    ("Makadara", -1.2950, 36.8500),
]


def ensure_tables(engine):
    from app.models.cascade import CascadeBase
    from app.models.roi import RoiBase
    CascadeBase.metadata.create_all(bind=engine)
    RoiBase.metadata.create_all(bind=engine)
    logger.info("Cascade and ROI tables verified/created")


def seed_cascade(engine):
    from app.models.cascade import CascadeAsset, CascadeWardPopulation, CascadeCriticalFacility
    from sqlalchemy.orm import Session

    with Session(bind=engine) as session:
        for w, p in WARD_POPULATIONS:
            existing = session.query(CascadeWardPopulation).filter_by(
                city_slug=CITY, ward_name=w).first()
            if not existing:
                session.add(CascadeWardPopulation(city_slug=CITY, ward_name=w, population=p))

        for s in POWER_SUBSTATIONS:
            existing = session.query(CascadeAsset).filter_by(asset_id=s["asset_id"]).first()
            if not existing:
                session.add(CascadeAsset(
                    asset_id=s["asset_id"], city_slug=CITY, asset_type="power_substation",
                    name=s["name"], lat=s["lat"], lon=s["lon"],
                    capacity_mw=s["capacity_mw"], restoration_hours=s["restoration_hours"],
                    serves_wards=s["serves_wards"],
                ))

        for p in WATER_PUMPS:
            existing = session.query(CascadeAsset).filter_by(asset_id=p["asset_id"]).first()
            if not existing:
                session.add(CascadeAsset(
                    asset_id=p["asset_id"], city_slug=CITY, asset_type="water_pump",
                    name=p["name"], lat=p["lat"], lon=p["lon"],
                    capacity_m3_day=p["capacity_m3_day"], restoration_hours=p["restoration_hours"],
                    powered_by=p["powered_by"], serves_wards=p["serves_wards"],
                ))

        for f in CRITICAL_FACILITIES:
            existing = session.query(CascadeCriticalFacility).filter_by(
                city_slug=CITY, name=f["name"]).first()
            if not existing:
                session.add(CascadeCriticalFacility(
                    city_slug=CITY, name=f["name"], facility_type=f["facility_type"],
                    ward=f["ward"], lat=f["lat"], lon=f["lon"],
                    beds=f.get("beds"), students=f.get("students"),
                    annual_passengers=f.get("annual_passengers"),
                ))

        session.commit()

    counts = {}
    with Session(bind=engine) as session:
        counts["wards"] = session.query(CascadeWardPopulation).filter_by(city_slug=CITY).count()
        counts["assets"] = session.query(CascadeAsset).filter_by(city_slug=CITY).count()
        counts["facilities"] = session.query(CascadeCriticalFacility).filter_by(city_slug=CITY).count()
    logger.info("Cascade seeded: %d wards, %d assets, %d facilities", counts["wards"], counts["assets"], counts["facilities"])


def seed_roi(engine):
    from app.models.roi import UpgradeOption
    from sqlalchemy.orm import Session

    with Session(bind=engine) as session:
        for infra_type, asset_id, name, cost, savings, desc, payback in ROI_UPGRADE_OPTIONS:
            existing = session.query(UpgradeOption).filter_by(
                infra_type=infra_type, asset_id=asset_id).first()
            if not existing:
                session.add(UpgradeOption(
                    infra_type=infra_type, asset_id=asset_id, name=name,
                    typical_cost_kes=cost, typical_annual_savings_kes=savings,
                    description=desc, payback_years=payback,
                ))
        session.commit()

    with Session(bind=engine) as session:
        count = session.query(UpgradeOption).count()
    logger.info("ROI seeded: %d upgrade options", count)


def seed_ward_coords(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS ward_coordinates ("
            "  id SERIAL PRIMARY KEY,"
            "  city_slug VARCHAR(64) NOT NULL,"
            "  ward_name VARCHAR(128) NOT NULL,"
            "  lat DOUBLE PRECISION NOT NULL,"
            "  lon DOUBLE PRECISION NOT NULL"
            ")"
        ))
        conn.commit()
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_ward_coords_ward ON ward_coordinates(city_slug, ward_name)"))
        for ward, lat, lon in WARD_COORDS:
            r = conn.execute(text("SELECT id FROM ward_coordinates WHERE city_slug=:city AND ward_name=:ward"),
                             {"city": CITY, "ward": ward}).first()
            if not r:
                conn.execute(text("INSERT INTO ward_coordinates (city_slug, ward_name, lat, lon) VALUES (:c, :w, :lat, :lon)"),
                             {"c": CITY, "w": ward, "lat": lat, "lon": lon})
        conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM ward_coordinates WHERE city_slug=:c"), {"c": CITY}).scalar()
    logger.info("Ward coordinates seeded: %d wards", count)


def main():
    import sys
    import os as _os

    _base = _os.path.dirname(_os.path.abspath(__file__))
    _core = _os.path.dirname(_base)
    if _core not in sys.path:
        sys.path.insert(0, _core)

    try:
        from dotenv import load_dotenv
        load_dotenv(_os.path.join(_core, '..', '..', '.env'))
    except ImportError:
        pass

    from app.database import get_engine

    logger.info("Seeding production reference data for cascade, ROI, and NL Map")
    try:
        engine = get_engine()
    except Exception as exc:
        logger.error("Cannot create engine. Is the database running? %s", exc)
        return 1

    ensure_tables(engine)
    seed_cascade(engine)
    seed_roi(engine)
    seed_ward_coords(engine)
    logger.info("All reference data seeded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
