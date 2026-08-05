# Sindio MCP Server

Model Context Protocol server that lets Claude Desktop or ChatGPT query Sindio urban
infrastructure data directly — cascading failure analysis, ROI calculations,
infrastructure stress levels, and public datasets.

## Installation

```bash
pip install -r requirements.txt
```

The server tries to use the official `mcp` SDK. If it is not available it falls back
to a manual JSON-RPC-over-stdio implementation (no extra dependencies).

## Configuration

### Claude Desktop

Add this to your `claude_desktop_config.json` (macOS: `~/Library/Application
Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sindio": {
      "command": "python3",
      "args": ["/Users/jordanmafumbo/Desktop/Code (Projects)/S:i/sindio/mcp/server.py"]
    }
  }
}
```

### ChatGPT / Other MCP Clients

Any client that speaks MCP over stdio works — point it at the same `server.py`.

## Tools

| Tool                       | Description                                        |
| -------------------------- | -------------------------------------------------- |
| `query_cascade`            | Analyse cascading failure effects when an asset fails |
| `calculate_roi`            | Calculate ROI for infrastructure upgrades          |
| `list_datasets`            | List available public datasets                     |
| `get_infrastructure_stress` | Get current infrastructure stress levels           |

## Resources

| URI                                  | Content                         |
| ------------------------------------ | ------------------------------- |
| `sindio://datasets`                  | All public datasets             |
| `sindio://cities`                    | Cities monitored (with wards)   |
| `sindio://infrastructure/{type}/stress` | Per-type stress data         |

## Example Queries

Once connected to Claude Desktop, try:

- "Show me the cascading failure effects if the Kariobangi water treatment plant fails."
- "Calculate the ROI for upgrading the Embakasi switching station."
- "What datasets does Sindio have available?"
- "What is the current stress level of Nairobi's water infrastructure?"
- "List all cities Sindio monitors with their wards."
