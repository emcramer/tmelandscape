"""``tmelandscape viz-figures`` — discover available Phase-6 figure tools.

Per-figure CLI verbs (``tmelandscape viz lcss-3 …``) were judged not worth
the surface area for v0.7.0 — eleven verbs in a single namespace would
overwhelm ``--help``, and the figure functions are Python-API-first
anyway. Agents reach the figures via the MCP tools; humans reach them
via the Python API or via this discovery verb to look up the available
tool names. See [`tasks/07-visualisation-implementation.md`](../../tasks/07-visualisation-implementation.md)
for the rationale (the "MCP surface" section).
"""

from __future__ import annotations

import json

import typer

from tmelandscape.mcp.tools import list_viz_figures_tool

app = typer.Typer(
    name="viz-figures",
    help="Inspect available Phase-6 figure-producing tools.",
    no_args_is_help=True,
)


@app.command("list")
def list_cmd() -> None:
    """List available figure tools (tool name + manuscript citation +
    one-line description). Each entry corresponds to an MCP tool of the
    same name plus a Python-API function under ``tmelandscape.viz.*``."""
    typer.echo(json.dumps(list_viz_figures_tool(), indent=2))
