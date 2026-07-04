# Sindio — Real Data Sources Registry
======================================

This document catalogs all real data sources integrated into Sindio's ingestion pipeline.

## Source Summary by Infrastructure Type

| Infrastructure Type | Primary Source | Secondary Source | Tertiary Source | Update Frequency |
|---|---|---|---|---|
| **Power** | KPLC Substation Registry + NASA POWER | VIIRS Night Lights | Kenya Power Static Model | Hourly / Daily |
| **Water** | Nairobi Water SCADA + CHIRPS Rainfall | World Bank Water Access | NCWSC Asset Registry | Hourly / Daily |
| **Roads** | HERE Traffic API | OpenStreetMap | KeNHA Road Conditions | 5 min / Weekly |
| **Solid Waste** | Nairobi County Waste Model | World Bank Indicators | JICA Master Plan | Daily |
| **Sidewalks** | Nairobi Sidewalk Model | OpenStreetMap Footways | NIUPLAN Maps | Weekly |
| **LRT** | Kenya Railways Commuter Schedules | KRC Website Scraping | Static Network Model | Hourly |
| **SGR** | Kenya Railways SGR Schedules | KRC Freight Reports | Static Network Model | Hourly |
| **Airports** | OpenSky Network (ADS-B) | Kenya Airports Authority | OurAirports Database | 5 min |

---

## 1. Power

### 1.1 Kenya Power & Lighting Company (KPLC)
**Type:** Static asset registry + modeled loading  
**URL:** https://kplc.co.ke (public outage schedules)  
**Authentication:** None (public scraping), optional `KPLC_API_KEY` for premium  
**Data:** 14 Nairobi substations with MVA ratings, 9 national generators, network topology  
**Latency:** Static (assets), Modeled (loading)  
**Fallback:** Heuristic load curves based on time-of-day

### 1.2 NASA POWER (Prediction of Worldwide Energy Resources)
**Type:** Satellite-derived climate data  
**URL:** https://power.larc.nasa.gov/api/  
**Authentication:** None (free)  
**Parameters:** Temperature, solar irradiance, wind speed, humidity, precipitation  
**Use case:** Power demand forecasting, solar generation potential, thermal stress  
**Latency:** ~2-3 days (reanalysis)  
**Fallback:** Nairobi seasonal climate model

### 1.3 NASA VIIRS DNB (Nighttime Lights)
**Type:** Satellite imagery proxy  
**URL:** https://eogdata.mines.edu/products/vnl/  
**Authentication:** None (free)  
**Use case:** Power grid health proxy (areas going dark = outages), electrification tracking  
**Latency:** Monthly, ~30 days delayed  
**Fallback:** Kenya Power electrification statistics (90-98% for Nairobi)

---

## 2. Water

### 2.1 Nairobi City Water & Sewerage Company (NCWSC)
**Type:** Public asset registry + supply notices  
**URL:** https://www.nairobiwater.co.ke  
**Authentication:** None (public scraping)  
**Data:** 7 reservoirs, 2 treatment plants, 8 pipeline nodes, ward demand models  
**Latency:** Static (assets), Daily (supply status)  
**Fallback:** Ward demand model based on population × 120 L/person/day

### 2.2 CHIRPS (Climate Hazards Center InfraRed Precipitation)
**Type:** Satellite rainfall estimates  
**URL:** http://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/  
**Authentication:** None (free)  
**Data:** Daily precipitation (mm), 5-day and 30-day rolling totals, flood risk index  
**Use case:** Reservoir inflow forecasting, flood risk assessment  
**Latency:** ~6 weeks (final), near-real-time preliminary available  
**Fallback:** Nairobi bimodal rainfall model (long rains Mar-May, short rains Oct-Nov)

### 2.3 World Bank — Water Access Indicators
**Type:** Development statistics  
**URL:** https://api.worldbank.org/v2/country/KEN/indicator/SH.H2O.SMDW.ZS  
**Authentication:** None (free)  
**Data:** National access to clean water (%), freshwater withdrawals  
**Latency:** Annual, ~1 year delayed  
**Fallback:** KNBS census data

---

## 3. Roads

