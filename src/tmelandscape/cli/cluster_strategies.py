"""``tmelandscape cluster-strategies`` — discover available clustering strategies.

Mirrors the ``tmelandscape embed-strategies`` / ``normalize-strategies``
discovery pattern. v0.6.0 ships ``leiden_ward`` (the reference algorithm) plus
``identity`` as a passthrough baseline. Future strategies in
``cluster/alternatives.py`` join the catalogue here.
"""

from __future__ import annotations

import json

import typer

app = typer.Typer(
    name="cluster-strategies",
    help="Inspect available clustering strategies.",
    no_args_is_help=True,
)


def _catalogue() -> list[dict[str, str]]:
    return [
        {
            "name": "leiden_ward",
            "description": (
                "Two-stage clustering: Leiden community detection on a kNN "
                "graph over the embedding (Stage 1), then Ward hierarchical "
                "clustering on the per-Leiden-community mean embedding "
                "vectors (Stage 2). The dendrogram is cut at "
                "`n_final_clusters` if supplied; otherwise auto-selected via "
                "`cluster_count_metric` (default: WSS elbow). Reference "
                "oracle: reference/01_abm_generate_embedding.py lines "
                "~519-720. See ADR 0007 and ADR 0010."
            ),
            "module": "tmelandscape.cluster.leiden_ward",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough baseline: assigns every row to cluster 0. "
                "Useful for diagnosing orchestrator plumbing or as a "
                "no-op anchor in tests."
            ),
            "module": "tmelandscape.cluster.alternatives",
        },
    ]


@app.command("list")
def list_cmd() -> None:
    """List available clustering strategies (name + description)."""
    typer.echo(json.dumps(_catalogue(), indent=2))
