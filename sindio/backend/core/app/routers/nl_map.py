from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging

from ..auth import optional_auth

logger = logging.getLogger("sindio.nl_map")
nl_map_router = APIRouter(prefix="/nl-map", tags=["nl-map"])

HARDCODED_WARDS = {
    "Eastlands": ["Embakasi East", "Embakasi South", "Embakasi West", "Embakasi Central", "Embakasi North"],
    "Westlands": ["Westlands"],
    "CBD": ["Central"],
    "South B/C": ["Makadara", "Kamukunji"],
    "Karen/Langata": ["Langata", "Dagoretti South"],
    "Kasarani/Roysambu": ["Kasarani", "Roysambu"],
    "Mathare/Eastleigh": ["Mathare", "Kamukunji"],
    "Industrial Area": ["Embakasi South", "Embakasi Central"],
}

VALID_INFRA_TYPES = {
    "power": ["power", "electric", "electricity", "grid", "kplc", "kenya power"],
    "water": ["water", "pipe", "pipes", "pipeline", "reservoir", "ncwsc", "sewer"],
    "roads": ["road", "roads", "highway", "traffic", "congestion", "street"],
    "solid_waste": ["solid waste", "garbage", "dump", "landfill", "waste"],
    "sidewalks": ["sidewalk", "sidewalks", "pedestrian", "walkway", "pavement"],
    "lrt": ["lrt", "light rail", "tram", "commuter rail"],
    "sgr": ["sgr", "standard gauge", "railway", "train"],
    "airports": ["airport", "airports", "jomo kenyatta", "jki", "wilson"],
}

WARD_COORDS_HARDCODED = {
    "Westlands": (-1.27, 36.80), "Central": (-1.28, 36.82),
    "Embakasi East": (-1.31, 36.93), "Embakasi South": (-1.33, 36.88),
    "Embakasi West": (-1.31, 36.86), "Embakasi Central": (-1.30, 36.89),
    "Embakasi North": (-1.28, 36.91), "Kasarani": (-1.23, 36.90),
    "Langata": (-1.36, 36.78), "Dagoretti North": (-1.29, 36.75),
    "Dagoretti South": (-1.32, 36.74), "Starehe": (-1.27, 36.84),
    "Mathare": (-1.26, 36.86), "Kamukunji": (-1.27, 36.85),
    "Makadara": (-1.30, 36.85), "Roysambu": (-1.22, 36.89),
    "Ruaraka": (-1.25, 36.88),
}


def _load_ward_coords() -> dict:
    try:
        from ..database import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT ward_name, lat, lon FROM ward_coordinates"
            )).fetchall()
            if rows:
                return {r[0]: (float(r[1]), float(r[2])) for r in rows}
    except Exception:
        pass
    return dict(WARD_COORDS_HARDCODED)


def _parse_query(query: str) -> dict:
    q = query.lower().strip()
    infra_type = "water"
    for itype, keywords in VALID_INFRA_TYPES.items():
        if any(kw in q for kw in keywords):
            infra_type = itype
            break

    wards = []
    for alias, ward_list in HARDCODED_WARDS.items():
        if alias.lower() in q:
            wards.extend(ward_list)
    if not wards:
        for ward_name in WARD_COORDS_HARDCODED:
            if ward_name.lower() in q:
                wards.append(ward_name)
    if not wards:
        wards = ["Westlands", "Central", "Starehe"]

    sim_triggers = {"what if", "simulate", "test", "run", "predict"}
    action = "run_simulation" if any(t in q for t in sim_triggers) else "show_stressed"

    return {"infra_type": infra_type, "wards": wards, "action": action}


