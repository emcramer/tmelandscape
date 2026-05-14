"""fastmcp server exposing tmelandscape's public API as MCP tools.

Pipeline-step tools land here phase-by-phase. v0.0.1 (Phase 0) only registers
``ping`` so the server boots and integration tests can verify the transport.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from tmelandscape import __version__
from tmelandscape.mcp.tools import (
    cluster_ensemble_tool,
    describe_statistic_tool,
    embed_ensemble_tool,
    generate_sweep_tool,
    list_available_statistics_tool,
    list_cluster_strategies_tool,
    list_embed_strategies_tool,
    list_normalize_strategies_tool,
    list_viz_figures_tool,
    normalize_ensemble_tool,
    plot_attractor_basins_tool,
    plot_feature_umap_tool,
    plot_model_schematic_tool,
    plot_parameter_by_state_tool,
    plot_phase_space_vector_field_tool,
    plot_state_feature_clustermap_tool,
    plot_state_umap_tool,
    plot_state_umap_with_vector_field_tool,
    plot_time_umap_tool,
    plot_trajectory_clustergram_tool,
    plot_trajectory_umap_tool,
    summarize_ensemble_tool,
)

mcp: FastMCP = FastMCP(
    name="tmelandscape",
    instructions=(
        "Tumor microenvironment state-landscape generation. "
        "Pipeline tools: generate_sweep (step 1 — parameter sampling + IC "
        "replicate generation), summarize_ensemble (step 3 — spatialtissuepy "
        "summarisation), normalize_ensemble (step 3.5 — within-timestep "
        "normalisation), embed_ensemble (step 4 — sliding-window embedding), "
        "cluster_ensemble (step 5 — two-stage Leiden + Ward clustering). "
        "Visualisation tools (step 6 — Phase 6): plot_state_umap, "
        "plot_time_umap, plot_feature_umap, plot_trajectory_umap, "
        "plot_state_umap_with_vector_field, plot_state_feature_clustermap, "
        "plot_trajectory_clustergram, plot_phase_space_vector_field, "
        "plot_parameter_by_state, plot_attractor_basins, plot_model_schematic. "
        "Each viz tool "
        "requires a `save_path` argument and returns the resolved path of "
        "the rendered PNG. Discovery: list_available_statistics, "
        "list_normalize_strategies, list_embed_strategies, "
        "list_cluster_strategies, list_viz_figures."
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
mcp.tool(embed_ensemble_tool, name="embed_ensemble")
mcp.tool(list_embed_strategies_tool, name="list_embed_strategies")
mcp.tool(cluster_ensemble_tool, name="cluster_ensemble")
mcp.tool(list_cluster_strategies_tool, name="list_cluster_strategies")

# Phase 6 — visualisation tools. One MCP tool per figure-producing
# function. Each requires `save_path` (MCP cannot return Figure objects)
# and returns the resolved path of the rendered PNG plus a small summary.
mcp.tool(plot_state_umap_tool, name="plot_state_umap")
mcp.tool(plot_time_umap_tool, name="plot_time_umap")
mcp.tool(plot_feature_umap_tool, name="plot_feature_umap")
mcp.tool(plot_trajectory_umap_tool, name="plot_trajectory_umap")
mcp.tool(plot_state_umap_with_vector_field_tool, name="plot_state_umap_with_vector_field")
mcp.tool(plot_state_feature_clustermap_tool, name="plot_state_feature_clustermap")
mcp.tool(plot_trajectory_clustergram_tool, name="plot_trajectory_clustergram")
mcp.tool(plot_phase_space_vector_field_tool, name="plot_phase_space_vector_field")
mcp.tool(plot_parameter_by_state_tool, name="plot_parameter_by_state")
mcp.tool(plot_attractor_basins_tool, name="plot_attractor_basins")
mcp.tool(plot_model_schematic_tool, name="plot_model_schematic")
mcp.tool(list_viz_figures_tool, name="list_viz_figures")


def main() -> None:
    """Console entry point: ``tmelandscape-mcp``. Defaults to stdio transport."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
