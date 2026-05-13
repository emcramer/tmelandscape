"""``tmelandscape summarize`` — drive spatialtissuepy across a sweep, build the ensemble Zarr."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize import summarize_ensemble


def summarize(
    manifest_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a SweepManifest JSON (the artefact from `tmelandscape sample`).",
        ),
    ],
    physicell_root: Annotated[
        Path,
        typer.Option(
            "--physicell-root",
            "-r",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Directory containing one PhysiCell output subdirectory per manifest row.",
        ),
    ],
    output_zarr: Annotated[
        Path,
        typer.Option(
            "--output-zarr",
            "-o",
            help="Path of the Zarr store to write.",
        ),
    ] = Path("ensemble.zarr"),
    summarize_config_path: Annotated[
        Path | None,
        typer.Option(
            "--summarize-config",
            "-c",
            help="Optional JSON file holding a SummarizeConfig. Defaults to the LCSS panel.",
        ),
    ] = None,
    chunk_simulations: Annotated[
        int, typer.Option(help="Zarr chunk size along `simulation`.")
    ] = 32,
    chunk_timepoints: Annotated[
        int, typer.Option(help="Zarr chunk size along `timepoint` (-1 for full axis).")
    ] = -1,
    chunk_statistics: Annotated[
        int, typer.Option(help="Zarr chunk size along `statistic` (-1 for full axis).")
    ] = -1,
) -> None:
    """Run step 3: spatial-statistic summarisation + ensemble Zarr aggregation."""
    manifest = SweepManifest.load(manifest_path)
    config = (
        SummarizeConfig.model_validate_json(summarize_config_path.read_text())
        if summarize_config_path is not None
        else SummarizeConfig()
    )
    zarr_path = summarize_ensemble(
        manifest,
        physicell_root=physicell_root,
        output_zarr=output_zarr,
        config=config,
        chunk_simulations=chunk_simulations,
        chunk_timepoints=chunk_timepoints,
        chunk_statistics=chunk_statistics,
    )
    summary = {
        "zarr_path": str(zarr_path),
        "n_simulations": len({row.simulation_id for row in manifest.rows}),
        "statistics": list(config.statistics),
    }
    typer.echo(json.dumps(summary, indent=2))
