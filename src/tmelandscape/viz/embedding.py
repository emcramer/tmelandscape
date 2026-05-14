"""UMAP-scatter visualisations for the clustered ensemble Zarr (Phase 6, Stream A).

This module ships one fit-once helper plus five figure functions that together
reproduce the UMAP-projection family of figures from the LCSS and TNBC
manuscripts:

* :func:`plot_state_umap` — TNBC Figure 2b. State-coloured scatter.
* :func:`plot_time_umap` — TNBC Figure 2c. Per-window mean time colouring.
* :func:`plot_feature_umap` — LCSS Figure 4 / TNBC Figure 2e. Multi-panel
  per-feature colouring.
* :func:`plot_trajectory_umap` — TNBC Figure 2d. State-coloured background
  with named simulation trajectories overlaid as polylines.
* :func:`plot_state_umap_with_vector_field` — LCSS Figure 3. State-coloured
  scatter, per-state mean-displacement quiver, optional per-state density
  contours.

All functions are read-only with respect to the input Zarr — the store is
opened lazily via :func:`xarray.open_zarr` inside a context manager and
closed before the function returns.

References
----------
* ``reference/01_abm_generate_embedding.py`` lines 158-207 (UMAP fit),
  279-322 (time-coloured scatter), 446-496 (feature-coloured panels),
  850-907 (state-coloured scatter).
* ``reference/02_abm_state_space_analysis.marimo.py`` lines 1176-1234
  (animated trajectory; the static-overlay version here is the same
  underlying group-by-sim polyline construction).
* TNBC manuscript Methods section (lines 880-896) for the per-state
  vector-field methodology.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import matplotlib.figure as mfig
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import umap
import xarray as xr
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
from numpy.typing import NDArray


@dataclass
class UMAPResult:
    """Cached UMAP projection of a windowed-embedding Zarr.

    Persistable; the same :class:`UMAPResult` is reused across every figure
    that overlays on the 2D projection (LCSS-3/4, TNBC-2b/2c/2d/2e).

    Attributes
    ----------
    coordinates
        ``(n_window, 2)`` ``float64`` array of UMAP-projected coordinates,
        one row per window in the input Zarr.
    n_neighbors
        ``n_neighbors`` parameter passed to :class:`umap.UMAP`.
    min_dist
        ``min_dist`` parameter passed to :class:`umap.UMAP`.
    random_state
        ``random_state`` parameter passed to :class:`umap.UMAP`.
    source_input_zarr
        Absolute resolved path of the cluster Zarr the projection was fit
        against (string, not :class:`~pathlib.Path`, so the dataclass is
        trivially JSON-serialisable for a future provenance sidecar).
    """

    coordinates: NDArray[np.float64]
    n_neighbors: int
    min_dist: float
    random_state: int
    source_input_zarr: str


def fit_umap(
    cluster_zarr: str | Path,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> UMAPResult:
    """Fit a 2D UMAP projection of the cluster Zarr's embedding array.

    The Zarr is opened lazily and treated as read-only. The default source
    variable is ``"embedding"``, matching the Phase 5 output contract.

    Parameters
    ----------
    cluster_zarr
        Path to a cluster Zarr produced by
        :func:`tmelandscape.cluster.cluster_ensemble` (or any compatible
        Zarr carrying an ``embedding`` data variable of shape
        ``(n_window, n_feature)``).
    n_neighbors
        ``n_neighbors`` parameter for :class:`umap.UMAP`. Default 15
        (matches the reference oracle).
    min_dist
        ``min_dist`` parameter for :class:`umap.UMAP`. Default 0.1
        (matches the reference oracle).
    random_state
        Determinism anchor for :class:`umap.UMAP`. Default 42.

    Returns
    -------
    UMAPResult
        Dataclass carrying the ``(n_window, 2)`` coordinates plus the
        UMAP hyperparameters and the absolute resolved path of the
        input Zarr.
    """
    input_path = Path(cluster_zarr).expanduser().resolve()
    with xr.open_zarr(input_path) as ds:
        if "embedding" not in ds.data_vars:
            raise ValueError(
                f"cluster Zarr at {input_path!s} has no 'embedding' data variable "
                f"(found: {list(ds.data_vars)}). Pass a Zarr produced by "
                "tmelandscape.cluster.cluster_ensemble (or its upstream embed step)."
            )
        embedding_array = np.asarray(ds["embedding"].values, dtype=np.float64)

    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=2,
        random_state=random_state,
        metric="euclidean",
    )
    coordinates = np.asarray(reducer.fit_transform(embedding_array), dtype=np.float64)

    return UMAPResult(
        coordinates=coordinates,
        n_neighbors=int(n_neighbors),
        min_dist=float(min_dist),
        random_state=int(random_state),
        source_input_zarr=str(input_path),
    )


def plot_state_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    state_palette: dict[int, str] | None = None,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC Figure 2b — state-coloured UMAP scatter.

    Parameters
    ----------
    umap_result
        :class:`UMAPResult` produced by :func:`fit_umap`.
    cluster_zarr
        Path to the cluster Zarr; must contain a ``cluster_labels`` data
        variable of shape ``(n_window,)`` aligned to
        ``umap_result.coordinates``.
    state_palette
        Optional mapping ``{cluster_label: hex_or_named_colour}`` for
        per-state colours. ``None`` defaults to :mod:`matplotlib.cm.tab10`
        for up to 10 states; passing ``None`` with more than 10 distinct
        labels raises :class:`ValueError`.
    save_path
        Optional path to save the figure (``bbox_inches="tight"``,
        ``dpi=150``).

    Returns
    -------
    matplotlib.figure.Figure
        The constructed figure with a single Axes carrying one scatter
        :class:`~matplotlib.collections.PathCollection` per state plus a
        legend.

    Raises
    ------
    ValueError
        If ``state_palette is None`` and the cluster Zarr has more than
        10 distinct cluster labels.
    """
    coords = umap_result.coordinates
    labels = _read_cluster_labels(cluster_zarr, n_expected=coords.shape[0])
    palette = _resolve_state_palette(labels, state_palette)

    fig, ax = plt.subplots(figsize=(5, 5))
    _scatter_states(ax, coords, labels, palette)
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("State-coloured UMAP")
    ax.legend(title="State", loc="best", frameon=False)
    fig.tight_layout()
    _maybe_save(fig, save_path)
    return fig


