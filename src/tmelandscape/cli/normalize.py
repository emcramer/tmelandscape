"""``tmelandscape normalize`` — Step 3.5 normalisation CLI verb.

Reads an input ensemble Zarr (the artefact from ``tmelandscape summarize``)
plus a ``NormalizeConfig`` JSON, writes a NEW Zarr at the user-specified
output path containing both the raw ``value`` array and the new
``value_normalized`` array. The input store is never overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from tmelandscape.config.normalize import NormalizeConfig
from tmelandscape.normalize import normalize_ensemble


def normalize(
    input_zarr: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Path to the input ensemble Zarr (from `tmelandscape summarize`).",
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
            help="JSON file holding a NormalizeConfig.",
        ),
    ],
) -> None:
    """Run step 3.5: within-timestep normalisation of the ensemble Zarr."""
    cfg = NormalizeConfig.model_validate_json(config_path.read_text())
    out_path = normalize_ensemble(input_zarr, output_zarr, config=cfg)
    summary = {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "preserve_time_effect": cfg.preserve_time_effect,
        "drop_columns": list(cfg.drop_columns),
        "output_variable": cfg.output_variable,
    }
    typer.echo(json.dumps(summary, indent=2))
