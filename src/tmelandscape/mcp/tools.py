"""MCP tools that mirror the public :mod:`tmelandscape` API one-to-one.

Each function here is wrapped as an MCP tool in :mod:`tmelandscape.mcp.server`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tmelandscape.config.sweep import SweepConfig
from tmelandscape.sampling import generate_sweep


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