def plot_time_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC Figure 2c — UMAP coloured by per-window mean time.

    The cluster Zarr's upstream ``time`` coord is two-dimensional
    ``(simulation, timepoint)`` and is intentionally not propagated through
    Phase 4 / Phase 5 (see ``docs/development/STATUS.md`` "Quirks worth
    knowing"). This function uses the 1D ``start_timepoint`` /
    ``end_timepoint`` coords from the cluster Zarr and takes the per-window
    mean ``0.5 * (start + end)`` as the colour value. The result is in
    timepoint-index units, not wall-clock minutes.

    Parameters
    ----------
    umap_result
        :class:`UMAPResult` produced by :func:`fit_umap`.
    cluster_zarr
        Path to the cluster Zarr; must contain ``start_timepoint`` and
        ``end_timepoint`` 1D coords aligned to the ``window`` dim.
    save_path
        Optional path to save the figure.

    Returns
    -------
    matplotlib.figure.Figure
        Figure with a single Axes carrying a colour-mapped scatter and a
        colourbar labelled "mean window timepoint".
    """
    coords = umap_result.coordinates
    mean_time = _read_per_window_mean_time(cluster_zarr, n_expected=coords.shape[0])

    fig, ax = plt.subplots(figsize=(5, 5))
    scat = ax.scatter(
        coords[:, 0],
        coords[:, 1],
        c=mean_time,
        cmap="viridis",
        s=8,
        alpha=0.7,
        edgecolors="none",
    )
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("Time-coloured UMAP")
    fig.colorbar(scat, ax=ax, label="mean window timepoint")
    fig.tight_layout()
    _maybe_save(fig, save_path)
    return fig


def plot_feature_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    features: Sequence[str],
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS Figure 4 / TNBC Figure 2e — multi-panel UMAP coloured by features.

    Each requested feature gets its own panel coloured by the corresponding
    column of the cluster Zarr's ``window_averages`` data variable. Panels
    are laid out in a single row; the caller is free to crop / re-arrange.

    Parameters
    ----------
    umap_result
        :class:`UMAPResult` produced by :func:`fit_umap`.
    cluster_zarr
        Path to the cluster Zarr; must contain a ``window_averages`` data
        variable of shape ``(window, statistic)`` and a ``statistic`` coord
        listing the available feature names.
    features
        Sequence of statistic names to plot. Each must appear in the
        ``statistic`` coord.
    save_path
        Optional path to save the figure.

    Returns
    -------
    matplotlib.figure.Figure
        Figure with ``len(features)`` Axes, one per requested feature.

    Raises
    ------
    ValueError
        If ``features`` is empty, or if any requested name is not present
        in the ``statistic`` coord (the message lists what is available).
    """
    if len(features) == 0:
        raise ValueError("`features` must be a non-empty sequence of statistic names.")

    coords = umap_result.coordinates
    feature_values, feature_names = _read_window_averages(
        cluster_zarr, features=features, n_expected=coords.shape[0]
    )

    fig, axes = plt.subplots(
        nrows=1,
        ncols=len(features),
        figsize=(4 * len(features), 4),
        squeeze=False,
    )
    axes_row = axes[0]
    for idx, name in enumerate(feature_names):
        ax = axes_row[idx]
        scat = ax.scatter(
            coords[:, 0],
            coords[:, 1],
            c=feature_values[:, idx],
            cmap="inferno",
            s=8,
            alpha=0.7,
            edgecolors="none",
        )
        ax.set_xlabel("UMAP 1")
        ax.set_ylabel("UMAP 2")
        ax.set_title(name)
        fig.colorbar(scat, ax=ax, shrink=0.8)
    fig.tight_layout()
    _maybe_save(fig, save_path)
    return fig


def plot_trajectory_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    sim_ids: Sequence[str],
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC Figure 2d — state-coloured UMAP with simulation trajectories overlaid.

    The background is a state-coloured scatter (mirroring
    :func:`plot_state_umap` but slightly dimmer so the trajectory polylines
    pop). Each named simulation is drawn as a polyline through its windows
    sorted by ``window_index_in_sim``.

    Parameters
    ----------
    umap_result
        :class:`UMAPResult` produced by :func:`fit_umap`.
    cluster_zarr
        Path to the cluster Zarr; must contain ``cluster_labels``,
        ``simulation_id``, and ``window_index_in_sim`` coords / variables.
    sim_ids
        Sequence of simulation-id strings to overlay. Every entry must be
        present in the Zarr's ``simulation_id`` coord.
    save_path
        Optional path to save the figure.

    Returns
    -------
    matplotlib.figure.Figure
        Figure with one Axes carrying the background scatter plus one
        :class:`~matplotlib.lines.Line2D` per requested sim.

    Raises
    ------
    ValueError
        If ``sim_ids`` is empty, or if any requested sim id is absent from
        the Zarr.
    """
    if len(sim_ids) == 0:
        raise ValueError("`sim_ids` must be a non-empty sequence of simulation ids.")

    coords = umap_result.coordinates
    labels = _read_cluster_labels(cluster_zarr, n_expected=coords.shape[0])
    sim_id_per_window, window_index_per_window = _read_window_indices(
        cluster_zarr, n_expected=coords.shape[0]
    )

    available = set(sim_id_per_window.tolist())
    missing = [sid for sid in sim_ids if sid not in available]
    if missing:
        raise ValueError(
            f"requested sim_ids not present in cluster Zarr: {missing}. "
            f"Available ids include: {sorted(available)[:10]}"
            f"{'...' if len(available) > 10 else ''}"
        )

    palette = _resolve_state_palette(labels, None)
    fig, ax = plt.subplots(figsize=(5, 5))
    _scatter_states(ax, coords, labels, palette, alpha=0.3, s=6)

    for sid in sim_ids:
        mask = sim_id_per_window == sid
        if not mask.any():
            continue
        order = np.argsort(window_index_per_window[mask])
        path = coords[mask][order]
        ax.plot(
            path[:, 0],
            path[:, 1],
            marker="o",
            markersize=3,
            linewidth=1.2,
            label=f"sim {sid}",
        )

    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("Trajectories on state-coloured UMAP")
    ax.legend(loc="best", frameon=False, fontsize="small")
    fig.tight_layout()
    _maybe_save(fig, save_path)
    return fig


def plot_state_umap_with_vector_field(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    grid_size: int = 20,
    show_density_contours: bool = True,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS Figure 3 — state-coloured UMAP with per-state vector field.

    For each state ``s``, compute the per-window displacement ``Δ_UMAP``
    between consecutive windows of the same simulation that are *both*
    currently in state ``s``. Grid-bin the displacement starts in UMAP
    space and aggregate the mean displacement per cell, then render with
    :func:`matplotlib.axes.Axes.quiver`. When
    ``show_density_contours=True``, overlay a per-state KDE contour via
    :func:`seaborn.kdeplot` so the spatial extent of each state is visible.

    The vector-field recipe is the one described in the TNBC manuscript
    Methods (lines 880-896); the manuscript applied it in
    ``(epithelial_count, T_eff_count)`` phase space, but the same recipe
    works in UMAP space and is what LCSS Figure 3 reports.

    Parameters
    ----------
    umap_result
        :class:`UMAPResult` produced by :func:`fit_umap`.
    cluster_zarr
        Path to the cluster Zarr; must contain ``cluster_labels``,
        ``simulation_id``, and ``window_index_in_sim``.
    grid_size
        Number of bins per UMAP axis for the displacement aggregation.
        Default 20.
    show_density_contours
        When ``True``, overlay per-state KDE contours via
        :func:`seaborn.kdeplot`.
    save_path
        Optional path to save the figure.

    Returns
    -------
    matplotlib.figure.Figure
        Figure with a single Axes carrying the state-coloured scatter, one
        :class:`~matplotlib.quiver.Quiver` per state, and (optionally) per-
        state density contours.
    """
    if grid_size < 2:
        raise ValueError(f"`grid_size` must be >= 2; got {grid_size}")

    coords = umap_result.coordinates
    labels = _read_cluster_labels(cluster_zarr, n_expected=coords.shape[0])
    sim_id_per_window, window_index_per_window = _read_window_indices(
        cluster_zarr, n_expected=coords.shape[0]
    )
    palette = _resolve_state_palette(labels, None)

    fig, ax = plt.subplots(figsize=(6, 6))
    _scatter_states(ax, coords, labels, palette, alpha=0.3, s=6)

    x_min, x_max = float(coords[:, 0].min()), float(coords[:, 0].max())
    y_min, y_max = float(coords[:, 1].min()), float(coords[:, 1].max())
    # Pad the binning extent by a touch so points on the boundary land
    # inside a finite bin rather than being clipped off the right edge.
    x_pad = 0.01 * (x_max - x_min) if x_max > x_min else 1.0
    y_pad = 0.01 * (y_max - y_min) if y_max > y_min else 1.0
    x_edges = np.linspace(x_min - x_pad, x_max + x_pad, grid_size + 1)
    y_edges = np.linspace(y_min - y_pad, y_max + y_pad, grid_size + 1)

    starts, displacements, state_of_step = _per_state_displacements(
        coords, labels, sim_id_per_window, window_index_per_window
    )

    for state in sorted(np.unique(labels).tolist()):
        state_mask = state_of_step == state
        if not state_mask.any():
            continue
        start_xy = starts[state_mask]
        dxy = displacements[state_mask]
        u_grid, v_grid, x_centers, y_centers = _aggregate_quiver_grid(
            start_xy, dxy, x_edges, y_edges
        )
        has_vector = ~np.isnan(u_grid)
        if not has_vector.any():
            continue
        xx, yy = np.meshgrid(x_centers, y_centers, indexing="ij")
        ax.quiver(
            xx[has_vector],
            yy[has_vector],
            u_grid[has_vector],
            v_grid[has_vector],
            color=palette[int(state)],
            angles="xy",
            scale_units="xy",
            scale=1.0,
            width=0.004,
            alpha=0.9,
        )

    if show_density_contours:
        for state in sorted(np.unique(labels).tolist()):
            mask = labels == state
            if mask.sum() < 5:
                continue
            sns.kdeplot(
                x=coords[mask, 0],
                y=coords[mask, 1],
                ax=ax,
                levels=3,
                color=palette[int(state)],
                linewidths=1.0,
                alpha=0.8,
            )

    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("State-coloured UMAP with per-state vector field")
    ax.legend(title="State", loc="best", frameon=False)
    fig.tight_layout()
    _maybe_save(fig, save_path)
    return fig


# --- internals --------------------------------------------------------------


def _read_cluster_labels(cluster_zarr: str | Path, *, n_expected: int) -> NDArray[np.int64]:
    with xr.open_zarr(Path(cluster_zarr).expanduser().resolve()) as ds:
        if "cluster_labels" not in ds.data_vars:
            raise ValueError(
                f"cluster Zarr has no 'cluster_labels' data variable (found: {list(ds.data_vars)})."
            )
        labels = np.asarray(ds["cluster_labels"].values, dtype=np.int64)
    if labels.shape[0] != n_expected:
        raise ValueError(
            f"cluster_labels length {labels.shape[0]} does not match the "
            f"UMAPResult coordinate count {n_expected}; the Zarr and the "
            "UMAPResult appear to be from different sources."
        )
    return labels


def _read_per_window_mean_time(cluster_zarr: str | Path, *, n_expected: int) -> NDArray[np.float64]:
    with xr.open_zarr(Path(cluster_zarr).expanduser().resolve()) as ds:
        if "start_timepoint" not in ds.coords or "end_timepoint" not in ds.coords:
            raise ValueError(
                "cluster Zarr is missing 'start_timepoint' or 'end_timepoint' "
                "coords required by plot_time_umap."
            )
        start = np.asarray(ds["start_timepoint"].values, dtype=np.float64)
        end = np.asarray(ds["end_timepoint"].values, dtype=np.float64)
    if start.shape[0] != n_expected:
        raise ValueError(
            f"start_timepoint length {start.shape[0]} does not match the "
            f"UMAPResult coordinate count {n_expected}."
        )
    return 0.5 * (start + end)


def _read_window_averages(
    cluster_zarr: str | Path,
    *,
    features: Sequence[str],
    n_expected: int,
) -> tuple[NDArray[np.float64], list[str]]:
    with xr.open_zarr(Path(cluster_zarr).expanduser().resolve()) as ds:
        if "window_averages" not in ds.data_vars:
            raise ValueError(
                f"cluster Zarr has no 'window_averages' data variable "
                f"(found: {list(ds.data_vars)})."
            )
        if "statistic" not in ds.coords:
            raise ValueError("cluster Zarr has no 'statistic' coord on 'window_averages'.")
        available = [str(s) for s in ds["statistic"].values.tolist()]
        missing = [name for name in features if name not in available]
        if missing:
            raise ValueError(
                f"requested feature(s) {missing} are not present in the cluster "
                f"Zarr's statistic coord. Available statistics: {available}"
            )
        selected = ds["window_averages"].sel(statistic=list(features))
        values = np.asarray(selected.values, dtype=np.float64)
    if values.shape[0] != n_expected:
        raise ValueError(
            f"window_averages window-axis length {values.shape[0]} does not "
            f"match the UMAPResult coordinate count {n_expected}."
        )
    return values, list(features)


def _read_window_indices(
    cluster_zarr: str | Path, *, n_expected: int
) -> tuple[NDArray[np.str_], NDArray[np.int64]]:
    with xr.open_zarr(Path(cluster_zarr).expanduser().resolve()) as ds:
        if "simulation_id" not in ds.coords:
            raise ValueError(
                "cluster Zarr has no 'simulation_id' coord required by "
                "trajectory / vector-field plots."
            )
        if "window_index_in_sim" not in ds.coords:
            raise ValueError(
                "cluster Zarr has no 'window_index_in_sim' coord required by "
                "trajectory / vector-field plots."
            )
        sim_ids = np.asarray(ds["simulation_id"].values).astype(str)
        window_indices = np.asarray(ds["window_index_in_sim"].values, dtype=np.int64)
    if sim_ids.shape[0] != n_expected:
        raise ValueError(
            f"simulation_id length {sim_ids.shape[0]} does not match the "
            f"UMAPResult coordinate count {n_expected}."
        )
    return sim_ids, window_indices


def _resolve_state_palette(
    labels: NDArray[np.int64],
    state_palette: dict[int, str] | None,
) -> dict[int, str]:
    unique_states = sorted({int(s) for s in np.unique(labels).tolist()})
    if state_palette is not None:
        missing = [s for s in unique_states if s not in state_palette]
        if missing:
            raise ValueError(
                f"state_palette is missing entries for state(s) {missing}. "
                f"Distinct states in the Zarr: {unique_states}"
            )
        return {int(s): str(state_palette[s]) for s in unique_states}
    if len(unique_states) > 10:
        raise ValueError(
            f"cluster Zarr has {len(unique_states)} distinct cluster labels "
            "(more than tab10 supports). Pass an explicit `state_palette` "
            "mapping each label to a colour."
        )
    cmap = plt.get_cmap("tab10")
    return {int(s): _rgba_to_hex(cmap(i)) for i, s in enumerate(unique_states)}


def _rgba_to_hex(rgba: tuple[float, float, float, float]) -> str:
    r, g, b, _ = rgba
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _scatter_states(
    ax: Axes,
    coords: NDArray[np.float64],
    labels: NDArray[np.int64],
    palette: dict[int, str],
    *,
    alpha: float = 0.7,
    s: int = 8,
) -> list[PathCollection]:
    collections: list[PathCollection] = []
    for state in sorted(palette):
        mask = labels == state
        if not mask.any():
            continue
        coll = ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            color=palette[state],
            s=s,
            alpha=alpha,
            label=f"state {state}",
            edgecolors="none",
        )
        collections.append(coll)
    return collections


