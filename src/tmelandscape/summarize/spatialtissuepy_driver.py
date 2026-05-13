"""Per-simulation driver around ``spatialtissuepy``.

This is the adapter between the on-disk PhysiCell output produced by step 2
of the pipeline and the long-form summary DataFrame consumed by the
ensemble aggregator (Stream B). It is intentionally thin: anything that
touches the ``spatialtissuepy`` API surface lives in
``tmelandscape.summarize.registry``; this module only handles I/O,
per-timepoint orchestration, and DataFrame assembly.

Public API
----------
:func:`summarize_simulation` — load one PhysiCell output directory, compute
every statistic listed in :class:`SummarizeConfig.statistics`, and return a
long-form ``pandas.DataFrame`` with columns
``(time_index, time, statistic, value)``.

The DataFrame is "long-form" so that matrix-valued statistics
(``interaction_strength_matrix``) compose naturally with scalar ones: each
matrix entry becomes its own row keyed ``interaction_<src>_<dst>``. Stream
B pivots this representation into the ``(simulation, timepoint, statistic)``
Zarr store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.summarize.registry import compute_statistic

# Public column schema for the long-form per-simulation summary DataFrame.
# Pinned here so both this driver and Stream B's aggregator agree on names
# and column order. The aggregator pivots on ``(time_index, statistic)`` so
# any name change here is a breaking change there.
SUMMARY_COLUMNS: tuple[str, ...] = ("time_index", "time", "statistic", "value")


def summarize_simulation(
    physicell_dir: Path,
    *,
    config: SummarizeConfig,
) -> pd.DataFrame:
    """Run ``spatialtissuepy`` over one PhysiCell output directory.

    Loads every ``outputNNNNNNNN.xml`` / ``..._cells_physicell.mat`` pair in
    ``physicell_dir``, builds the cell graph requested by ``config``, and
    delegates each statistic in ``config.statistics`` to
    :func:`tmelandscape.summarize.registry.compute_statistic`.

    Parameters
    ----------
    physicell_dir:
        Directory containing one simulation's PhysiCell output (i.e. a
        single ``simulation_id`` from the sweep manifest).
    config:
        Frozen :class:`SummarizeConfig`. The ``statistics`` list, graph
        method, radius, and ``include_dead_cells`` flag are honoured;
        ``n_workers`` is irrelevant at this scope (it controls the
        ensemble-level Dask parallelism in Stream B).

    Returns
    -------
    pandas.DataFrame
        Long-form table with columns ``(time_index, time, statistic, value)``.
        Exactly one row per (timepoint, output-statistic) pair. Statistics
        that fail at a given timepoint (e.g. centrality on an empty cell
        list, where the graph has no nodes) emit ``NaN`` values rather than
        raising, so downstream Zarr writes get a well-shaped ``NaN`` mask.

    Raises
    ------
    FileNotFoundError
        If ``physicell_dir`` does not exist or contains no PhysiCell output.
    ImportError
        If ``spatialtissuepy`` (or one of its required submodules) is not
        importable. The error is re-raised verbatim with a hint pointing at
        the project install instructions.

    Notes
    -----
    Per AGENTS.md house-style invariant #6 ("no silent network IO inside
    library code") this function never reaches off-machine — all data is
    read from ``physicell_dir``.
    """
    # Lazy import: keep ``tmelandscape.summarize`` importable on machines
    # where the optional ``spatialtissuepy[network]`` extras are absent.
    # The registry does its own lazy imports for the actual statistic
    # computations; here we only need the high-level loader + graph builder.
    try:
        from spatialtissuepy.core import SpatialTissueData
        from spatialtissuepy.network import CellGraph
        from spatialtissuepy.synthetic import PhysiCellSimulation
    except ImportError as exc:  # pragma: no cover - exercised by integration tests
        raise ImportError(
            "summarize_simulation requires the optional 'spatialtissuepy[network]' "
            "dependency. Install it via `uv sync --all-extras` and retry."
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

        spatial_data, graph = _prepare_timepoint(
            timestep=timestep,
            spatial_tissue_data_cls=SpatialTissueData,
            cell_graph_cls=CellGraph,
            config=config,
        )

        for statistic_name in config.statistics:
            entries = _compute_or_nan(
                statistic_name=statistic_name,
                spatial_data=spatial_data,
                graph=graph,
                n_alive_cells=int(timestep.n_cells),
                config=config,
            )
            for key, value in entries.items():
                rows.append(
                    {
                        "time_index": time_index,
                        "time": time_value,
                        "statistic": key,
                        "value": float(value),
                    }
                )

    # ``pd.DataFrame`` infers an ``object`` dtype for ``statistic`` when the
    # table is empty; force dtypes via the constructor so the schema matches
    # the non-empty case (Stream B relies on this).
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
    df = df.astype(
        {
            "time_index": "int64",
            "time": "float64",
            "statistic": "object",
            "value": "float64",
        }
    )
    return df


def _prepare_timepoint(
    *,
    timestep: Any,
    spatial_tissue_data_cls: type[Any],
    cell_graph_cls: type[Any],
    config: SummarizeConfig,
) -> tuple[Any | None, Any | None]:
    """Build ``(SpatialTissueData | None, CellGraph | None)`` for one timepoint.

    Returns ``(None, None)`` for timepoints with zero (visible) cells:
    ``spatialtissuepy.core.SpatialTissueData`` raises ``ValidationError``
    on empty coordinates, so we cannot even construct it. Returns
    ``(data, None)`` for the rare case of a non-empty data object that
    nevertheless can't form a graph (e.g. all cells share one position).

    ``spatial_tissue_data_cls`` and ``cell_graph_cls`` are injected (rather
    than imported here) so the top-level function performs all
    ``spatialtissuepy`` imports inside a single ``try/except`` — keeping the
    import-error message in one place.
    """
    if int(timestep.n_cells) == 0:
        return None, None

    spatial_data = spatial_tissue_data_cls(
        coordinates=timestep.positions,
        cell_types=timestep.to_dataframe()["cell_type"].to_numpy()
        if config.include_dead_cells
        else _alive_cell_types(timestep),
    )

    graph = cell_graph_cls.from_spatial_data(
        spatial_data,
        method=config.graph_method,
        radius=config.graph_radius_um,
    )
    return spatial_data, graph


def _alive_cell_types(timestep: Any) -> Any:
    """Return cell-type labels for the alive subset of a PhysiCell timestep.

    ``PhysiCellTimeStep.positions`` already applies the alive filter when
    ``include_dead_cells=False``, but the upstream class doesn't expose a
    matching property for ``cell_types``. We replicate the filter here to
    keep the two arrays aligned.
    """
    df = timestep.to_dataframe()
    alive_df = df[~df["is_dead"]]
    return alive_df["cell_type"].to_numpy()


def _compute_or_nan(
    *,
    statistic_name: str,
    spatial_data: Any | None,
    graph: Any | None,
    n_alive_cells: int,
    config: SummarizeConfig,
) -> dict[str, float]:
    """Compute one statistic, returning ``{name: NaN}`` on graceful failures.

    "Graceful failures" cover three cases:

    1. ``spatial_data`` is ``None`` — the timepoint had zero visible cells
       and we couldn't even construct a ``SpatialTissueData``.

       For ``cell_counts`` we synthesise a coherent ``n_cells=0`` row
       (population statistics are well-defined on the empty population);
       for ``cell_type_fractions`` we emit nothing (no types means no
       keys); everything else emits a single NaN placeholder so the
       long-form schema stays well-shaped.

    2. The graph is ``None`` and the statistic needs a graph. We emit a
       single NaN placeholder row keyed by the input statistic name so the
       long-form schema stays well-shaped.

    3. ``spatialtissuepy`` raises (e.g. ``RuntimeError`` for a disconnected
       graph in ``closeness_centrality``). We catch ``Exception`` here on
       purpose: this is the boundary between user code and a third-party
       library whose error taxonomy we don't fully control, and the
       alternative is a single bad cell killing an entire ensemble run.
    """
    if spatial_data is None:
        # Zero-cell timepoint. ``cell_counts`` is still well-defined.
        if statistic_name == "cell_counts":
            return {"n_cells": float(n_alive_cells)}
        # For every other default statistic, omit rows entirely on empty
        # data. Stream B's Zarr aggregator NaN-fills missing entries when
        # the union schema is built across simulations, so a downstream
        # consumer sees NaN at this (sim, timepoint) cell for whatever
        # the union vocabulary contains — without us polluting the
        # `statistic` coordinate with a one-off `cell_type_fractions`
        # key that disagrees with the non-empty rows' `fraction_<type>`
        # / `interaction_<src>|<dst>` schemas.
        return {}

    needs_graph = statistic_name.startswith("mean_") and statistic_name.endswith(
        "_centrality_by_type"
    )
    if needs_graph and graph is None:
        return {}

    try:
        return compute_statistic(
            statistic_name,
            spatial_data=spatial_data,
            graph=graph,
            config=config,
        )
    except Exception:
        # Broad except is intentional here — see docstring case 3. Return
        # an empty dict (no rows) so we don't pollute the long-form schema
        # with the input statistic name on a failure.
        return {}


__all__ = ["SUMMARY_COLUMNS", "summarize_simulation"]
