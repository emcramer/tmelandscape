"""Per-simulation driver around ``spatialtissuepy``.

Adapter between an on-disk PhysiCell output directory (produced by step 2)
and the long-form summary DataFrame consumed by the ensemble aggregator
(Stream B). Intentionally thin: all metric dispatch lives in
:mod:`tmelandscape.summarize.registry`; this module handles I/O,
per-timepoint orchestration, and DataFrame assembly.

Public API
----------
:func:`summarize_simulation` — load one PhysiCell output directory, compute
every statistic listed in :class:`SummarizeConfig.statistics`, and return a
long-form ``pandas.DataFrame`` with columns
``(time_index, time, statistic, value)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.summarize.registry import compute_panel

# Public column schema for the long-form per-simulation summary DataFrame.
# Pinned here so both this driver and Stream B's aggregator agree on names
# and order. Renames are breaking changes for Stream B.
SUMMARY_COLUMNS: tuple[str, ...] = ("time_index", "time", "statistic", "value")


def summarize_simulation(
    physicell_dir: Path,
    *,
    config: SummarizeConfig,
) -> pd.DataFrame:
    """Run ``spatialtissuepy`` over one PhysiCell output directory.

    Loads every ``outputNNNNNNNN.xml`` / ``..._cells_physicell.mat`` pair in
    ``physicell_dir`` and delegates each statistic in ``config.statistics``
    to :func:`tmelandscape.summarize.registry.compute_panel`.

    Parameters
    ----------
    physicell_dir
        Directory containing one simulation's PhysiCell output.
    config
        :class:`SummarizeConfig` selecting the metric panel.

    Returns
    -------
    pandas.DataFrame
        Long-form table with columns ``(time_index, time, statistic, value)``.
        Timepoints with zero (visible) cells emit no rows; the aggregator
        NaN-fills missing entries from the per-simulation union schema.

    Raises
    ------
    FileNotFoundError
        If ``physicell_dir`` does not exist or contains no PhysiCell output.
    ImportError
        If ``spatialtissuepy`` is not importable.
    """
    try:
        from spatialtissuepy.synthetic import PhysiCellSimulation
    except ImportError as exc:  # pragma: no cover - exercised by integration tests
        raise ImportError(
            "summarize_simulation requires `spatialtissuepy`. Install it via "
            "`uv sync --all-extras` and retry."
        ) from exc

    physicell_dir = Path(physicell_dir)
    if not physicell_dir.exists():
        raise FileNotFoundError(f"PhysiCell output directory does not exist: {physicell_dir}")

    sim = PhysiCellSimulation.from_output_folder(
        physicell_dir,
        include_dead_cells=config.include_dead_cells,
    )

    rows: list[dict[str, Any]] = []
    for ts_idx in range(int(sim.n_timesteps)):
        timestep = sim.get_timestep(ts_idx)
        time_index = int(timestep.time_index)
        time_value = float(timestep.time)

        if int(timestep.n_cells) == 0:
            # `SpatialTissueData` rejects empty coordinates; the aggregator's
            # NaN fill handles the gap for any non-`cell_counts` metric. We
            # still emit the cell-count rows because they remain well-defined.
            entries = _empty_timepoint_rows(config)
        else:
            spatial_data = timestep.to_spatial_data()
            try:
                entries = compute_panel(spatial_data=spatial_data, config=config)
            except Exception:
                # spatialtissuepy raises a variety of errors at this layer
                # (disconnected graphs, missing parameters, etc.). We swallow
                # the failure and emit no rows so a single bad timepoint
                # doesn't poison the whole ensemble run. Upstream test runs
                # surface the original error.
                entries = {}

        for key, value in entries.items():
            rows.append(
                {
                    "time_index": time_index,
                    "time": time_value,
                    "statistic": key,
                    "value": float(value),
                }
            )

    if not rows:
        return pd.DataFrame(
            {
                "time_index": pd.Series([], dtype="int64"),
                "time": pd.Series([], dtype="float64"),
                "statistic": pd.Series([], dtype="object"),
                "value": pd.Series([], dtype="float64"),
            },
            columns=list(SUMMARY_COLUMNS),
        )

    df = pd.DataFrame(rows, columns=list(SUMMARY_COLUMNS))
    return df.astype(
        {
            "time_index": "int64",
            "time": "float64",
            "statistic": "object",
            "value": "float64",
        }
    )


def _empty_timepoint_rows(config: SummarizeConfig) -> dict[str, float]:
    """Emit only the rows that are well-defined when there are zero cells.

    ``cell_counts`` is well-defined: there are 0 cells. Every other metric
    is meaningless without cells, so we emit nothing — Stream B's aggregator
    NaN-fills the missing entries against the union schema across sims.
    """
    if any(spec.name == "cell_counts" for spec in config.statistics):
        return {"n_cells": 0.0}
    return {}


__all__ = ["SUMMARY_COLUMNS", "summarize_simulation"]
