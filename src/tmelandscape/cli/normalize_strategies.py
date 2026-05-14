"""``tmelandscape normalize-strategies`` — discover available normalisation strategies.

Mirrors the ``tmelandscape statistics list`` discovery pattern for the
summarisation panel. v0.4.0 ships only ``within_timestep``; the listing
shape is set up so future strategies in ``alternatives.py`` can join the
catalogue without a breaking CLI change.
"""

from __future__ import annotations

import json

import typer

app = typer.Typer(
    name="normalize-strategies",
    help="Inspect available normalisation strategies.",
    no_args_is_help=True,
)


def _catalogue() -> list[dict[str, str]]:
    """Return the strategy catalogue.

    Hard-coded for now because the set of strategies is closed (only those
    implemented in ``tmelandscape.normalize``). Future additions to
    ``alternatives.py`` should be added here in lockstep.
    """
    return [
        {
            "name": "within_timestep",
            "description": (
                "Per-timestep Yeo-Johnson + z-score, optionally re-adding "
                "the pre-transform per-step mean to preserve temporal trend. "
                "Reference oracle: reference/00_abm_normalization.py."
            ),
            "module": "tmelandscape.normalize.within_timestep",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough strategy: returns the input unchanged. Useful "
                "as a baseline / for diagnosing orchestrator plumbing."
            ),
            "module": "tmelandscape.normalize.alternatives",
        },
    ]


@app.command("list")
def list_cmd() -> None:
    """List available normalisation strategies (name + description)."""
    typer.echo(json.dumps(_catalogue(), indent=2))
