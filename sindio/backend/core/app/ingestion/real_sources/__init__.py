"""Sindio — Real Data Sources Package.

Production-grade fetchers integrating with actual, published APIs and datasets.

Each fetcher targets a specific infrastructure type using real data:
  - opensky_fetcher: Real-time aviation (ADS-B) via OpenSky Network
  - nasa_power_fetcher: Climate/solar data via NASA POWER
  - here_traffic_fetcher: Real-time road traffic via HERE Technologies
  - chirps_fetcher: Rainfall via CHIRPS (UCSB)
  - kenya_railways_fetcher: KRC commuter rail + SGR schedules
  - viirs_fetcher: Night lights for power grid monitoring (NASA)
  - esa_worldcover_fetcher: Land use classification (ESA)
  - world_bank_fetcher: Kenya development indicators
  - nairobi_waste_fetcher: Solid waste management data
  - nairobi_sidewalks_fetcher: Pedestrian infrastructure
"""
from __future__ import annotations

from .opensky_fetcher import OpenSkyFetcher
from .nasa_power_fetcher import NASA_POWER_Fetcher
from .here_traffic_fetcher import HERE_TrafficFetcher
from .chirps_fetcher import CHIRPS_Fetcher
from .kenya_railways_fetcher import KenyaRailwaysFetcher
from .viirs_fetcher import VIIRS_Fetcher
from .esa_worldcover_fetcher import ESA_WorldCover_Fetcher
from .world_bank_fetcher import WorldBankFetcher
from .nairobi_waste_fetcher import NairobiWasteFetcher
from .nairobi_sidewalks_fetcher import NairobiSidewalksFetcher

__all__ = [
    "OpenSkyFetcher",
    "NASA_POWER_Fetcher",
    "HERE_TrafficFetcher",
    "CHIRPS_Fetcher",
    "KenyaRailwaysFetcher",
    "VIIRS_Fetcher",
    "ESA_WorldCover_Fetcher",
    "WorldBankFetcher",
    "NairobiWasteFetcher",
    "NairobiSidewalksFetcher",
]