def _per_state_displacements(
    coords: NDArray[np.float64],
    labels: NDArray[np.int64],
    sim_ids: NDArray[np.str_],
    window_indices: NDArray[np.int64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.int64]]:
    """Compute per-state consecutive-window displacements.

    A displacement is included for state ``s`` only when *both* the start
    window and the next window (by ``window_index_in_sim`` within the same
    simulation) carry label ``s``. This matches the LCSS-3 contract: the
    quiver for state ``s`` describes motion that *originates* inside ``s``
    and stays inside ``s``.
    """
    start_xy_list: list[NDArray[np.float64]] = []
    displacement_list: list[NDArray[np.float64]] = []
    state_list: list[int] = []

    for sid in np.unique(sim_ids):
        mask = sim_ids == sid
        if mask.sum() < 2:
            continue
        order = np.argsort(window_indices[mask])
        sim_coords = coords[mask][order]
        sim_labels = labels[mask][order]
        sim_window_idx = window_indices[mask][order]

        # Only count consecutive windows (no skips).
        for i in range(sim_coords.shape[0] - 1):
            if sim_window_idx[i + 1] - sim_window_idx[i] != 1:
                continue
            if sim_labels[i] != sim_labels[i + 1]:
                continue
            start_xy_list.append(sim_coords[i])
            displacement_list.append(sim_coords[i + 1] - sim_coords[i])
            state_list.append(int(sim_labels[i]))

    if len(start_xy_list) == 0:
        return (
            np.zeros((0, 2), dtype=np.float64),
            np.zeros((0, 2), dtype=np.float64),
            np.zeros((0,), dtype=np.int64),
        )

    return (
        np.asarray(start_xy_list, dtype=np.float64),
        np.asarray(displacement_list, dtype=np.float64),
        np.asarray(state_list, dtype=np.int64),
    )


