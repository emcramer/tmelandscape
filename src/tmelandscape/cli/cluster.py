"""``tmelandscape cluster`` — Step 5 two-stage Leiden + Ward clustering CLI verb.

Reads a windowed-embedding Zarr (the artefact from ``tmelandscape embed``) plus
a ``ClusterConfig`` JSON, writes a NEW Zarr at the user-specified output path
containing the per-window cluster labels (both Leiden and final), the
per-Leiden-cluster mean embedding vectors, the Ward linkage matrix, and (when
auto-selection was used) the per-candidate metric scores. The input store is
never overwritten.

See [ADR 0007](../../docs/adr/0007-two-stage-leiden-ward-clustering.md) for the
two-stage algorithm rationale and [ADR 0010](../../docs/adr/0010-cluster-count-auto-selection.md)
for the auto-selection policy (``n_final_clusters`` has no silent default).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from tmelandscape.cluster import cluster_ensemble
from tmelandscape.config.cluster import ClusterConfig


def cluster(
    input_zarr: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Path to the input ensemble Zarr (from `tmelandscape embed`).",
        ),
    ],
    output_zarr: Annotated[
        Path,
        typer.Argument(
            help=(
                "Path of the NEW Zarr store to write. Must not already "
                "exist — the orchestrator refuses to overwrite by design."
            ),
        ),
    ],
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help=(
                "JSON file holding a ClusterConfig. `n_final_clusters` may be "
                "omitted (null / absent) to trigger auto-selection via "
                "`cluster_count_metric` (default: WSS elbow)."
            ),
        ),
    ],
) -> None:
    """Run step 5: two-stage Leiden + Ward clustering of the embedding Zarr."""
    cfg = ClusterConfig.model_validate_json(config_path.read_text())
    out_path = cluster_ensemble(input_zarr, output_zarr, config=cfg)
    summary = {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "knn_neighbors": cfg.knn_neighbors,
        "leiden_partition": cfg.leiden_partition,
        "leiden_resolution": cfg.leiden_resolution,
        "leiden_seed": cfg.leiden_seed,
        "n_final_clusters": cfg.n_final_clusters,
        "cluster_count_metric": cfg.cluster_count_metric,
        "cluster_count_min": cfg.cluster_count_min,
        "cluster_count_max": cfg.cluster_count_max,
        "source_variable": cfg.source_variable,
        "leiden_labels_variable": cfg.leiden_labels_variable,
        "final_labels_variable": cfg.final_labels_variable,
        "cluster_means_variable": cfg.cluster_means_variable,
        "linkage_variable": cfg.linkage_variable,
        "cluster_count_scores_variable": cfg.cluster_count_scores_variable,
    }
    typer.echo(json.dumps(summary, indent=2))
