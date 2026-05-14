"""Phase 6 prerequisite — sweep-manifest ↔ cluster-Zarr join.

The Phase 5 cluster output stores per-window ``cluster_labels`` plus
per-window coordinates (``simulation_id``, ``window_index_in_sim``, the
sampled ``parameter_<name>`` columns from the Phase 2 manifest broadcast
across windows). Two of the Phase 6 figures — LCSS-6 (parameter-space
attractor basins) and TNBC-6c (one parameter by terminal state) — need a
per-simulation view that puts the sampled parameter vector beside a
single terminal cluster label per sim.

:func:`join_manifest_cluster` provides that view. It opens both stores
lazily and read-only, computes the **mode of the last
``terminal_window_count`` window labels per sim** as the terminal
cluster label, and returns a pandas DataFrame indexed by
``simulation_id``.

Read-only with respect to both inputs (see the binding invariants in
``tasks/07-visualisation-implementation.md``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from tmelandscape.sampling.manifest import SweepManifest


def join_manifest_cluster(
    manifest_path: str | Path,
    cluster_zarr: str | Path,
    *,
    terminal_window_count: int = 5,
) -> pd.DataFrame:
    """Join the Phase 2 sweep manifest with the Phase 5 cluster Zarr.

    Returns a DataFrame indexed by ``simulation_id`` (string) with columns:

    - one column per ``parameter_<name>`` (the sampled parameter vector
      from the manifest — column names carry the ``parameter_`` prefix
      so they match the per-window coord names in the cluster Zarr),
    - ``terminal_cluster_label``: the mode of ``cluster_labels`` over
      the last ``terminal_window_count`` windows of the sim (windows
      ordered by ``window_index_in_sim``),
    - ``n_windows``: total windows for that sim (sanity).

    Parameters
    ----------
    manifest_path
        Path to the Phase 2 sweep-manifest JSON (the ``.json`` suffix is
        optional — :meth:`SweepManifest.load` strips it).
    cluster_zarr
        Path to the Phase 5 cluster Zarr store. Must carry
        ``cluster_labels``, ``simulation_id``, and ``window_index_in_sim``
        per-``window`` arrays.
    terminal_window_count
        Number of trailing windows to aggregate when picking the
        terminal cluster label. Must be ``>= 1``. If a sim has fewer
        windows than this, all of them are used.

    Returns
    -------
    pandas.DataFrame
        Indexed by ``simulation_id``. Order follows the manifest row
        order.

    Raises
    ------
    ValueError
        If ``terminal_window_count < 1``, or if the manifest's sim set
        does not exactly match the cluster Zarr's sim set.
    """
    if terminal_window_count < 1:
        raise ValueError(
            f"terminal_window_count must be >= 1; got {terminal_window_count}. "
            "The terminal label is the mode of the last N window labels; N must be positive."
        )

    manifest = SweepManifest.load(manifest_path)
    manifest_sim_ids = [row.simulation_id for row in manifest.rows]
    manifest_param_names = [p.name for p in manifest.config.parameters]

    cluster_path = Path(cluster_zarr).expanduser().resolve()

    with xr.open_zarr(cluster_path) as ds:
        for required in ("cluster_labels", "simulation_id", "window_index_in_sim"):
            if required not in ds.variables:
                raise ValueError(
                    f"cluster Zarr at {cluster_path!s} is missing required variable {required!r}; "
                    f"available variables: {sorted(ds.variables)}"
                )
        cluster_labels = np.asarray(ds["cluster_labels"].values)
        sim_id_per_window = np.asarray(ds["simulation_id"].values).astype(str)
        win_idx_per_window = np.asarray(ds["window_index_in_sim"].values).astype(np.int64)

    cluster_sim_set = set(sim_id_per_window.tolist())
    manifest_sim_set = set(manifest_sim_ids)
    missing_in_cluster = manifest_sim_set - cluster_sim_set
    missing_in_manifest = cluster_sim_set - manifest_sim_set
    if missing_in_cluster or missing_in_manifest:
        raise ValueError(
            "manifest and cluster Zarr have mismatched simulation_id sets. "
            f"in manifest only: {sorted(missing_in_cluster)}; "
            f"in cluster Zarr only: {sorted(missing_in_manifest)}."
        )

    per_window = pd.DataFrame(
        {
            "simulation_id": sim_id_per_window,
            "window_index_in_sim": win_idx_per_window,
            "cluster_label": cluster_labels,
        }
    )
    per_window = per_window.sort_values(["simulation_id", "window_index_in_sim"])

    terminal_rows: list[dict[str, object]] = []
    for sim_id, group in per_window.groupby("simulation_id", sort=False):
        labels = group["cluster_label"].to_numpy()
        n_windows = int(labels.shape[0])
        tail = labels[-terminal_window_count:]
        terminal_label = pd.Series(tail).mode().iloc[0]
        terminal_rows.append(
            {
                "simulation_id": str(sim_id),
                "terminal_cluster_label": terminal_label,
                "n_windows": n_windows,
            }
        )
    terminal_df = pd.DataFrame(terminal_rows).set_index("simulation_id")

    manifest_records: list[dict[str, object]] = []
    for row in manifest.rows:
        record: dict[str, object] = {"simulation_id": row.simulation_id}
        for name in manifest_param_names:
            record[f"parameter_{name}"] = row.parameter_values.get(name)
        manifest_records.append(record)
    manifest_df = pd.DataFrame(manifest_records).set_index("simulation_id")

    joined = manifest_df.join(terminal_df, how="left")
    return joined


__all__ = ["join_manifest_cluster"]
