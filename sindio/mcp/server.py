#!/usr/bin/env python3
"""Sindio MCP Server — exposes Sindio urban infrastructure data via Model Context Protocol."""

import json
import os
import sys
import logging

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
logger = logging.getLogger("sindio-mcp")

# ---------------------------------------------------------------------------
# Try the official MCP SDK first
# ---------------------------------------------------------------------------
try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationCapabilities
    from mcp.server.stdio import stdio_server

    HAS_MCP_SDK = True
except ImportError:
    HAS_MCP_SDK = False

# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


def _call_api(path: str, method: str = "GET", body: dict = None) -> dict:
    """Call the Sindio backend API."""
    api_url = os.environ.get("SINDIO_API_URL", "http://localhost:8080")
    api_token = os.environ.get("SINDIO_API_TOKEN", "")
    url = f"{api_url}{path}"

    try:
        import urllib.request
        import urllib.error

        data = None
        if body:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if api_token:
            req.add_header("Authorization", f"Bearer {api_token}")

        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return {"error": f"API error {e.code}", "detail": error_body}
    except Exception as e:
        return {"error": f"API unreachable: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool handlers — call live Sindio API
# ---------------------------------------------------------------------------

def tool_query_cascade(asset_id: str, asset_type: str, city_slug: str = "nairobi"):
    """Analyze cascading failure effects when an asset fails."""
    path = (
        f"/api/v1/cascade/analyze"
        f"?asset_type={asset_type}&asset_id={asset_id}&city_slug={city_slug}"
    )
    return _call_api(path)


def tool_calculate_roi(
    infra_type: str,
    asset_id: str,
    upgrade_cost_kes: float,
    upgrade_description: str,
    asset_lifespan_years: int = 20,
):
    """Calculate ROI for infrastructure upgrades."""
    body = {
        "infra_type": infra_type,
        "asset_id": asset_id,
        "upgrade_cost_kes": upgrade_cost_kes,
        "upgrade_description": upgrade_description,
        "asset_lifespan_years": asset_lifespan_years,
    }
    return _call_api("/api/v1/roi/calculate", method="POST", body=body)


def tool_list_datasets(category: str = None):
    """List available public datasets, optionally filtered by category."""
    path = "/api/v1/datasets"
    if category:
        path += f"?category={category}"
    return _call_api(path)


def tool_get_infrastructure_stress(infra_type: str = None):
    """Get current infrastructure stress levels."""
    path = "/api/v1/monitor/stress"
    if infra_type:
        path += f"?infra_type={infra_type}"
    return _call_api(path)


# ---------------------------------------------------------------------------
# Resource handlers (fallback data for MCP resources)
# ---------------------------------------------------------------------------

RESOURCE_DATASETS = [
    {
        "id": "infra-stress-nairobi",
        "name": "Infrastructure Stress Index — Nairobi",
        "category": "infrastructure",
        "description": "Stress readings for water, power, roads, and waste across Nairobi wards.",
        "format": "JSON/GeoJSON",
    },
    {
        "id": "public-transit-routes",
        "name": "Public Transit Route Network",
        "category": "transport",
        "description": "GTFS-compliant transit routes for Nairobi, Mombasa, and Kisumu.",
        "format": "GTFS/JSON",
    },
    {
        "id": "flood-risk-zones",
        "name": "Flood Risk Zones — Kenya",
        "category": "environment",
        "description": "Flood-risk areas from satellite imagery and hydrological models.",
        "format": "GeoJSON",
    },
    {
        "id": "air-quality-monitoring",
        "name": "Air Quality Sensor Readings",
        "category": "environment",
        "description": "PM2.5, PM10, CO₂, NO₂ readings from 45 stations.",
        "format": "CSV/JSON",
    },
    {
        "id": "ward-demographics-2024",
        "name": "Ward-Level Demographics 2024",
        "category": "demographics",
        "description": "Population and income data for all 47 counties.",
        "format": "CSV/JSON",
    },
    {
        "id": "water-pipeline-network",
        "name": "Water Pipeline Network Atlas",
        "category": "infrastructure",
        "description": "GIS layer of water distribution network.",
        "format": "GeoJSON",
    },
    {
        "id": "power-grid-topology",
        "name": "Power Grid Topology Dataset",
        "category": "infrastructure",
        "description": "Substations, transmission lines, and feeder maps.",
        "format": "GeoJSON",
    },
    {
        "id": "solid-waste-collection",
        "name": "Solid Waste Collection Schedule",
        "category": "waste",
        "description": "Ward-level collection routes and coverage.",
        "format": "JSON",
    },
]

RESOURCE_CITIES = [
    {
        "slug": "nairobi",
        "name": "Nairobi",
        "county": "Nairobi County",
        "population": 5700000,
        "wards_count": 85,
    },
    {
        "slug": "mombasa",
        "name": "Mombasa",
        "county": "Mombasa County",
        "population": 1520000,
        "wards_count": 30,
    },
    {
        "slug": "kisumu",
        "name": "Kisumu",
        "county": "Kisumu County",
        "population": 720000,
        "wards_count": 35,
    },
]

RESOURCE_INFRA_TYPES = ["water", "power", "roads", "waste"]


def resource_list_datasets():
    return json.dumps(RESOURCE_DATASETS, indent=2)


def resource_infrastructure_stress(infra_type: str):
    result = _call_api(f"/api/v1/monitor/stress?infra_type={infra_type}")
    return json.dumps(result, indent=2)


def resource_cities():
    return json.dumps(RESOURCE_CITIES, indent=2)


# ============================================================================
# MCP SDK path
# ============================================================================

if HAS_MCP_SDK:

    app = Server("sindio-mcp")

    @app.list_tools()
    async def list_tools():
        return [
            {
                "name": "query_cascade",
                "description": "Analyzes cascading failure effects when an infrastructure asset fails. Returns direct impact, multi-step cascade timeline, affected assets, and mitigation options.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string", "description": "Asset identifier (e.g. WTR-KAR-045, PWR-EMB-022)"},
                        "asset_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Type of infrastructure asset"},
                        "city_slug": {"type": "string", "description": "City slug (default: nairobi)"},
                    },
                    "required": ["asset_id", "asset_type"],
                },
            },
            {
                "name": "calculate_roi",
                "description": "Calculates return on investment for infrastructure upgrades. Returns annual benefits breakdown, payback period, NPV, and recommendation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "infra_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Type of infrastructure"},
                        "asset_id": {"type": "string", "description": "Asset identifier"},
                        "upgrade_cost_kes": {"type": "number", "description": "Total cost of the upgrade in KES"},
                        "upgrade_description": {"type": "string", "description": "Description of the upgrade work"},
                        "asset_lifespan_years": {"type": "integer", "description": "Expected lifespan in years (default: 20)"},
                    },
                    "required": ["infra_type", "asset_id", "upgrade_cost_kes", "upgrade_description"],
                },
            },
            {
                "name": "list_datasets",
                "description": "Lists available public datasets from the Sindio platform. Optionally filter by category (infrastructure, transport, environment, demographics, waste).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by dataset category"},
                    },
                },
            },
            {
                "name": "get_infrastructure_stress",
                "description": "Gets current infrastructure stress levels across Nairobi. Returns overall stress scores, top stressed wards, critical assets, and trends for water, power, roads, and waste systems.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "infra_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Specific infrastructure type (omit for all)"},
                    },
                },
            },
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "query_cascade":
            return [{"type": "text", "text": json.dumps(
                tool_query_cascade(
                    arguments.get("asset_id", ""),
                    arguments.get("asset_type", ""),
                    arguments.get("city_slug", "nairobi"),
                ),
                indent=2,
            )}]
        elif name == "calculate_roi":
            return [{"type": "text", "text": json.dumps(
                tool_calculate_roi(
                    arguments.get("infra_type", ""),
                    arguments.get("asset_id", ""),
                    float(arguments.get("upgrade_cost_kes", 0)),
                    arguments.get("upgrade_description", ""),
                    int(arguments.get("asset_lifespan_years", 20)),
                ),
                indent=2,
            )}]
        elif name == "list_datasets":
            return [{"type": "text", "text": json.dumps(
                tool_list_datasets(arguments.get("category")),
                indent=2,
            )}]
        elif name == "get_infrastructure_stress":
            return [{"type": "text", "text": json.dumps(
                tool_get_infrastructure_stress(arguments.get("infra_type")),
                indent=2,
            )}]
        return [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {name}"})}]

    @app.list_resources()
    async def list_resources():
        return [
            {"uri": "sindio://datasets", "name": "Sindio Public Datasets", "mimeType": "application/json", "description": "All public datasets available on the Sindio platform"},
            {"uri": "sindio://cities", "name": "Available Cities", "mimeType": "application/json", "description": "Cities monitored by Sindio with their ward lists"},
            *[
                {"uri": f"sindio://infrastructure/{t}/stress", "name": f"{t.title()} Infrastructure Stress", "mimeType": "application/json", "description": f"Current stress levels for {t} infrastructure"}
                for t in RESOURCE_INFRA_TYPES
            ],
        ]

    @app.read_resource()
    async def read_resource(uri: str):
        if uri == "sindio://datasets":
            return [{"type": "text", "text": resource_list_datasets()}]
        elif uri == "sindio://cities":
            return [{"type": "text", "text": resource_cities()}]
        elif uri.startswith("sindio://infrastructure/") and uri.endswith("/stress"):
            infra_type = uri.split("/")[2]
            return [{"type": "text", "text": resource_infrastructure_stress(infra_type)}]
        return [{"type": "text", "text": json.dumps({"error": f"Unknown resource: {uri}"})}]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    if __name__ == "__main__":
        import asyncio
        asyncio.run(main())

else:
    # ========================================================================
    # Manual MCP JSON-RPC over stdio
    # ========================================================================

    TOOLS = [
        {
            "name": "query_cascade",
            "description": "Analyzes cascading failure effects when an infrastructure asset fails. Returns direct impact, multi-step cascade timeline, affected assets, and mitigation options.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "Asset identifier (e.g. WTR-KAR-045, PWR-EMB-022)"},
                    "asset_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Type of infrastructure asset"},
                    "city_slug": {"type": "string", "description": "City slug (default: nairobi)"},
                },
                "required": ["asset_id", "asset_type"],
            },
        },
        {
            "name": "calculate_roi",
            "description": "Calculates return on investment for infrastructure upgrades. Returns annual benefits breakdown, payback period, NPV, and recommendation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "infra_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Type of infrastructure"},
                    "asset_id": {"type": "string", "description": "Asset identifier"},
                    "upgrade_cost_kes": {"type": "number", "description": "Total cost of the upgrade in KES"},
                    "upgrade_description": {"type": "string", "description": "Description of the upgrade work"},
                    "asset_lifespan_years": {"type": "integer", "description": "Expected lifespan in years (default: 20)"},
                },
                "required": ["infra_type", "asset_id", "upgrade_cost_kes", "upgrade_description"],
            },
        },
        {
            "name": "list_datasets",
            "description": "Lists available public datasets from the Sindio platform. Optionally filter by category (infrastructure, transport, environment, demographics, waste).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by dataset category"},
                },
            },
        },
        {
            "name": "get_infrastructure_stress",
            "description": "Gets current infrastructure stress levels across Nairobi. Returns overall stress scores, top stressed wards, critical assets, and trends for water, power, roads, and waste systems.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "infra_type": {"type": "string", "enum": ["water", "power", "roads", "waste"], "description": "Specific infrastructure type (omit for all)"},
                },
            },
        },
    ]

    RESOURCES = [
        {"uri": "sindio://datasets", "name": "Sindio Public Datasets", "mimeType": "application/json", "description": "All public datasets available on the Sindio platform"},
        {"uri": "sindio://cities", "name": "Available Cities", "mimeType": "application/json", "description": "Cities monitored by Sindio with their ward lists"},
        *[
            {"uri": f"sindio://infrastructure/{t}/stress", "name": f"{t.title()} Infrastructure Stress", "mimeType": "application/json", "description": f"Current stress levels for {t} infrastructure"}
            for t in RESOURCE_INFRA_TYPES
        ],
    ]

    TOOL_DISPATCH = {
        "query_cascade": lambda args: tool_query_cascade(
            args.get("asset_id", ""), args.get("asset_type", ""), args.get("city_slug", "nairobi")
        ),
        "calculate_roi": lambda args: tool_calculate_roi(
            args.get("infra_type", ""),
            args.get("asset_id", ""),
            float(args.get("upgrade_cost_kes", 0)),
            args.get("upgrade_description", ""),
            int(args.get("asset_lifespan_years", 20)),
        ),
        "list_datasets": lambda args: tool_list_datasets(args.get("category")),
        "get_infrastructure_stress": lambda args: tool_get_infrastructure_stress(args.get("infra_type")),
    }

    RESOURCE_DISPATCH = {
        "sindio://datasets": lambda: resource_list_datasets(),
        "sindio://cities": lambda: resource_cities(),
        **{f"sindio://infrastructure/{t}/stress": (lambda t=t: resource_infrastructure_stress(t)) for t in RESOURCE_INFRA_TYPES},
    }

    SERVER_INFO = {
        "name": "sindio-mcp",
        "version": "1.0.0",
    }

    def send_response(rpc_id, result):
        payload = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def send_error(rpc_id, code, message):
        payload = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def handle_initialize(msg_id, params):
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
            },
            "serverInfo": SERVER_INFO,
        }

    def handle_tools_list(msg_id, params):
        return {"tools": TOOLS}

    def handle_tools_call(msg_id, params):
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_DISPATCH.get(tool_name)
        if not handler:
            send_error(msg_id, -32601, f"Unknown tool: {tool_name}")
            return None
        try:
            result_data = handler(arguments)
            return {"content": [{"type": "text", "text": json.dumps(result_data, indent=2)}]}
        except Exception as exc:
            logger.exception("Tool call failed")
            send_error(msg_id, -32603, str(exc))
            return None

    def handle_resources_list(msg_id, params):
        return {"resources": RESOURCES}

    def handle_resources_read(msg_id, params):
        uri = params.get("uri", "")
        handler = RESOURCE_DISPATCH.get(uri)
        if not handler:
            send_error(msg_id, -32601, f"Unknown resource: {uri}")
            return None
        try:
            text = handler()
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        except Exception as exc:
            logger.exception("Resource read failed")
            send_error(msg_id, -32603, str(exc))
            return None

    METHOD_TABLE = {
        "initialize": handle_initialize,
        "notifications/initialized": lambda msg_id, params: None,
        "tools/list": handle_tools_list,
        "tools/call": handle_tools_call,
        "resources/list": handle_resources_list,
        "resources/read": handle_resources_read,
    }

    def main_loop():
        logger.info("Sindio MCP server starting (manual JSON-RPC mode)")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_id = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params", {})

            handler = METHOD_TABLE.get(method)
            if handler is None:
                send_error(msg_id, -32601, f"Method not found: {method}")
                continue

            result = handler(msg_id, params)
            if result is not None:
                send_response(msg_id, result)

    if __name__ == "__main__":
        main_loop()
