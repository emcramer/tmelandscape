"""``tmelandscape sample`` — generate a parameter sweep manifest.

Reads a :class:`SweepConfig` from a JSON file and writes a
:class:`SweepManifest` to disk along with the generated initial-condition CSVs.
All IC-generation knobs (``ic_source``, ``ic_scaffold_strategy``,
``ic_sa_params``, ``ic_network_mode``, ``ic_network_radius_um``) live on the
JSON config — this command has no per-flag overrides for them by design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from tmelandscape.config.sweep import SweepConfig
from tmelandscape.sampling import generate_sweep


def sample(
    config_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a JSON SweepConfig file.",
        ),
    ],
    manifest_out: Annotated[
        Path,
        typer.Option(
            "--manifest-out",
            "-m",
            help="Output manifest stem (creates <stem>.json and <stem>.parquet).",
        ),
    ] = Path("sweep_manifest"),
    initial_conditions_dir: Annotated[
        Path,
        typer.Option(
            "--ic-dir",
            "-i",
            help="Directory to write initial-condition CSVs into.",
        ),
    ] = Path("initial_conditions"),
) -> None:
    """Run step 1: parameter sampling + IC replicate generation."""
    config = SweepConfig.model_validate_json(config_path.read_text())
    manifest = generate_sweep(
        config,
        initial_conditions_dir=initial_conditions_dir,
    )
    manifest.save(manifest_out)
    summary = {
        "manifest_json": str(Path(f"{manifest_out}.json").resolve()),
        "manifest_parquet": str(Path(f"{manifest_out}.parquet").resolve()),
        "initial_conditions_dir": manifest.initial_conditions_dir,
        "n_rows": len(manifest.rows),
        "n_parameter_combinations": config.n_parameter_samples,
        "n_initial_conditions": config.n_initial_conditions,
    }
    typer.echo(json.dumps(summary, indent=2))
