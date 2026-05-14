"""tmelandscape CLI root.

Pipeline-step verbs (``sample``, ``summarize``, ``embed``, ``fit``, ``viz``) land
here phase-by-phase. v0.0.1 (Phase 0) only exposes ``version``.
"""

from __future__ import annotations

import typer

from tmelandscape import __version__
from tmelandscape.cli.normalize import normalize
from tmelandscape.cli.normalize_strategies import app as normalize_strategies_app
from tmelandscape.cli.sample import sample
from tmelandscape.cli.statistics import app as statistics_app
from tmelandscape.cli.summarize import summarize

app = typer.Typer(
    name="tmelandscape",
    help="Generate tumor microenvironment state landscapes from ABM ensembles.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Root callback. Forces Typer to register subcommands explicitly."""


@app.command()
def version() -> None:
    """Print the tmelandscape version."""
    typer.echo(__version__)


app.command(name="sample")(sample)
app.command(name="summarize")(summarize)
app.command(name="normalize")(normalize)
app.add_typer(statistics_app, name="statistics")
app.add_typer(normalize_strategies_app, name="normalize-strategies")


if __name__ == "__main__":  # pragma: no cover
    app()
