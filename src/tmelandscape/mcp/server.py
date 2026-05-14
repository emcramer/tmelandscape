"""fastmcp server exposing tmelandscape's public API as MCP tools.

Pipeline-step tools land here phase-by-phase. v0.0.1 (Phase 0) only registers
``ping`` so the server boots and integration tests can verify the transport.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from tmelandscape import __version__
from tmelandscape.mcp.tools import (
    describe_statistic_tool,
    generate_sweep_tool,
    list_available_statistics_tool,
    list_normalize_strategies_tool,
    normalize_ensemble_tool,
    summarize_ensemble_tool,
)

mcp: FastMCP = FastMCP(
    name="tmelandscape",
    instructions=(
        "Tumor microenvironment state-landscape generation. "
        "Available tools: ping (health check), generate_sweep (step 1 — "
        "parameter sampling + IC replicate generation). Step 3 "
        "(spatialtissuepy summarisation), normalize, embed, cluster land in "
        "later releases."
    ),
)


@mcp.tool
def ping() -> dict[str, Any]:
    """Health check. Returns the running tmelandscape version."""
    return {"status": "ok", "version": __version__}


mcp.tool(generate_sweep_tool, name="generate_sweep")
mcp.tool(summarize_ensemble_tool, name="summarize_ensemble")
mcp.tool(list_available_statistics_tool, name="list_available_statistics")
mcp.tool(describe_statistic_tool, name="describe_statistic")
mcp.tool(normalize_ensemble_tool, name="normalize_ensemble")
mcp.tool(list_normalize_strategies_tool, name="list_normalize_strategies")


def main() -> None:
    """Console entry point: ``tmelandscape-mcp``. Defaults to stdio transport."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