### 3.1 HERE Traffic API
**Type:** Real-time traffic flow  
**URL:** https://traffic.ls.hereapi.com/traffic/6.2/  
**Authentication:** `HERE_API_KEY` (free tier: 250K req/month)  
**Data:** Speed, free-flow speed, jam factor, incidents, road closures  
**Coverage:** 12 major Nairobi road segments (Mombasa Rd, Thika Rd, Waiyaki Way, etc.)  
**Latency:** Real-time (~1-2 min)  
**Fallback:** Nairobi time-of-day congestion model

### 3.2 OpenStreetMap Overpass API
**Type:** Crowd-sourced infrastructure geometry  
**URL:** https://overpass-api.de/api/interpreter  
**Authentication:** None (free, fair-use: ~3 req/sec)  
**Data:** Roads, sidewalks, power lines, water pipes, rail, buildings, waste facilities  
**Latency:** Real-time (community updates)  
**Cache:** 24-hour local cache  
**Fallback:** Static asset registry

### 3.3 ESA WorldCover
**Type:** Satellite land use classification  
**URL:** https://esa-worldcover.org/  
**Authentication:** None (free)  
**Data:** 10m resolution land cover (built-up, tree cover, grassland, water, etc.)  
**Use case:** Impervious surface ratio (flood risk), green space (heat island), urban density  
**Latency:** Annual (2020 baseline, updates yearly)  
**Fallback:** Nairobi ward profiles from NIUPLAN

---

## 4. Solid Waste

### 4.1 Nairobi County Waste Model
**Type:** Derived from population + collection coverage data  
**Sources:**
  - Nairobi County Environment Department reports
  - JICA Nairobi Integrated Solid Waste Management Master Plan
  - UN-Habitat solid waste reports
  - World Bank urban development indicators  
**Data:** 16 ward-level waste generation (tons/day), collection rates, Dandora landfill stress  
**Latency:** Daily (modeled)  
**Fallback:** Per-capita model (0.6 kg/person/day)

---

## 5. Sidewalks / Pedestrian Infrastructure

### 5.1 Nairobi Sidewalk Model
**Type:** Composite index from multiple sources  
**Sources:**
  - OpenStreetMap footway coverage
  - Nairobi County pedestrian maps (NIUPLAN)
  - KNBS census walking-to-work statistics
  - Field survey models (Walk Score-like index)  
**Data:** 20 ward-level sidewalk coverage (%), quality score (0-10), pedestrian volume  
**Latency:** Weekly  
**Fallback:** Ward-level profiles from KNBS + OSM

---

## 6. Light Rail Transit (LRT) / Commuter Rail

### 6.1 Kenya Railways Corporation (KRC)
**Type:** Public schedules + operational status  
**URL:** https://krc.co.ke/services/commuter-rail/  
**Authentication:** None (public scraping)  
**Data:** 5 NCR lines (Syokimau, Ruiru, Kikuyu, Embakasi, Limuru), 16 stations, ridership models  
**Latency:** Hourly (status), Static (network)  
**Fallback:** Published KRC schedules + ridership model (50K daily)

---

## 7. Standard Gauge Railway (SGR)

### 7.1 Kenya Railways — Madaraka Express
**Type:** Public schedules + freight reports  
**URL:** https://krc.co.ke/services/madaraka-express/  
**Authentication:** None (public scraping)  
**Data:** 4 SGR stations (Nairobi, Mtito Andei, Voi, Mombasa), daily train frequencies  
**Latency:** Hourly  
**Fallback:** Published KRC timetable

---

## 8. Airports

### 8.1 OpenSky Network
**Type:** Real-time ADS-B flight tracking  
**URL:** https://opensky-network.org/api/states/all  
**Authentication:** Optional (anonymous: 10 req/min; registered: higher limits)  
**Data:** Aircraft positions, callsigns, altitudes, velocities, flight phases  
**Coverage:** All ADS-B equipped aircraft in Nairobi FIR (Kenya, parts of Uganda/Tanzania/Ethiopia/Somalia)  
**Latency:** Real-time (~5-10 seconds)  
**Fallback:** Static airport registry (6 Kenya airports)

