"""``tmelandscape statistics`` — discover available spatial statistics.

Surfaces the same catalogue as the MCP discovery tools so human users can
explore the panel before composing a ``SummarizeConfig``.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from tmelandscape.summarize.registry import describe_metric, list_available_statistics

app = typer.Typer(
    name="statistics",
    help="Inspect the spatial-statistic catalogue.",
    no_args_is_help=True,
)


@app.command("list")
def list_cmd(
    category: Annotated[
        str | None,
        typer.Option("--category", help="Filter to one category (e.g. 'population')."),
    ] = None,
) -> None:
    """List every available statistic with name, category, and description."""
    catalogue = list_available_statistics()
    if category is not None:
        catalogue = [m for m in catalogue if m["category"] == category]
    typer.echo(json.dumps(catalogue, indent=2))


@app.command("describe")
def describe_cmd(name: Annotated[str, typer.Argument(help="Metric name.")]) -> None:
    """Print the full description of one metric (parameters, category, etc.)."""
    typer.echo(json.dumps(describe_metric(name), indent=2))
