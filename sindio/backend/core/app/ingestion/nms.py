"""
Sindio — Nairobi Metropolitan Services (NMS) Fetcher
======================================================
NMS manages water, waste, roads, and drainage in Nairobi.
They do not publish a public REST API, but they do publish:
- Weekly water supply schedules (PDF/HTML on nms.co.ke)
- Road maintenance notices
- Drainage / flood reports

This fetcher uses a hybrid approach:
1. HTTP scraping of public schedule pages
2. Static CSV/Excel datasets if available via Nairobi Open Data
3. Graceful fallback to empty list (no crash)

For live data, NMS would need a direct SCADA or IoT integration —
this fetcher captures what is publicly available as baseline.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import BaseFetcher

logger = logging.getLogger("sindio.ingestion")

NMS_BASE = "https://nms.go.ke"
NMS_WATER_SCHEDULE = f"{NMS_BASE}/water-supply-schedule"
NMS_ROAD_WORKS = f"{NMS_BASE}/road-maintenance"


class NairobiMetropolitanFetcher(BaseFetcher):
    """Scrape / fetch NMS public infrastructure schedules."""

    source_name = "Nairobi Metropolitan Services"
    infrastructure_type = "water"   # Primary focus: water supply

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._target_urls = [NMS_WATER_SCHEDULE, NMS_ROAD_WORKS]

    def fetch(self) -> List[Dict[str, Any]]:
        """Scrape public pages for infrastructure schedule data."""
        all_records: List[Dict[str, Any]] = []
        for url in self._target_urls:
            records = self._scrape_page(url)
            if records:
                all_records.extend(records)
        return all_records

    def _scrape_page(self, url: str) -> List[Dict[str, Any]]:
        """Scrape a single NMS page for schedule tables."""
        try:
            resp = self._http_get(url, timeout=15)
            if resp is None:
                return []
            text = resp.text
            # Heuristic: look for ward names and dates in the HTML
            # This is fragile — real scraping would use BeautifulSoup with selectors
            # but NMS pages change layout frequently.
            wards = self._extract_ward_mentions(text)
            if not wards:
                return []

            records = []
            for ward in wards:
                records.append({
                    "id": f"nms_{ward.lower().replace(' ', '_')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    "infrastructure_type": "water",
                    "value": 0.0,   # schedule page has no numeric readings
                    "capacity": 100.0,
                    "unit": "scheduled",
                    "timestamp": datetime.now(timezone.utc),
                    "source": self.source_name,
                    "ward": ward,
                    "lat": 0.0,   # Would need geocoding
                    "lon": 0.0,
                    "is_mock": False,
                    "raw_payload": text[:2048],
                })
            return records
        except Exception as exc:
            logger.warning("[NMS] Scrape failed for %s: %s", url, exc)
            return []

    def _extract_ward_mentions(self, html: str) -> List[str]:
        """Naïve ward extraction from HTML text."""
        known_wards = [
            "Westlands", "Dagoretti", "Langata", "Kibra", "Roysambu", "Kasarani",
            "Ruaraka", "Embakasi", "Njiru", "Kamukunji", "Starehe", "Mathare",
            "Makadara", "Pumwani", "Kariobangi", "Kayole", "Pipeline", "Umoja",
            "Buruburu", "Dandora", "Kariobangi South", "Eastleigh", "Parklands",
            "Kilimani", "Karen", "Lavington", "Gigiri", "Runda", "Muthaiga",
            "Kileleshwa", "Hurlingham", "Ngong", "Karen", "Rongai",
        ]
        found = []
        lower_html = html.lower()
        for ward in known_wards:
            if ward.lower() in lower_html:
                found.append(ward)
        return list(set(found))[:20]  # deduplicate, cap at 20

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return raw  # Already normalised in fetch()
