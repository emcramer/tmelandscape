"""MCP tools that mirror the public :mod:`tmelandscape` API one-to-one.

Each function here is wrapped as an MCP tool in :mod:`tmelandscape.mcp.server`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.config.sweep import SweepConfig
from tmelandscape.sampling import generate_sweep
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize import summarize_ensemble


def generate_sweep_tool(
    config: dict[str, Any],
    *,
    initial_conditions_dir: str,
    manifest_out: str,
    target_n_cells: int = 500,
    similarity_tolerance: float = 0.10,
) -> dict[str, Any]:
    """Generate a parameter-sweep manifest (step 1 of the pipeline).

    Parameters
    ----------
    config
        Serialised :class:`tmelandscape.config.sweep.SweepConfig` (JSON-like dict).
    initial_conditions_dir
        Directory to write initial-condition CSVs into. Created if missing.
    manifest_out
        Output manifest stem; ``.json`` and ``.parquet`` siblings are written.
    target_n_cells
        Soft target for cell count per replicate.
    similarity_tolerance
        Per-metric divergence tolerance between replicates (default 0.10 = 10%).

    Returns
    -------
    dict
        Summary including absolute paths of the written artefacts and row counts.
    """
    sweep_cfg = SweepConfig.model_validate(config)
    manifest = generate_sweep(
        sweep_cfg,
        initial_conditions_dir=initial_conditions_dir,
        target_n_cells=target_n_cells,
        similarity_tolerance=similarity_tolerance,
    )
    manifest.save(manifest_out)
    return {
        "manifest_json": str(Path(f"{manifest_out}.json").resolve()),
        "manifest_parquet": str(Path(f"{manifest_out}.parquet").resolve()),
        "initial_conditions_dir": manifest.initial_conditions_dir,
        "n_rows": len(manifest.rows),
        "n_parameter_combinations": sweep_cfg.n_parameter_samples,
        "n_initial_conditions": sweep_cfg.n_initial_conditions,
    }


def summarize_ensemble_tool(
    manifest_path: str,
    *,
    physicell_root: str,
    output_zarr: str,
    summarize_config: dict[str, Any] | None = None,
    chunk_simulations: int = 32,
    chunk_timepoints: int = -1,
    chunk_statistics: int = -1,
) -> dict[str, Any]:
    """Run step 3: spatialtissuepy summarisation + ensemble Zarr aggregation.

    Parameters
    ----------
    manifest_path
        Path to a SweepManifest JSON (the artefact emitted by ``generate_sweep``).
    physicell_root
        Directory containing one PhysiCell output subdirectory per manifest row.
        The subdirectory name must match ``row.simulation_id``.
    output_zarr
        Path of the Zarr store to write.
    summarize_config
        Optional serialised :class:`SummarizeConfig` dict. Defaults to the
        LCSS-paper panel.
    chunk_simulations, chunk_timepoints, chunk_statistics
        Per-axis Zarr chunk size; ``-1`` means "one chunk for the whole axis".

    Returns
    -------
    dict
        Summary with the Zarr path and the panel that was applied.
    """
    manifest = SweepManifest.load(manifest_path)
    cfg = (
        SummarizeConfig.model_validate(summarize_config) if summarize_config else SummarizeConfig()
    )
    zarr_path = summarize_ensemble(
        manifest,
        physicell_root=physicell_root,
        output_zarr=output_zarr,
        config=cfg,
        chunk_simulations=chunk_simulations,
        chunk_timepoints=chunk_timepoints,
        chunk_statistics=chunk_statistics,
    )
    return {
        "zarr_path": str(zarr_path),
        "n_simulations": len({row.simulation_id for row in manifest.rows}),
        "statistics": list(cfg.statistics),
    }
