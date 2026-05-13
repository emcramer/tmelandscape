"""Step 3 — drive `spatialtissuepy` over an ensemble + aggregate to Zarr.

The public entry point is :func:`summarize_ensemble`, which iterates each row
of a :class:`~tmelandscape.sampling.manifest.SweepManifest`, calls
:func:`~tmelandscape.summarize.spatialtissuepy_driver.summarize_simulation`
for the corresponding PhysiCell output directory, and aggregates the resulting
long-form DataFrames into one chunked Zarr store via
:func:`~tmelandscape.summarize.aggregate.build_ensemble_zarr`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize.aggregate import build_ensemble_zarr
from tmelandscape.summarize.spatialtissuepy_driver import summarize_simulation

__all__ = [
    "SummarizeConfig",
    "build_ensemble_zarr",
    "summarize_ensemble",
    "summarize_simulation",
]


def summarize_ensemble(
    manifest: SweepManifest,
    *,
    physicell_root: str | Path,
    output_zarr: str | Path,
    config: SummarizeConfig | None = None,
    chunk_simulations: int = 32,
    chunk_timepoints: int = -1,
    chunk_statistics: int = -1,
) -> Path:
    """Run spatialtissuepy across every row of the manifest, write a Zarr ensemble.

    Parameters
    ----------
    manifest
        Sweep manifest produced by :func:`tmelandscape.sampling.generate_sweep`.
        Each row's ``simulation_id`` is interpreted as a subdirectory name under
        ``physicell_root``.
    physicell_root
        Parent directory containing one PhysiCell output subdirectory per
        manifest row. The subdirectory's name must match ``row.simulation_id``.
    output_zarr
        Path of the Zarr store to write. Created if missing.
    config
        :class:`SummarizeConfig` selecting which statistics to compute. Default
        is the LCSS-paper panel.
    chunk_simulations, chunk_timepoints, chunk_statistics
        Per-axis Zarr chunk size. ``-1`` means "one chunk for the whole axis".

    Returns
    -------
    pathlib.Path
        Absolute path of the written Zarr store.
    """
    cfg = config if config is not None else SummarizeConfig()
    root = Path(physicell_root).resolve()
    summary_frames: dict[str, pd.DataFrame] = {}
    seen_sim_ids: set[str] = set()
    for row in manifest.rows:
        if row.simulation_id in seen_sim_ids:
            continue
        seen_sim_ids.add(row.simulation_id)
        sim_dir = root / row.simulation_id
        if not sim_dir.is_dir():
            raise FileNotFoundError(
                f"simulation directory missing: {sim_dir} "
                f"(referenced by manifest row {row.simulation_id!r})"
            )
        summary_frames[row.simulation_id] = summarize_simulation(sim_dir, config=cfg)
    return build_ensemble_zarr(
        manifest,
        summary_frames,
        output_zarr,
        chunk_simulations=chunk_simulations,
        chunk_timepoints=chunk_timepoints,
        chunk_statistics=chunk_statistics,
        config=cfg,
    )
