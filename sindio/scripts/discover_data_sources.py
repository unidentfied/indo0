#!/usr/bin/env python3
"""
Sindio — Data Source Discovery Script
======================================

Searches for Nairobi/Kenya water infrastructure data sources via:
  1. SerpAPI Google search for "Nairobi Water SCADA API documentation"
  2. SerpAPI search of Kenya open data portals
  3. Direct scraping of the first 3 result pages for API endpoints,
     auth methods, and rate limits
  4. Cross-references discovered sources against the current mock API
     surface to identify real-world replacements

Outputs: data/data_sources_candidates.json with:
  - sources[] — verified real data sources
  - mock_to_real_mapping[] — which mock endpoints have real replacements
  - mock_coverage — % of mock endpoints with at least one real candidate
  - filtered_out[] — URLs rejected as tutorial/mock/fake

Emails: a summary when new sources appear compared to the previous run.

Usage:
    export SERPAPI_API_KEY="your-key"
    export NOTIFY_EMAIL="you@example.com"
    export SMTP_HOST="smtp.gmail.com"
    export SMTP_PORT=587
    export SMTP_USER="you@gmail.com"
    export SMTP_PASSWORD="app-password"
    python scripts/discover_data_sources.py

Schedule weekly via cron:
    0 9 * * 1 cd /path/to/sindio && poetry run python scripts/discover_data_sources.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("sindio.discover")

# ── Config ─────────────────────────────────────────────────────────

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "data_sources_candidates.json"
HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / ".discover_history.json"

SEARCH_QUERIES = [
    "Nairobi Water SCADA API documentation",
    "Nairobi City Water and Sewerage Company API",
    "Kenya open data water infrastructure SCADA",
    "Kenya Water Resources Authority API data",
    "site:data.go.ke water infrastructure",
    "site:opendata.go.ke Nairobi water",
]

# ── Known mock API surface (extracted from backend/app/routers/api.py) ──

MOCK_ENDPOINTS: List[Dict[str, Any]] = [
    {
        "method": "GET",
        "path": "/api/dashboard/metrics",
        "data_type": "infrastructure metrics",
        "infra_types": ["power", "water", "roads", "transit"],
        "description": "Random mock metrics (grid stability, current load, avg transit, water pressure)",
    },
    {
        "method": "GET",
        "path": "/api/dashboard/alerts",
        "data_type": "alerts",
        "infra_types": ["electricity", "utilities", "traffic", "water", "roads"],
        "description": "5 hardcoded static alerts with fixed timestamps",
    },
    {
        "method": "GET",
        "path": "/api/infrastructure/{system}",
        "data_type": "infrastructure status",
        "infra_types": ["water", "power", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "Hardcoded status dicts (grid_stability, current_load, active_nodes, capacity_percent)",
    },
    {
        "method": "POST",
        "path": "/api/simulations/run",
        "data_type": "simulation results",
        "infra_types": ["power", "water"],
        "description": "Fixed 5-point time-series impact data, random ID",
    },
    {
        "method": "GET",
        "path": "/api/simulations/status",
        "data_type": "simulation status",
        "infra_types": [],
        "description": "Hardcoded status (active=True, progress=0.68)",
    },
    {
        "method": "GET",
        "path": "/api/predictive-params",
        "data_type": "predictive parameters",
        "infra_types": [],
        "description": "Fixed params (thermal_stress=42, population_density=peak)",
    },
    {
        "method": "POST",
        "path": "/api/simulate/run",
        "data_type": "async simulation",
        "infra_types": ["any"],
        "description": "Redis-backed mock task queue, returns task_id",
    },
    {
        "method": "GET",
        "path": "/api/simulate/status/{task_id}",
        "data_type": "task state",
        "infra_types": [],
        "description": "Mock task state machine (PENDING/STARTED/SUCCESS/FAILURE)",
    },
    {
        "method": "GET",
        "path": "/api/v1/alerts",
        "data_type": "alerts v1",
        "infra_types": ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "12 generated mock alerts with synthetic GeoJSON",
    },
    {
        "method": "GET",
        "path": "/api/v1/next_updates",
        "data_type": "update schedule",
        "infra_types": ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "Fixed intervals (60s–600s) per infra type",
    },
    {
        "method": "GET",
        "path": "/api/v1/spatial/stress-heatmap",
        "data_type": "spatial heatmap",
        "infra_types": ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "Random GeoJSON grid with seeded stress values",
    },
    {
        "method": "GET",
        "path": "/api/v1/spatial/nearest-asset",
        "data_type": "spatial nearest",
        "infra_types": ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "5 random mock assets near given coordinates",
    },
    {
        "method": "POST",
        "path": "/api/v1/spatial/alerts-in-polygon",
        "data_type": "spatial alerts",
        "infra_types": ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        "description": "20 generated mock alerts filtered by polygon bbox",
    },
    {
        "method": "POST",
        "path": "/api/v1/scenario/generate",
        "data_type": "scenario generation",
        "infra_types": ["power", "water", "roads", "solid_waste"],
        "description": "Fixed RAG-style response with 3 hardcoded similar scenarios",
    },
]

# All infra types the mock covers
MOCK_INFRA_TYPES: Set[str] = set()
for ep in MOCK_ENDPOINTS:
    MOCK_INFRA_TYPES.update(ep["infra_types"])

# ── Filters: known tutorial/mock/fake domains ──────────────────────

FILTERED_DOMAINS: Set[str] = {
    "stackoverflow.com", "stackexchange.com",
    "github.com", "gist.github.com",
    "medium.com", "dev.to", "hackernoon.com",
    "tutorialspoint.com", "w3schools.com", "geeksforgeeks.org",
    "postman.com", "swagger.io",
    "jsonplaceholder.typicode.com",
    "mockapi.io", "mocky.io", "beeceptor.com",
    "reqres.in", "httpbin.org",
    "example.com", "example.org",
    "youtube.com", "youtu.be",
    "reddit.com",
    "quora.com",
    "npmjs.com", "pypi.org", "crates.io",
}

FILTERED_URL_PATTERNS: List[str] = [
    r"tutorial",
    r"example[-_]?api",
    r"mock[-_]?server",
    r"fake[-_]?data",
    r"placeholder",
    r"sample[-_]?endpoint",
    r"demo[-_]?api",
    r"test[-_]?api",
    r"/swagger-ui",
    r"/petstore",
    r"/dummyjson",
    r"/jsonplaceholder",
]


# ── SerpAPI client ─────────────────────────────────────────────────

def serpapi_search(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """Search via SerpAPI and return organic results."""
    if not SERPAPI_API_KEY:
        logger.warning("SERPAPI_API_KEY not set — skipping SerpAPI search for: %s", query)
        return []

    url = "https://serpapi.com/search.json"
    params = {
        "api_key": SERPAPI_API_KEY,
        "q": query,
        "num": num_results,
        "engine": "google",
    }

    try:
        resp = httpx.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("organic_results", [])
    except httpx.HTTPError as exc:
        logger.error("SerpAPI request failed for '%s': %s", query, exc)
        return []
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("SerpAPI response parse error for '%s': %s", query, exc)
        return []


# ── Filtering ──────────────────────────────────────────────────────

def is_filtered(url: str, title: str = "", snippet: str = "") -> Tuple[bool, str]:
    """Check if a URL should be filtered out as a tutorial/mock/fake source.

    Returns (is_filtered, reason).
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")

    # Domain blocklist
    if domain in FILTERED_DOMAINS:
        return True, f"blocked domain: {domain}"

    # Check for subdomains of blocked domains
    for blocked in FILTERED_DOMAINS:
        if domain.endswith(f".{blocked}"):
            return True, f"blocked domain: {domain}"

    # URL pattern matching
    url_lower = url.lower()
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    combined = f"{url_lower} {title_lower} {snippet_lower}"

    for pattern in FILTERED_URL_PATTERNS:
        if re.search(pattern, combined):
            return True, f"matched pattern: {pattern}"

    # Heuristic: if title/snippet clearly says "mock", "fake", "example", "tutorial"
    mock_indicators = [
        "mock api", "fake api", "example api", "sample api",
        "tutorial api", "demo api", "test api",
        "this is a mock", "for demonstration", "for testing",
        "placeholder data", "dummy data",
    ]
    for indicator in mock_indicators:
        if indicator in title_lower or indicator in snippet_lower:
            return True, f"mock indicator: {indicator}"

    return False, ""


