"""``tmelandscape embed-strategies`` — discover available embedding strategies.

Mirrors the ``tmelandscape normalize-strategies`` discovery pattern. v0.5.0
ships ``sliding_window`` (the reference algorithm) plus ``identity`` as a
passthrough baseline. Future strategies in ``alternatives.py`` join the
catalogue here.
"""

from __future__ import annotations

import json

import typer

app = typer.Typer(
    name="embed-strategies",
    help="Inspect available embedding strategies.",
    no_args_is_help=True,
)


def _catalogue() -> list[dict[str, str]]:
    return [
        {
            "name": "sliding_window",
            "description": (
                "Per-simulation sliding window of length `window_size` (step 1 "
                "by default), flattening each window's `(window_size, n_stat)` "
                "submatrix into a row vector. Reference oracle: "
                "reference/utils.py::window_trajectory_data."
            ),
            "module": "tmelandscape.embedding.sliding_window",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough strategy: returns the input unchanged. Useful as "
                "a baseline / for diagnosing orchestrator plumbing."
            ),
            "module": "tmelandscape.embedding.alternatives",
        },
    ]


@app.command("list")
def list_cmd() -> None:
    """List available embedding strategies (name + description)."""
    typer.echo(json.dumps(_catalogue(), indent=2))
