"""
Sindio — External Data Ingestion Package
==========================================
Fetchers for real-world Nairobi infrastructure data sources:
  - Kenya Open Data Initiative (KODI)
  - Nairobi Metropolitan Services (NMS)
  - Kenya Power & Lighting Company
  - WorldPop population density raster

Usage:
  from app.ingestion import run_all, list_fetchers
  results = run_all()
"""
from .runner import run_all, run_single, list_fetchers
from .models import create_tables

__all__ = ["run_all", "run_single", "list_fetchers", "create_tables"]
