"""Sindio — Seed GIS Data Generator
====================================
Generates synthetic-but-realistic Nairobi ward boundaries and
infrastructure asset GeoJSON fixtures for development and testing.

Usage:
  cd scripts && python generate_seed_gis.py
  Output: data/fixtures/nairobi_wards.geojson
          data/fixtures/power_grid.geojson
          data/fixtures/water_network.geojson
          data/fixtures/road_network.geojson
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# ── Nairobi ward approximate centroids (based on real geography) ─
_NAIROBI_WARD_CENTROIDS: list[dict[str, Any]] = [
    {"name": "Kilimani", "lat": -1.286, "lon": 36.787, "area_km2": 4.2, "pop_2023": 52000},
    {"name": "Upper Hill", "lat": -1.296, "lon": 36.812, "area_km2": 3.8, "pop_2023": 38000},
    {"name": "CBD", "lat": -1.286, "lon": 36.823, "area_km2": 2.1, "pop_2023": 65000},
    {"name": "Westlands", "lat": -1.267, "lon": 36.804, "area_km2": 5.5, "pop_2023": 72000},
    {"name": "Industrial Area", "lat": -1.315, "lon": 36.847, "area_km2": 8.3, "pop_2023": 28000},
    {"name": "Eastleigh", "lat": -1.268, "lon": 36.850, "area_km2": 4.6, "pop_2023": 95000},
    {"name": "Karen", "lat": -1.378, "lon": 36.726, "area_km2": 12.4, "pop_2023": 42000},
    {"name": "Parklands", "lat": -1.258, "lon": 36.818, "area_km2": 3.9, "pop_2023": 45000},
    {"name": "Langata", "lat": -1.368, "lon": 36.746, "area_km2": 9.1, "pop_2023": 58000},
    {"name": "Ngong Road", "lat": -1.302, "lon": 36.774, "area_km2": 6.2, "pop_2023": 68000},
    {"name": "Kibera", "lat": -1.313, "lon": 36.780, "area_km2": 2.5, "pop_2023": 185000},
    {"name": "South B", "lat": -1.316, "lon": 36.838, "area_km2": 5.8, "pop_2023": 62000},
    {"name": "South C", "lat": -1.327, "lon": 36.832, "area_km2": 4.2, "pop_2023": 55000},
    {"name": "Donholm", "lat": -1.294, "lon": 36.887, "area_km2": 3.5, "pop_2023": 48000},
    {"name": "Embakasi", "lat": -1.315, "lon": 36.900, "area_km2": 10.2, "pop_2023": 125000},
    {"name": "Ruaraka", "lat": -1.210, "lon": 36.880, "area_km2": 7.4, "pop_2023": 78000},
    {"name": "Kasarani", "lat": -1.220, "lon": 36.910, "area_km2": 8.6, "pop_2023": 92000},
    {"name": "Dagoretti", "lat": -1.295, "lon": 36.756, "area_km2": 6.8, "pop_2023": 75000},
    {"name": "Mathare", "lat": -1.255, "lon": 36.860, "area_km2": 3.0, "pop_2023": 160000},
    {"name": "Huruma", "lat": -1.265, "lon": 36.875, "area_km2": 3.4, "pop_2023": 105000},
]


def _generate_ward_polygon(centroid: dict, area_km2: float, seed: int) -> list[list[float]]:
    """Generate a rough polygon around a ward centroid."""
    rng = np.random.RandomState(seed)
    n_points = rng.randint(6, 12)
    radius_km = (area_km2 / np.pi) ** 0.5
    angles = np.sort(rng.uniform(0, 2 * np.pi, n_points))
    r = radius_km * (0.5 + 0.5 * rng.random(n_points))
    lats = centroid["lat"] + (r / 111.32) * np.cos(angles)
    lons = centroid["lon"] + (r / (111.32 * np.cos(np.radians(centroid["lat"])))) * np.sin(angles)
    coords = [[round(lon, 6), round(lat, 6)] for lon, lat in zip(lons, lats)]
    coords.append(coords[0])  # Close polygon
    return [coords]


def generate_wards() -> dict:
    """Generate Nairobi ward GeoJSON FeatureCollection."""
    features: list[dict] = []
    for i, ward in enumerate(_NAIROBI_WARD_CENTROIDS):
        polygon = _generate_ward_polygon(ward, ward["area_km2"], seed=i)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": polygon},
            "properties": {
                "ward_name": ward["name"],
                "area_km2": ward["area_km2"],
                "population_2023": ward["pop_2023"],
                "density_km2": round(ward["pop_2023"] / ward["area_km2"], 1),
                "county": "Nairobi",
                "constituency": "Nairobi County",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    return {
        "type": "FeatureCollection",
        "name": "Nairobi Wards",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }


def _generate_power_grid() -> dict:
    """Generate synthetic Nairobi power grid (substations + feeders)."""
    rng = np.random.RandomState(100)
    features: list[dict] = []

    substations = [
        {"id": f"SUB-{i:03d}", "name": s["name"], "lat": s["lat"], "lon": s["lon"],
         "voltage_kv": s.get("voltage_kv", 66), "capacity_mva": s.get("capacity_mva", 66)}
        for i, s in enumerate(_NAIROBI_WARD_CENTROIDS)
    ]

    for sub in substations:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [sub["lon"], sub["lat"]]},
            "properties": {
                "asset_id": sub["id"],
                "asset_type": "substation",
                "name": sub["name"],
                "voltage_kv": sub["voltage_kv"],
                "capacity_mva": sub["capacity_mva"],
                "infrastructure_type": "power",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    # Generate feeder lines between nearby substations
    for i, a in enumerate(substations):
        for j, b in enumerate(substations):
            if i >= j:
                continue
            dx = (a["lat"] - b["lat"]) * 111.32
            dy = (a["lon"] - b["lon"]) * 111.32 * 0.866
            dist_km = (dx ** 2 + dy ** 2) ** 0.5
            if dist_km < 8.0:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [a["lon"], a["lat"]],
                            [b["lon"], b["lat"]],
                        ],
                    },
                    "properties": {
                        "asset_id": f"FEEDER-{a['id']}-{b['id']}",
                        "asset_type": "feeder",
                        "from": a["name"],
                        "to": b["name"],
                        "voltage_kv": min(a["voltage_kv"], b["voltage_kv"]),
                        "length_km": round(dist_km, 2),
                        "infrastructure_type": "power",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

    return {"type": "FeatureCollection", "name": "Nairobi Power Grid", "features": features}


def _generate_water_network() -> dict:
    """Generate synthetic Nairobi water network (reservoirs + pipelines)."""
    features: list[dict] = []

    reservoirs = [
        {"id": "RES-001", "name": "Kabete Reservoir", "lat": -1.25, "lon": 36.73, "capacity_m3": 500000},
        {"id": "RES-002", "name": "Gigiri Reservoir", "lat": -1.23, "lon": 36.81, "capacity_m3": 750000},
        {"id": "RES-003", "name": "Karen Reservoir", "lat": -1.38, "lon": 36.73, "capacity_m3": 300000},
    ]

    for r in reservoirs:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "asset_id": r["id"],
                "asset_type": "reservoir",
                "name": r["name"],
                "capacity_m3": r["capacity_m3"],
                "infrastructure_type": "water",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    # Pipelines from reservoirs to nearby wards
    for r in reservoirs:
        for ward in _NAIROBI_WARD_CENTROIDS[:8]:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [r["lon"], r["lat"]],
                        [ward["lon"], ward["lat"]],
                    ],
                },
                "properties": {
                    "asset_id": f"PIPE-{r['id']}-{ward['name'][:3].upper()}",
                    "asset_type": "pipeline",
                    "from": r["name"],
                    "to": ward["name"],
                    "infrastructure_type": "water",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            })

    return {"type": "FeatureCollection", "name": "Nairobi Water Network", "features": features}


def _generate_road_network() -> dict:
    """Generate synthetic Nairobi road network (major arterials + local roads)."""
    rng = np.random.RandomState(200)
    features: list[dict] = []

    major_roads = [
        {"name": "Mombasa Road (A104)", "coords": [[36.80, -1.30], [36.95, -1.32]]},
        {"name": "Thika Road (A2)", "coords": [[36.82, -1.27], [36.93, -1.20]]},
        {"name": "Ngong Road", "coords": [[36.77, -1.30], [36.75, -1.38]]},
        {"name": "Waiyaki Way", "coords": [[36.78, -1.27], [36.70, -1.25]]},
        {"name": "Jogoo Road", "coords": [[36.85, -1.30], [36.90, -1.28]]},
        {"name": "Langata Road", "coords": [[36.80, -1.30], [36.73, -1.38]]},
        {"name": "Kiambu Road", "coords": [[36.82, -1.27], [36.83, -1.20]]},
        {"name": "Outer Ring Road", "coords": [[36.87, -1.30], [36.90, -1.25], [36.87, -1.20], [36.82, -1.27]]},
    ]

    for road in major_roads:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": road["coords"]},
            "properties": {
                "asset_id": f"ROAD-{road['name'][:3].upper()}",
                "asset_type": "primary",
                "name": road["name"],
                "lanes": rng.randint(2, 6),
                "infrastructure_type": "roads",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    return {"type": "FeatureCollection", "name": "Nairobi Road Network", "features": features}


def main() -> None:
    print("Generating Sindio seed GIS fixtures...")

    ward_geojson = generate_wards()
    power_geojson = _generate_power_grid()
    water_geojson = _generate_water_network()
    road_geojson = _generate_road_network()

    for name, data in [
        ("nairobi_wards.geojson", ward_geojson),
        ("power_grid.geojson", power_geojson),
        ("water_network.geojson", water_geojson),
        ("road_network.geojson", road_geojson),
    ]:
        path = FIXTURES_DIR / name
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  [OK] {path} ({len(data['features'])} features)")

    print(f"\nAll fixtures written to {FIXTURES_DIR}")
    print("Run ingestion to load into PostGIS:")
    print("  python -m app.services.ingest_geospatial --assets wards,power,water,roads --force")


if __name__ == "__main__":
    main()