# ── Page scraper ───────────────────────────────────────────────────

def scrape_page(url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch a page and extract API endpoints, auth methods, and rate limits."""
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SindioDataDiscovery/0.1)"
            },
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text_lower = text.lower()

    # ── API endpoints ──
    endpoints: List[str] = []

    for tag in soup.find_all(["a", "code", "pre"]):
        href = tag.get("href", "")
        code_text = tag.get_text(strip=True)
        for candidate in [href, code_text]:
            if _looks_like_api_path(candidate):
                endpoints.append(candidate)

    api_path_pattern = re.compile(r'["\'](/api/[\w/\-{}]+)["\']')
    for match in api_path_pattern.finditer(text):
        endpoints.append(match.group(1))

    endpoints = sorted(set(endpoints))[:20]

    # ── Authentication methods ──
    auth_methods: List[str] = []
    auth_patterns = [
        (r"(?:OAuth\s*2\.?0?)", "OAuth 2.0"),
        (r"(?:Bearer\s+(?:token|auth))", "Bearer token"),
        (r"(?:API\s*key|api[_-]?key)", "API key"),
        (r"(?:Basic\s+auth|HTTP\s*Basic)", "HTTP Basic"),
        (r"(?:JWT|JSON\s*Web\s*Token)", "JWT"),
        (r"(?:mTLS|mutual\s*TLS|client\s*certificate)", "mTLS"),
        (r"(?:SAML|SAML\s*2\.?0?)", "SAML"),
        (r"(?:token[_-]?based|tokenised?\s*auth)", "Token-based"),
        (r"(?:username\s*(?:and|&)\s*password|credentials)", "Username/password"),
    ]
    for pattern, label in auth_patterns:
        if re.search(pattern, text_lower):
            auth_methods.append(label)
    auth_methods = sorted(set(auth_methods))

    # ── Rate limits ──
    rate_limits: List[str] = []
    rate_patterns = [
        r"(\d+)\s*(?:requests?|calls?|queries?)\s*(?:per|/)\s*(?:minute|second|hour|day|month)",
        r"(\d+)\s*(?:req|rps|rpm|rph)\b",
        r"(?:rate\s*limit(?:ed)?|throttl(?:ed|ing))\s*:?\s*(.+?)(?:\.|\n)",
        r"(?:X-RateLimit|X-Request-Limit|Rate-Limit)",
    ]
    for pattern in rate_patterns:
        for match in re.finditer(pattern, text_lower):
            snippet = match.group(0).strip()
            if snippet and len(snippet) < 200:
                rate_limits.append(snippet)
    rate_limits = sorted(set(rate_limits))[:5]

    # ── Data type hints ──
    data_types: List[str] = []
    type_keywords = [
        "scada", "telemetry", "sensor", "meter", "water quality",
        "flow rate", "pressure", "consumption", "billing", "GIS",
        "infrastructure", "asset", "maintenance", "outage", "leak",
        "distribution", "treatment", "reservoir", "pump", "valve",
    ]
    for kw in type_keywords:
        if kw in text_lower:
            data_types.append(kw)
    data_types = sorted(set(data_types))[:10]

    return {
        "endpoints": endpoints,
        "auth_methods": auth_methods,
        "rate_limits": rate_limits,
        "data_types": data_types,
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "title": soup.title.string.strip() if soup.title else "",
    }


def _looks_like_api_path(s: str) -> bool:
    """Heuristic: does this string look like an API endpoint path?"""
    if not s or len(s) > 200:
        return False
    s = s.strip()
    api_patterns = [
        r"^/api/",
        r"^/v\d+/",
        r"^/graphql",
        r"^/rest/",
        r"^/odata/",
        r"^/swagger",
        r"^/openapi",
        r"^/docs",
    ]
    return any(re.search(p, s) for p in api_patterns)


# ── Source classification ─────────────────────────────────────────

def classify_source(url: str, title: str, snippet: str, scrape: Optional[Dict]) -> Dict[str, Any]:
    """Build a candidate source record."""
    parsed = urlparse(url)
    source_name = parsed.netloc.replace("www.", "").split(".")[0].title()
    if title:
        source_name = title.split("|")[0].split("-")[0].strip()

    url_lower = url.lower()
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    combined = f"{url_lower} {title_lower} {snippet_lower}"

    data_type = "unknown"
    if any(kw in combined for kw in ["scada", "telemetry", "sensor", "meter"]):
        data_type = "SCADA / telemetry"
    elif any(kw in combined for kw in ["water quality", "quality"]):
        data_type = "Water quality"
    elif any(kw in combined for kw in ["gis", "spatial", "map"]):
        data_type = "GIS / spatial"
    elif any(kw in combined for kw in ["billing", "consumption", "customer"]):
        data_type = "Billing / consumption"
    elif any(kw in combined for kw in ["open data", "opendata", "data.go.ke"]):
        data_type = "Open data portal"
    elif any(kw in combined for kw in ["api", "rest", "graphql"]):
        data_type = "API documentation"
    elif any(kw in combined for kw in ["weather", "rainfall", "climate"]):
        data_type = "Weather / climate"

    access_notes: List[str] = []
    if scrape:
        if scrape["auth_methods"]:
            access_notes.append(f"Auth: {', '.join(scrape['auth_methods'])}")
        if scrape["rate_limits"]:
            access_notes.append(f"Rate limits: {'; '.join(scrape['rate_limits'])}")
        if scrape["endpoints"]:
            access_notes.append(f"Found {len(scrape['endpoints'])} API endpoint(s)")
        if scrape["data_types"]:
            access_notes.append(f"Data types: {', '.join(scrape['data_types'])}")
    else:
        access_notes.append("Page not scraped (fetch failed or SerpAPI only)")

    return {
        "source_name": source_name,
        "url": url,
        "data_type": data_type,
        "access_notes": " | ".join(access_notes) if access_notes else "No details found",
        "scrape_details": scrape,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Mock-to-real mapping ──────────────────────────────────────────

def build_mock_to_real_mapping(
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Cross-reference discovered real sources against mock endpoints.

    Returns a list of mappings showing which mock endpoints have real-world
    data source candidates.
    """
    mapping: List[Dict[str, Any]] = []

    for mock_ep in MOCK_ENDPOINTS:
        mock_data_type = mock_ep["data_type"].lower()
        mock_infra = set(mock_ep["infra_types"])

        matched_sources: List[Dict[str, Any]] = []

        for src in sources:
            src_data_type = src.get("data_type", "").lower()
            src_notes = src.get("access_notes", "").lower()
            src_scrape = src.get("scrape_details") or {}
            src_scrape_types = [t.lower() for t in src_scrape.get("data_types", [])]

            # Match by data type overlap
            type_match = False
            if mock_data_type in src_data_type or src_data_type in mock_data_type:
                type_match = True
            if any(kw in src_notes for kw in mock_data_type.split()):
                type_match = True
            if any(kw in src_scrape_types for kw in mock_data_type.split()):
                type_match = True

            # Match by infrastructure type overlap
            infra_match = False
            if mock_infra:
                for infra in mock_infra:
                    if infra in src_data_type or infra in src_notes:
                        infra_match = True
                        break
                for infra in mock_infra:
                    if any(infra in t for t in src_scrape_types):
                        infra_match = True
                        break
            else:
                infra_match = True  # endpoint has no specific infra type

            if type_match or infra_match:
                matched_sources.append({
                    "source_name": src["source_name"],
                    "url": src["url"],
                    "data_type": src["data_type"],
                    "confidence": _match_confidence(mock_ep, src),
                })

        if matched_sources:
            matched_sources.sort(key=lambda s: s["confidence"], reverse=True)
            mapping.append({
                "mock_endpoint": f"{mock_ep['method']} {mock_ep['path']}",
                "mock_description": mock_ep["description"],
                "mock_data_type": mock_ep["data_type"],
                "mock_infra_types": mock_ep["infra_types"],
                "real_candidates": matched_sources,
                "candidate_count": len(matched_sources),
            })

    return mapping


def _match_confidence(mock_ep: Dict[str, Any], src: Dict[str, Any]) -> float:
    """Score how well a real source matches a mock endpoint (0.0–1.0)."""
    score = 0.0

    mock_type = mock_ep["data_type"].lower()
    src_type = src.get("data_type", "").lower()
    src_notes = src.get("access_notes", "").lower()
    scrape = src.get("scrape_details") or {}

    # Exact data type match
    if mock_type == src_type:
        score += 0.4
    elif mock_type in src_type or src_type in mock_type:
        score += 0.25

    # Has scraped API endpoints
    if scrape.get("endpoints"):
        score += 0.2

    # Has auth info (more likely to be a real API)
    if scrape.get("auth_methods"):
        score += 0.1

    # Has rate limits (more likely to be production)
    if scrape.get("rate_limits"):
        score += 0.1

    # Infra type overlap
    mock_infra = set(mock_ep.get("infra_types", []))
    if mock_infra:
        src_scrape_types = [t.lower() for t in scrape.get("data_types", [])]
        overlap = mock_infra & set(src_scrape_types)
        if overlap:
            score += 0.1 * min(len(overlap), 2)

    return round(min(score, 1.0), 2)


# ── Dedup & history ────────────────────────────────────────────────

def load_history() -> List[str]:
    """Load previously seen URLs."""
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            return data.get("seen_urls", [])
        except (json.JSONDecodeError, KeyError):
            return []
    return []


def save_history(urls: List[str]) -> None:
    """Persist seen URLs."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(
            {"seen_urls": urls, "updated_at": datetime.now(timezone.utc).isoformat()},
            indent=2,
        )
    )


def find_new_sources(
    candidates: List[Dict[str, Any]], seen_urls: List[str]
) -> List[Dict[str, Any]]:
    """Return candidates whose URL is not in seen_urls."""
    seen_set = set(seen_urls)
    return [c for c in candidates if c["url"] not in seen_set]


# ── Email notification ─────────────────────────────────────────────

def send_email(
    new_sources: List[Dict[str, Any]],
    mock_mapping: List[Dict[str, Any]],
    mock_coverage: float,
) -> None:
    """Send an email summary of newly discovered sources and mock coverage."""
    if not NOTIFY_EMAIL or not SMTP_USER or not SMTP_PASSWORD:
        logger.info(
            "Email not configured (set NOTIFY_EMAIL, SMTP_USER, SMTP_PASSWORD). "
            "Found %d new source(s) — see output file.",
            len(new_sources),
        )
        return

    subject = f"[Sindio] {len(new_sources)} new data source(s) | {mock_coverage:.0f}% mock coverage"

    body_lines = [
        "Sindio Data Source Discovery — Weekly Report",
        f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"New sources found: {len(new_sources)}",
        f"Mock endpoint coverage: {mock_coverage:.0f}% ({len(mock_mapping)}/{len(MOCK_ENDPOINTS)} endpoints have real candidates)",
        "",
        "=" * 60,
    ]

    if new_sources:
        body_lines.append("\nNEW SOURCES:")
        for i, src in enumerate(new_sources, 1):
            body_lines.append(f"\n{i}. {src['source_name']}")
            body_lines.append(f"   URL: {src['url']}")
            body_lines.append(f"   Type: {src['data_type']}")
            body_lines.append(f"   Notes: {src['access_notes']}")

            details = src.get("scrape_details")
            if details:
                if details.get("endpoints"):
                    body_lines.append(f"   Endpoints: {', '.join(details['endpoints'][:5])}")
                if details.get("auth_methods"):
                    body_lines.append(f"   Auth: {', '.join(details['auth_methods'])}")
                if details.get("rate_limits"):
                    body_lines.append(f"   Rate limits: {', '.join(details['rate_limits'])}")

    if mock_mapping:
        body_lines.append("\n" + "=" * 60)
        body_lines.append("MOCK → REAL MAPPING (endpoints with real candidates):")
        for m in mock_mapping[:10]:
            body_lines.append(f"\n  {m['mock_endpoint']}")
            body_lines.append(f"    Mock: {m['mock_description']}")
            for c in m["real_candidates"][:3]:
                body_lines.append(
                    f"    → {c['source_name']} ({c['data_type']}) "
                    f"[confidence: {c['confidence']:.2f}]"
                )

    body_lines.append("\n" + "=" * 60)
    body_lines.append("Full results: data/data_sources_candidates.json")

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText("\n".join(body_lines), "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s", NOTIFY_EMAIL)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)


# ── Main pipeline ──────────────────────────────────────────────────

def run() -> Dict[str, Any]:
    """Execute the full discovery pipeline."""
    logger.info("Starting data source discovery…")
    logger.info("Mock API surface: %d endpoints covering %d infra types", len(MOCK_ENDPOINTS), len(MOCK_INFRA_TYPES))

    seen_urls = load_history()
    all_results: List[Dict[str, Any]] = []
    filtered_out: List[Dict[str, str]] = []
    scraped_urls: set = set()

    for query in SEARCH_QUERIES:
        logger.info("Searching: %s", query)
        results = serpapi_search(query, num_results=10)
        logger.info("  → %d results", len(results))

        for idx, r in enumerate(results):
            url = r.get("link", "")
            if not url or url in scraped_urls:
                continue
            scraped_urls.add(url)

            title = r.get("title", "")
            snippet = r.get("snippet", "")

            # Filter out tutorials, mock APIs, fake data sources
            is_filt, reason = is_filtered(url, title, snippet)
            if is_filt:
                logger.info("  ✗ Filtered: %s (%s)", url, reason)
                filtered_out.append({"url": url, "title": title, "reason": reason})
                continue

            # Scrape first 3 non-filtered results per query
            scrape_data = None
            if idx < 3:
                logger.info("  Scraping: %s", url)
                scrape_data = scrape_page(url)
                time.sleep(1)

            candidate = classify_source(url, title, snippet, scrape_data)
            all_results.append(candidate)

    # Deduplicate by URL, keeping the richest record
    deduped: Dict[str, Dict[str, Any]] = {}
    for c in all_results:
        url = c["url"]
        if url not in deduped:
            deduped[url] = c
        else:
            existing = deduped[url]
            if c.get("scrape_details") and not existing.get("scrape_details"):
                deduped[url] = c
            elif c.get("scrape_details") and existing.get("scrape_details"):
                for key in ["endpoints", "auth_methods", "rate_limits", "data_types"]:
                    existing_vals = set(existing.get("scrape_details", {}).get(key, []))
                    new_vals = set(c.get("scrape_details", {}).get(key, []))
                    merged = sorted(existing_vals | new_vals)
                    existing["scrape_details"][key] = merged
                existing["access_notes"] = c["access_notes"]

    sources = list(deduped.values())

    # Build mock-to-real mapping
    mock_mapping = build_mock_to_real_mapping(sources)
    mock_coverage = len(mock_mapping) / len(MOCK_ENDPOINTS) if MOCK_ENDPOINTS else 0.0

    # Find new sources
    new_sources = find_new_sources(sources, seen_urls)

    # Update history
    all_seen = list(set(seen_urls) | {c["url"] for c in sources})
    save_history(all_seen)

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sources": len(sources),
        "new_sources": len(new_sources),
        "filtered_out_count": len(filtered_out),
        "mock_coverage": round(mock_coverage, 2),
        "mock_endpoint_count": len(MOCK_ENDPOINTS),
        "mock_infra_types_covered": sorted(MOCK_INFRA_TYPES),
        "sources": sorted(sources, key=lambda s: s["source_name"]),
        "mock_to_real_mapping": mock_mapping,
        "unmapped_mock_endpoints": [
            {
                "endpoint": f"{ep['method']} {ep['path']}",
                "description": ep["description"],
                "data_type": ep["data_type"],
            }
            for ep in MOCK_ENDPOINTS
            if not any(m["mock_endpoint"] == f"{ep['method']} {ep['path']}" for m in mock_mapping)
        ],
        "filtered_out": filtered_out,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    logger.info(
        "Wrote %d source(s) to %s (%d new, %d filtered, %.0f%% mock coverage)",
        len(sources), OUTPUT_PATH, len(new_sources), len(filtered_out), mock_coverage * 100,
    )

    # Notify
    if new_sources or mock_mapping:
        send_email(new_sources, mock_mapping, mock_coverage)
    else:
        logger.info("No new sources discovered this run.")

    return output


if __name__ == "__main__":
    if not SERPAPI_API_KEY:
        logger.error("SERPAPI_API_KEY environment variable is required.")
        logger.error("Get one at https://serpapi.com/ and export it:")
        logger.error("  export SERPAPI_API_KEY='your-key'")
        sys.exit(1)

    run()