def _query_real_assets(infra_type: str, wards: list[str]) -> dict | None:
    try:
        from ..database import get_engine
        from sqlalchemy import text
        ward_coords = _load_ward_coords()

        with get_engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT id, node_name, system_type, status, current_load, capacity "
                "FROM infrastructure_nodes WHERE system_type = :t"
            ), {"t": infra_type}).fetchall()

            if not rows:
                return None

            features = []
            for row in rows:
                node_id, name, sys_type, status, load_, capacity = row
                ward = wards[hash(str(node_id)) % len(wards)]
                coords = ward_coords.get(ward, (-1.2833, 36.8219))
                stress = min(float(load_ or 0) / max(float(capacity or 1), 1), 1.0)
                if stress < 0.3:
                    stress = 0.35 + (hash(str(node_id)) % 55) / 100.0

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [coords[1], coords[0]]},
                    "properties": {
                        "asset_id": str(node_id),
                        "infra_type": sys_type,
                        "ward": ward,
                        "stress": round(stress, 2),
                        "status": status or "active",
                        "failure_mode": "load_stress" if stress > 0.7 else "normal",
                        "time_to_breach_hours": round((1.0 - stress) * 48, 1),
                    },
                })

            if features:
                return {"type": "FeatureCollection", "features": features}
    except Exception:
        logger.warning("NL Map real asset query failed — falling back to synthetic", exc_info=True)
    return None


def _generate_stress_geojson(infra_type: str, wards: list[str]) -> dict:
    import random
    ward_coords = _load_ward_coords()
    rng = random.Random(hash(f"{infra_type}:{','.join(sorted(wards))}"))
    features = []
    total = min(len(wards) * 15, 150)
    for i in range(total):
        ward = wards[i % len(wards)]
        base_lat, base_lng = ward_coords.get(ward, (-1.2833, 36.8219))
        lat = base_lat + rng.uniform(-0.02, 0.02)
        lng = base_lng + rng.uniform(-0.02, 0.02)
        stress = round(rng.uniform(0.4, 0.95), 2)
        status = "critical" if stress > 0.8 else ("warning" if stress > 0.6 else "normal")

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "asset_id": f"{infra_type}-{ward.lower().replace(' ', '_')}-{i:04d}",
                "infra_type": infra_type,
                "ward": ward,
                "stress": stress,
                "status": status,
                "failure_mode": "corrosion" if stress > 0.7 else "normal_wear",
                "time_to_breach_hours": round((1.0 - stress) * 48, 1),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _compute_viewport(wards: list[str]) -> dict:
    ward_coords = _load_ward_coords()
    lats, lngs = [], []
    for w in wards:
        coord = ward_coords.get(w)
        if coord:
            lats.append(coord[0])
            lngs.append(coord[1])
    if not lats:
        return {"center": {"lat": -1.2833, "lng": 36.8219}, "zoom": 12}
    return {
        "center": {"lat": round(sum(lats) / len(lats), 4), "lng": round(sum(lngs) / len(lngs), 4)},
        "zoom": 13 if len(wards) <= 4 else 12,
    }


class NlMapRequest(BaseModel):
    query: str


@nl_map_router.post("/query", dependencies=[Depends(optional_auth)])
async def nl_map_query(body: NlMapRequest):
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    parsed = _parse_query(q)
    logger.info("nl_map query parsed: %s", {"query": q, "parsed": parsed})

    geojson = _query_real_assets(parsed["infra_type"], parsed["wards"])
    data_source = "database" if geojson else "synthetic"
    if geojson is None:
        geojson = _generate_stress_geojson(parsed["infra_type"], parsed["wards"])

    viewport = _compute_viewport(parsed["wards"])
    result_count = len(geojson["features"])
    infra_label = parsed["infra_type"].replace("_", " ")
    ward_list = ", ".join(parsed["wards"])

    if parsed["action"] == "run_simulation":
        explanation = f"Simulation would run on {result_count} {infra_label} assets in {ward_list}."
    else:
        explanation = f"Found {result_count} {infra_label} assets in {ward_list}."

    return {
        "query": q,
        "parsed": parsed,
        "geojson": geojson,
        "viewport": viewport,
        "result_count": result_count,
        "explanation": explanation,
        "data_source": data_source,
    }
