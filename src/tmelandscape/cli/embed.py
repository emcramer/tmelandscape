"""``tmelandscape embed`` — Step 4 sliding-window embedding CLI verb.

Reads a normalised ensemble Zarr (the artefact from ``tmelandscape normalize``)
plus an ``EmbeddingConfig`` JSON, writes a NEW Zarr at the user-specified
output path containing the flattened embedding array and per-window
metadata. The input store is never overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from tmelandscape.config.embedding import EmbeddingConfig
from tmelandscape.embedding import embed_ensemble


def embed(
    input_zarr: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Path to the input ensemble Zarr (from `tmelandscape normalize`).",
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
            help="JSON file holding an EmbeddingConfig (window_size is required).",
        ),
    ],
) -> None:
    """Run step 4: sliding-window embedding of the normalised ensemble Zarr."""
    cfg = EmbeddingConfig.model_validate_json(config_path.read_text())
    out_path = embed_ensemble(input_zarr, output_zarr, config=cfg)
    summary = {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "window_size": cfg.window_size,
        "step_size": cfg.step_size,
        "source_variable": cfg.source_variable,
        "output_variable": cfg.output_variable,
        "averages_variable": cfg.averages_variable,
        "drop_statistics": list(cfg.drop_statistics),
    }
    typer.echo(json.dumps(summary, indent=2))