### 8.2 Kenya Airports Authority (KAA)
**Type:** Published statistics  
**URL:** https://kaa.go.ke/statistics/  
**Authentication:** None (public)  
**Data:** Passenger numbers, cargo volumes, aircraft movements (annual/quarterly)  
**Latency:** Quarterly/Annual  
**Fallback:** Static airport capacity data

---

## 9. Cross-Cutting / Additional Sources

### 9.1 World Bank API
**Type:** Development indicators  
**URL:** https://api.worldbank.org/v2/country/KEN/  
**Authentication:** None (free)  
**Indicators:**
  - EG.ELC.ACCS.ZS — Access to electricity
  - EG.ELC.RNEW.ZS — Renewable energy share
  - SH.H2O.SMDW.ZS — Access to clean water
  - IS.ROD.DNST.K2 — Road density
  - SP.URB.TOTL.IN.ZS — Urban population
  - NY.GDP.PCAP.CD — GDP per capita  
**Latency:** Annual

### 9.2 Kenya Open Data Initiative (KODI)
**Type:** Government open data portal  
**URL:** http://www.opendata.go.ke/  
**Data:** Various geospatial and statistical datasets for Kenya  
**Latency:** Varies by dataset

### 9.3 WorldPop
**Type:** High-resolution population data  
**URL:** https://www.worldpop.org/  
**Data:** 100m resolution population density (GeoTIFF)  
**Latency:** 2020 baseline, updated periodically  
**Fallback:** Hardcoded Nairobi high-density coordinates

### 9.4 Kenya National Bureau of Statistics (KNBS)
**Type:** Census and survey data  
**URL:** https://www.knbs.or.ke/  
**Data:** Population, housing, economic indicators by ward/county  
**Latency:** Census (every 10 years), surveys (annual)

---

## Authentication Requirements Summary

| Source | Env Var | Required? | Cost |
|---|---|---|---|
| OpenSky Network | `OPENSKY_USERNAME` / `OPENSKY_PASSWORD` | No (optional) | Free |
| HERE Traffic | `HERE_API_KEY` | No (optional) | Free tier: 250K req/mo |
| NASA POWER | — | No | Free |
| CHIRPS | — | No | Free |
| VIIRS DNB | — | No | Free |
| ESA WorldCover | — | No | Free |
| World Bank | — | No | Free |
| KPLC / KRC / NCWSC | — | No | Free (scraping) |
| Google Maps | `GOOGLE_MAPS_API_KEY` | No (optional) | Paid |

---

## Data Quality Tiers

| Tier | Description | Examples |
|---|---|---|
| **Tier 1** | Real-time, sensor/ADS-B data | OpenSky, HERE Traffic, NASA POWER |
| **Tier 2** | Daily/weekly operational data | CHIRPS, KRC schedules, VIIRS |
| **Tier 3** | Static registry + modeled dynamics | KPLC assets, OSM geometry, ESA WorldCover |
| **Tier 4** | Annual statistics + macro indicators | World Bank, KNBS, KAA |
| **Tier 5** | Fully modeled (no external source) | Waste collection, sidewalk quality |

---

## Fallback Cascade

Every fetcher implements a 3-tier fallback:

1. **Primary**: Live API query (OpenSky, HERE, NASA POWER, CHIRPS)
2. **Secondary**: Cached/previous data + trend extrapolation
3. **Tertiary**: Static model informed by known Nairobi patterns

When a fetcher falls back, the record is tagged `is_mock=True` with the `reason` field explaining which tier failed.

---

## Adding a New Real Data Source

To add a new fetcher:

1. Create `backend/core/app/ingestion/real_sources/your_fetcher.py`
2. Inherit from `BaseFetcher` (from `..base`)
3. Implement `fetch()` returning raw records
4. Optionally override `normalize()` for custom schema mapping
5. Add to `real_sources/__init__.py`
6. Add to `runner.py` FETCHERS list
7. Document in this file
8. Add any required env vars to `.env.example`

Example:
```python
class MySourceFetcher(BaseFetcher):
    source_name = "My Source"
    infrastructure_type = "power"
    
    def fetch(self) -> list[dict]:
        # Call real API
        data = self._http_get("https://api.example.com/data")
        return [self.normalize(r) for r in data.json()]
```
