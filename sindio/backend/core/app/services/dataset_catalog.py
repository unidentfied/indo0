from __future__ import annotations

from datetime import datetime, timezone

_CATALOG: list[dict] = [
    {
        "id": "power-grid-geojson",
        "name": "Nairobi Power Grid",
        "description": "GeoJSON topology of Nairobi's electrical grid including substations, "
        "transmission lines, distribution feeders, and transformer nodes. "
        "Covers Kenya Power infrastructure across all 85 wards.",
        "format": "geojson",
        "category": "infrastructure",
        "update_frequency": "daily",
        "record_count": 14204,
        "size_estimate": "48 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/power-grid-geojson/download",
        "api_endpoint": "/api/v1/datasets/power-grid-geojson",
        "fields": [
            {"name": "node_id", "type": "string", "description": "Unique substation or pole identifier"},
            {"name": "voltage_kv", "type": "float", "description": "Nominal line voltage (11, 33, 66, 132, or 220 kV)"},
            {"name": "capacity_mw", "type": "float", "description": "Rated capacity in megawatts"},
            {"name": "status", "type": "string", "description": "Operational / maintenance / fault"},
            {"name": "geometry", "type": "geometry", "description": "Point or LineString in EPSG:4326"},
        ],
        "last_updated": "2026-08-05T04:00:00Z",
    },
    {
        "id": "water-network-geojson",
        "name": "Nairobi Water Network",
        "description": "GeoJSON representation of Nairobi City Water & Sewerage Company network: "
        "transmission mains, distribution pipes, reservoirs, and treatment plants.",
        "format": "geojson",
        "category": "infrastructure",
        "update_frequency": "daily",
        "record_count": 8432,
        "size_estimate": "32 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/water-network-geojson/download",
        "api_endpoint": "/api/v1/datasets/water-network-geojson",
        "fields": [
            {"name": "pipe_id", "type": "string", "description": "Unique pipe segment identifier"},
            {"name": "diameter_mm", "type": "integer", "description": "Internal pipe diameter in millimetres"},
            {"name": "material", "type": "string", "description": "HDPE / ductile iron / steel / uPVC"},
            {"name": "pressure_zone", "type": "string", "description": "Hydraulic pressure zone label"},
            {"name": "status", "type": "string", "description": "Active / leaking / under repair"},
            {"name": "geometry", "type": "geometry", "description": "LineString in EPSG:4326"},
        ],
        "last_updated": "2026-08-05T04:00:00Z",
    },
    {
        "id": "road-network-geojson",
        "name": "Nairobi Road Network",
        "description": "GeoJSON road segment inventory derived from OpenStreetMap and "
        "KeNHA surveys. Includes classification, lane count, surface type, and "
        "traffic stress index per segment.",
        "format": "geojson",
        "category": "infrastructure",
        "update_frequency": "daily",
        "record_count": 3210,
        "size_estimate": "14 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/road-network-geojson/download",
        "api_endpoint": "/api/v1/datasets/road-network-geojson",
        "fields": [
            {"name": "segment_id", "type": "string", "description": "Unique road segment identifier"},
            {"name": "classification", "type": "string", "description": "Highway / arterial / collector / local"},
            {"name": "lanes", "type": "integer", "description": "Number of lanes"},
            {"name": "surface", "type": "string", "description": "Paved / gravel / earth"},
            {"name": "traffic_stress", "type": "float", "description": "Modelled stress index 0–1"},
            {"name": "geometry", "type": "geometry", "description": "LineString in EPSG:4326"},
        ],
        "last_updated": "2026-08-05T04:00:00Z",
    },
    {
        "id": "stress-points-geojson",
        "name": "Infrastructure Stress Points",
        "description": "Real-time stress and failure-risk points across power, water, "
        "and road networks. Each point includes a stress score, failure mode "
        "prediction, and estimated time-to-breach.",
        "format": "geojson",
        "category": "infrastructure",
        "update_frequency": "real-time",
        "record_count": 0,
        "size_estimate": "variable",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/stress-points-geojson/download",
        "api_endpoint": "/api/v1/datasets/stress-points-geojson",
        "fields": [
            {"name": "asset_id", "type": "string", "description": "Related infrastructure asset identifier"},
            {"name": "infra_type", "type": "string", "description": "Power / water / roads"},
            {"name": "stress_score", "type": "float", "description": "Current stress level 0–1"},
            {"name": "failure_mode", "type": "string", "description": "Predicted failure category"},
            {"name": "time_to_breach_hrs", "type": "float", "description": "Estimated hours until failure"},
            {"name": "geometry", "type": "geometry", "description": "Point in EPSG:4326"},
        ],
        "last_updated": "2026-08-05T10:30:00Z",
    },
    {
        "id": "synthetic-population-csv",
        "name": "Synthetic Population",
        "description": "Statistically representative synthetic household dataset "
        "for Nairobi generated from KNBS census microdata. Each row is a "
        "household with demographic and location attributes.",
        "format": "csv",
        "category": "population",
        "update_frequency": "quarterly",
        "record_count": 500000,
        "size_estimate": "210 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/synthetic-population-csv/download",
        "api_endpoint": "/api/v1/datasets/synthetic-population-csv",
        "fields": [
            {"name": "household_id", "type": "string", "description": "Unique household identifier"},
            {"name": "ward", "type": "string", "description": "Nairobi ward name"},
            {"name": "household_size", "type": "integer", "description": "Number of members"},
            {"name": "income_band", "type": "string", "description": "Low / lower-middle / upper-middle / high"},
            {"name": "has_vehicle", "type": "boolean", "description": "Whether the household has a vehicle"},
            {"name": "lat", "type": "float", "description": "Approximate centroid latitude"},
            {"name": "lng", "type": "float", "description": "Approximate centroid longitude"},
        ],
        "last_updated": "2026-07-01T00:00:00Z",
    },
    {
        "id": "movement-patterns-csv",
        "name": "Movement Patterns",
        "description": "Hourly origin–destination matrix for Nairobi derived from "
        "anonymised mobile network signalling data. Columns represent origin ward, "
        "destination ward, trip count, and hour of day.",
        "format": "csv",
        "category": "population",
        "update_frequency": "hourly",
        "record_count": 0,
        "size_estimate": "~120 MB / day",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/movement-patterns-csv/download",
        "api_endpoint": "/api/v1/datasets/movement-patterns-csv",
        "fields": [
            {"name": "origin_ward", "type": "string", "description": "Source ward name"},
            {"name": "destination_ward", "type": "string", "description": "Target ward name"},
            {"name": "hour", "type": "integer", "description": "Hour of day 0–23"},
            {"name": "trip_count", "type": "integer", "description": "Number of observed trips"},
            {"name": "date", "type": "string", "description": "ISO date"},
        ],
        "last_updated": "2026-08-05T10:00:00Z",
    },
    {
        "id": "carbon-credits-json",
        "name": "Carbon Credits Registry",
        "description": "Registry of verified carbon credits generated by Nairobi "
        "infrastructure projects (tree planting, solar microgrids, waste-to-energy). "
        "Includes issuance, retirement, and pricing records.",
        "format": "json",
        "category": "environment",
        "update_frequency": "monthly",
        "record_count": 480,
        "size_estimate": "1.2 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/carbon-credits-json/download",
        "api_endpoint": "/api/v1/datasets/carbon-credits-json",
        "fields": [
            {"name": "credit_id", "type": "string", "description": "Unique credit serial number"},
            {"name": "project_name", "type": "string", "description": "Originating project"},
            {"name": "tonnes_co2e", "type": "float", "description": "Tonnes of CO₂ equivalent"},
            {"name": "issuance_date", "type": "string", "description": "ISO date of issuance"},
            {"name": "status", "type": "string", "description": "Issued / retired / pending"},
            {"name": "price_kes", "type": "float", "description": "Most recent market price per tonne (KES)"},
        ],
        "last_updated": "2026-08-01T00:00:00Z",
    },
    {
        "id": "insurance-policies-json",
        "name": "Insurance Policies",
        "description": "Anonymised index of parametric infrastructure insurance "
        "policies issued against Nairobi assets. Includes coverage thresholds, "
        "premium rates, and claim status.",
        "format": "json",
        "category": "finance",
        "update_frequency": "daily",
        "record_count": 1270,
        "size_estimate": "3.5 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/insurance-policies-json/download",
        "api_endpoint": "/api/v1/datasets/insurance-policies-json",
        "fields": [
            {"name": "policy_id", "type": "string", "description": "Unique policy identifier"},
            {"name": "asset_id", "type": "string", "description": "Insured infrastructure asset"},
            {"name": "coverage_kes", "type": "float", "description": "Coverage amount in Kenyan shillings"},
            {"name": "trigger", "type": "string", "description": "Parametric trigger condition"},
            {"name": "premium_pct", "type": "float", "description": "Annual premium as % of coverage"},
            {"name": "status", "type": "string", "description": "Active / lapsed / claimed"},
        ],
        "last_updated": "2026-08-05T06:00:00Z",
    },
    {
        "id": "ward-boundaries-geojson",
        "name": "Nairobi Ward Boundaries",
        "description": "Administrative boundary polygons for all 85 Nairobi City "
        "County wards, with population estimates and area metadata.",
        "format": "geojson",
        "category": "infrastructure",
        "update_frequency": "static",
        "record_count": 85,
        "size_estimate": "2.8 MB",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/ward-boundaries-geojson/download",
        "api_endpoint": "/api/v1/datasets/ward-boundaries-geojson",
        "fields": [
            {"name": "ward_name", "type": "string", "description": "Official ward name"},
            {"name": "constituency", "type": "string", "description": "Parent constituency"},
            {"name": "population_2019", "type": "integer", "description": "KNBS 2019 census count"},
            {"name": "area_km2", "type": "float", "description": "Area in square kilometres"},
            {"name": "geometry", "type": "geometry", "description": "MultiPolygon in EPSG:4326"},
        ],
        "last_updated": "2025-01-15T00:00:00Z",
    },
    {
        "id": "alert-history-json",
        "name": "Alert History",
        "description": "Historical record of all infrastructure alerts generated by "
        "the Sindio monitoring system. Includes stress thresholds breached, "
        "recommendations issued, and resolution status.",
        "format": "json",
        "category": "infrastructure",
        "update_frequency": "5 min",
        "record_count": 0,
        "size_estimate": "variable",
        "license": "CC-BY-4.0",
        "download_url": "/api/v1/datasets/alert-history-json/download",
        "api_endpoint": "/api/v1/datasets/alert-history-json",
        "fields": [
            {"name": "alert_id", "type": "string", "description": "Unique alert identifier"},
            {"name": "asset_id", "type": "string", "description": "Affected infrastructure asset"},
            {"name": "severity", "type": "string", "description": "Critical / warning / info"},
            {"name": "stress_score", "type": "float", "description": "Trigger stress value"},
            {"name": "recommendation", "type": "string", "description": "Suggested response action"},
            {"name": "resolved", "type": "boolean", "description": "Whether the alert has been resolved"},
            {"name": "created_at", "type": "string", "description": "ISO timestamp"},
        ],
        "last_updated": "2026-08-05T10:35:00Z",
    },
]


def list_datasets(category: str | None = None) -> list[dict]:
    if category:
        return [d for d in _CATALOG if d["category"] == category]
    return list(_CATALOG)


def get_dataset(dataset_id: str) -> dict | None:
    for d in _CATALOG:
        if d["id"] == dataset_id:
            return d
    return None