def _aggregate_quiver_grid(
    start_xy: NDArray[np.float64],
    dxy: NDArray[np.float64],
    x_edges: NDArray[np.float64],
    y_edges: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Aggregate mean displacement per (x, y) grid cell.

    Returns ``(u_grid, v_grid, x_centers, y_centers)`` where ``u_grid`` and
    ``v_grid`` are ``(n_x, n_y)`` mean components in each cell. Cells with
    no displacements get NaN so callers can mask them out before passing to
    :func:`matplotlib.axes.Axes.quiver`.
    """
    n_x = x_edges.shape[0] - 1
    n_y = y_edges.shape[0] - 1
    u_grid = np.full((n_x, n_y), np.nan, dtype=np.float64)
    v_grid = np.full((n_x, n_y), np.nan, dtype=np.float64)
    if start_xy.shape[0] == 0:
        x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
        y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
        return u_grid, v_grid, x_centers, y_centers

    ix = np.clip(np.digitize(start_xy[:, 0], x_edges) - 1, 0, n_x - 1)
    iy = np.clip(np.digitize(start_xy[:, 1], y_edges) - 1, 0, n_y - 1)
    sum_u = np.zeros((n_x, n_y), dtype=np.float64)
    sum_v = np.zeros((n_x, n_y), dtype=np.float64)
    counts = np.zeros((n_x, n_y), dtype=np.int64)
    for k in range(start_xy.shape[0]):
        sum_u[ix[k], iy[k]] += dxy[k, 0]
        sum_v[ix[k], iy[k]] += dxy[k, 1]
        counts[ix[k], iy[k]] += 1
    populated = counts > 0
    u_grid[populated] = sum_u[populated] / counts[populated]
    v_grid[populated] = sum_v[populated] / counts[populated]
    x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    return u_grid, v_grid, x_centers, y_centers


def _maybe_save(fig: mfig.Figure, save_path: str | Path | None) -> None:
    if save_path is None:
        return
    out_path = Path(save_path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", dpi=150)


__all__ = [
    "UMAPResult",
    "fit_umap",
    "plot_feature_umap",
    "plot_state_umap",
    "plot_state_umap_with_vector_field",
    "plot_time_umap",
    "plot_trajectory_umap",
]
