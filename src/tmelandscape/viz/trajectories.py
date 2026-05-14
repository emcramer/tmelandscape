"""Heatmap-style figures over the Phase 5 cluster Zarr.

Two public functions live here:

* :func:`plot_state_feature_clustermap` — TNBC-2a: a seaborn ``clustermap``
  of Leiden-cluster mean spatial-feature values, with rows ordered by the
  Ward linkage stored on the cluster Zarr and a row colour bar coloured by
  each Leiden cluster's modal final TME-state.
* :func:`plot_trajectory_clustergram` — TNBC-6a: a ``(n_simulation,
  n_window_per_sim)`` heatmap of per-window state labels, ordered by a
  hierarchical clustering of the trajectory vectors. A left-hand
  dendrogram annotates the row order.

Both functions are read-only with respect to the input Zarr and return
``matplotlib.figure.Figure`` objects. When ``save_path`` is supplied each
function additionally writes a PNG (``bbox_inches="tight"``, ``dpi=150``).

Reference oracle: ``reference/02_abm_state_space_analysis.marimo.py``
lines 134-305 (clustermap) and 1000-1156 (trajectory clustergram).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, cast

import matplotlib.figure as mfig
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import xarray as xr
from matplotlib import colormaps
from matplotlib.colors import Colormap, ListedColormap
from matplotlib.gridspec import GridSpec
from scipy.cluster.hierarchy import dendrogram, linkage

if TYPE_CHECKING:
    from numpy.typing import NDArray


_TAB10_MAX_STATES = 10


def _tab10() -> Colormap:
    """Return matplotlib's ``tab10`` colormap.

    Wrapped so the lookup happens through ``matplotlib.colormaps`` (the
    forward-compatible API) rather than the deprecated ``cm.tab10``
    attribute, and so mypy gets a concrete ``Colormap`` return type.
    """
    return colormaps["tab10"]


def plot_state_feature_clustermap(
    cluster_zarr: str | Path,
    *,
    z_score: int | None = 1,
    cmap: str = "viridis",
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-2a — clustermap of Leiden-cluster means over spatial features.

    Reads ``leiden_cluster_means`` ``(n_leiden_cluster, n_embedding_feature)``
    from ``cluster_zarr``, collapses the window-stacked embedding-feature
    axis by averaging each statistic's repeated measures, and renders a
    seaborn ``clustermap``. Rows are ordered by the Ward linkage stored on
    the Zarr (``linkage_matrix``); the row colour bar paints each Leiden
    cluster by the mode of the final TME-state (``cluster_labels``) over
    the windows assigned to that Leiden cluster.

    Parameters
    ----------
    cluster_zarr
        Path to the Phase 5 cluster Zarr.
    z_score
        Passed through to ``seaborn.clustermap``. ``1`` (default) z-scores
        columns, ``0`` z-scores rows, ``None`` leaves values raw.
    cmap
        Matplotlib colormap name for the heatmap. Default ``"viridis"``.
    save_path
        If supplied, the returned figure is also saved to this path with
        ``bbox_inches="tight"`` and ``dpi=150``.

    Returns
    -------
    matplotlib.figure.Figure
        The seaborn ``clustermap``'s underlying figure (``g.fig``).

    Raises
    ------
    ValueError
        If ``cluster_zarr`` lacks ``leiden_cluster_means``,
        ``linkage_matrix``, or ``cluster_labels``; if the embedding-feature
        axis cannot be evenly partitioned into per-statistic groups using
        the ``statistic`` coord; or if more than ten distinct final TME
        states are present (``tab10`` would otherwise be silently
        extended).
    """
    cluster_path = Path(cluster_zarr).expanduser().resolve()
    with xr.open_zarr(cluster_path) as ds:
        _require_vars(ds, ("leiden_cluster_means", "linkage_matrix", "cluster_labels"))

        leiden_cluster_means = np.asarray(ds["leiden_cluster_means"].values, dtype=np.float64)
        linkage_matrix = np.asarray(ds["linkage_matrix"].values, dtype=np.float64)
        cluster_labels = np.asarray(ds["cluster_labels"].values, dtype=np.int64)
        leiden_labels = (
            np.asarray(ds["leiden_labels"].values, dtype=np.int64)
            if "leiden_labels" in ds.data_vars
            else None
        )

        if "statistic" not in ds.coords:
            raise ValueError(
                "cluster_zarr is missing the 'statistic' coord required to "
                "collapse the window-stacked embedding_feature axis into per-"
                "statistic means. The Phase 4 embedding orchestrator emits "
                "this coord on `window_averages`; if you opened a stripped-down "
                "Zarr without it, regenerate the cluster Zarr from a Phase 4 "
                "output that carries `statistic`."
            )
        statistic_names = [str(s) for s in ds.coords["statistic"].values.tolist()]

    collapsed = _collapse_repeated_measures(leiden_cluster_means, n_statistic=len(statistic_names))

    row_colors = _row_colors_from_modal_state(
        n_leiden_clusters=collapsed.shape[0],
        cluster_labels=cluster_labels,
        leiden_labels=leiden_labels,
    )

    grid = sns.clustermap(
        collapsed,
        row_linkage=linkage_matrix,
        row_colors=row_colors,
        cmap=cmap,
        z_score=z_score,
        xticklabels=statistic_names,
        yticklabels=False,
        figsize=(10, 8),
    )
    fig = cast(mfig.Figure, grid.fig)

    grid.ax_heatmap.set_xlabel("Spatial statistic")
    grid.ax_heatmap.set_ylabel("Leiden cluster")
    plt.setp(
        grid.ax_heatmap.xaxis.get_majorticklabels(),
        rotation=45,
        ha="right",
        fontsize=8,
    )

    if save_path is not None:
        fig.savefig(Path(save_path), bbox_inches="tight", dpi=150)

    return fig


def plot_trajectory_clustergram(
    cluster_zarr: str | Path,
    *,
    metric: str = "euclidean",
    linkage_method: str = "average",
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6a — trajectory clustergram of per-simulation state sequences.

    Builds a ``(n_simulation, n_window_per_sim)`` matrix of state labels by
    grouping ``cluster_labels`` on ``simulation_id`` and sorting on
    ``window_index_in_sim``, then runs ``scipy.cluster.hierarchy.linkage``
    on the per-simulation trajectory vectors. The result is a heatmap with
    a left-hand row dendrogram; discrete state colours come from a
    ``ListedColormap`` over matplotlib's ``tab10``.

    Parameters
    ----------
    cluster_zarr
        Path to the Phase 5 cluster Zarr.
    metric
        Distance metric passed to ``scipy.cluster.hierarchy.linkage``.
        Default ``"euclidean"``.
    linkage_method
        Linkage method passed to ``scipy.cluster.hierarchy.linkage``.
        Default ``"average"`` (matches the TNBC reference oracle).
    save_path
        If supplied, the returned figure is also saved to this path with
        ``bbox_inches="tight"`` and ``dpi=150``.

    Returns
    -------
    matplotlib.figure.Figure
        A two-panel figure: row dendrogram on the left, ``(sim x window)``
        state-label heatmap on the right.

    Raises
    ------
    ValueError
        If ``cluster_zarr`` lacks ``cluster_labels`` or the per-window
        ``simulation_id`` / ``window_index_in_sim`` coords; if any
        simulation contributes a different number of windows than the
        others (ragged trajectories are refused — the cleaner alternative
        to NaN-padding for a discrete-valued metric); or if more than ten
        distinct states are present.
    """
    cluster_path = Path(cluster_zarr).expanduser().resolve()
    with xr.open_zarr(cluster_path) as ds:
        _require_vars(ds, ("cluster_labels",))
        for coord_name in ("simulation_id", "window_index_in_sim"):
            if coord_name not in ds.coords:
                raise ValueError(
                    f"cluster_zarr is missing the per-window coord {coord_name!r}; "
                    "this coord is emitted by the Phase 4 embedding orchestrator "
                    "and is required to group windows into per-simulation "
                    "trajectories."
                )

        cluster_labels = np.asarray(ds["cluster_labels"].values, dtype=np.int64)
        simulation_id = np.asarray(ds.coords["simulation_id"].values)
        window_index_in_sim = np.asarray(ds.coords["window_index_in_sim"].values, dtype=np.int64)

    trajectory_matrix, sim_ids_ordered = _build_trajectory_matrix(
        cluster_labels=cluster_labels,
        simulation_id=simulation_id,
        window_index_in_sim=window_index_in_sim,
    )

    unique_states = np.unique(trajectory_matrix)
    if unique_states.size > _TAB10_MAX_STATES:
        raise ValueError(
            f"plot_trajectory_clustergram supports at most {_TAB10_MAX_STATES} "
            f"distinct states (matplotlib's tab10 palette); got "
            f"{unique_states.size}. Silent palette extension is disallowed."
        )

    state_to_rank = {int(state): i for i, state in enumerate(unique_states.tolist())}
    ranked_matrix = np.vectorize(state_to_rank.get)(trajectory_matrix).astype(np.int64)

    row_linkage = linkage(
        trajectory_matrix.astype(np.float64), method=linkage_method, metric=metric
    )

    palette = [_tab10()(i) for i in range(unique_states.size)]
    discrete_cmap = ListedColormap(palette)

    fig = plt.figure(figsize=(12, 8))
    gs = GridSpec(1, 2, width_ratios=[1, 4], wspace=0.02, figure=fig)

    ax_dendro = fig.add_subplot(gs[0, 0])
    dendro_info = dendrogram(
        row_linkage,
        orientation="left",
        ax=ax_dendro,
        link_color_func=lambda _k: "black",
        no_labels=True,
    )
    ax_dendro.set_xticks([])
    ax_dendro.set_yticks([])
    for spine in ax_dendro.spines.values():
        spine.set_visible(False)

    reorder = list(dendro_info["leaves"])
    sorted_ranked = ranked_matrix[reorder, :]

    ax_heatmap = fig.add_subplot(gs[0, 1])
    ax_heatmap.imshow(
        sorted_ranked,
        cmap=discrete_cmap,
        aspect="auto",
        interpolation="nearest",
        vmin=-0.5,
        vmax=unique_states.size - 0.5,
        origin="upper",
    )
    ax_heatmap.set_xlabel("Time window")
    ax_heatmap.set_ylabel("Simulation (clustered)")
    ax_heatmap.set_yticks([])
    ax_heatmap.set_title("Simulation trajectories through state space")

    fig.suptitle(f"Trajectory clustergram (n={len(sim_ids_ordered)} sims)", y=0.98)

    if save_path is not None:
        fig.savefig(Path(save_path), bbox_inches="tight", dpi=150)

    return fig


def _require_vars(ds: xr.Dataset, names: tuple[str, ...]) -> None:
    """Raise ``ValueError`` if any of ``names`` is missing from ``ds``."""
    missing = [n for n in names if n not in ds.data_vars]
    if missing:
        raise ValueError(
            f"cluster_zarr is missing required data variable(s) {missing}. "
            f"Available variables: {sorted(str(v) for v in ds.data_vars)}."
        )


def _collapse_repeated_measures(
    leiden_cluster_means: NDArray[np.float64], *, n_statistic: int
) -> NDArray[np.float64]:
    """Collapse the window-stacked embedding-feature axis by per-statistic mean.

    Phase 4's flattening order is C-order over ``(window_size, n_statistic)``
    (see :mod:`tmelandscape.embedding.sliding_window`), so each row of
    ``leiden_cluster_means`` lays out features as
    ``[stat_0_w0, stat_1_w0, ..., stat_{S-1}_w0, stat_0_w1, ...]``. Averaging
    over the ``window_size`` repeats per statistic recovers a
    ``(n_leiden_cluster, n_statistic)`` matrix indexed by the input
    ``statistic`` coord.
    """
    n_features = int(leiden_cluster_means.shape[1])
    if n_statistic <= 0:
        raise ValueError(
            f"_collapse_repeated_measures: n_statistic must be positive; got {n_statistic}"
        )
    if n_features % n_statistic != 0:
        raise ValueError(
            f"_collapse_repeated_measures: embedding-feature axis length "
            f"({n_features}) is not divisible by the number of statistics "
            f"({n_statistic}); cannot infer the window-stride mapping. "
            "Check that the cluster Zarr's `statistic` coord matches the "
            "Phase 4 input that produced `leiden_cluster_means`."
        )
    window_size = n_features // n_statistic
    reshaped = leiden_cluster_means.reshape(-1, window_size, n_statistic)
    return cast("NDArray[np.float64]", reshaped.mean(axis=1))


def _row_colors_from_modal_state(
    *,
    n_leiden_clusters: int,
    cluster_labels: NDArray[np.int64],
    leiden_labels: NDArray[np.int64] | None,
) -> list[tuple[float, float, float, float]]:
    """Map each Leiden cluster to a ``tab10`` colour via the mode of the
    final TME-state assigned to its windows.

    When ``leiden_labels`` is not available we fall back to a per-row
    state-rank colouring derived from the Ward dendrogram cut implicit in
    ``cluster_labels`` — but the contract requires ``cluster_labels``, so
    the absence of ``leiden_labels`` simply means each row gets the modal
    final state across the full window axis (a graceful degradation;
    the rendered colours then no longer carry per-row signal but the
    figure still produces).

    Raises ``ValueError`` if more than ten distinct final states are seen
    (``tab10`` has ten entries; we refuse to silently extend the palette).
    """
    unique_states = np.unique(cluster_labels)
    if unique_states.size > _TAB10_MAX_STATES:
        raise ValueError(
            f"plot_state_feature_clustermap supports at most {_TAB10_MAX_STATES} "
            f"distinct final states (matplotlib's tab10 palette); got "
            f"{unique_states.size}. Silent palette extension is disallowed."
        )

    state_to_rank = {int(state): i for i, state in enumerate(unique_states.tolist())}

    if leiden_labels is None:
        modal_state = int(Counter(int(x) for x in cluster_labels.tolist()).most_common(1)[0][0])
        rank = state_to_rank[modal_state]
        return [_tab10()(rank)] * n_leiden_clusters

    row_colors: list[tuple[float, float, float, float]] = []
    for leiden_id in range(n_leiden_clusters):
        mask = leiden_labels == leiden_id
        if not bool(mask.any()):
            row_colors.append(_tab10()(0))
            continue
        modal_state = int(
            Counter(int(x) for x in cluster_labels[mask].tolist()).most_common(1)[0][0]
        )
        row_colors.append(_tab10()(state_to_rank[modal_state]))
    return row_colors


def _build_trajectory_matrix(
    *,
    cluster_labels: NDArray[np.int64],
    simulation_id: NDArray[np.generic],
    window_index_in_sim: NDArray[np.int64],
) -> tuple[NDArray[np.int64], list[str]]:
    """Reshape per-window ``cluster_labels`` into a ``(n_sim, n_window)`` matrix.

    Returns the matrix and the list of simulation ids in row order
    (the ids are sorted by first-appearance to match the input ordering's
    intent without being sensitive to within-sim window ordering).

    Raises ``ValueError`` if any simulation has a different window count
    than the others (ragged trajectories are refused).
    """
    sim_ids_str: list[str] = [str(s) for s in simulation_id.tolist()]
    seen: dict[str, int] = {}
    for sid in sim_ids_str:
        if sid not in seen:
            seen[sid] = len(seen)
    sim_ids_ordered = list(seen.keys())

    n_sim = len(sim_ids_ordered)
    if n_sim == 0:
        raise ValueError(
            "plot_trajectory_clustergram: cluster_zarr contains zero windows; "
            "cannot build a trajectory matrix."
        )

    per_sim_windows: dict[str, list[tuple[int, int]]] = {sid: [] for sid in sim_ids_ordered}
    for row_idx, sid in enumerate(sim_ids_str):
        per_sim_windows[sid].append(
            (int(window_index_in_sim[row_idx]), int(cluster_labels[row_idx]))
        )

    n_windows_per_sim = {sid: len(pairs) for sid, pairs in per_sim_windows.items()}
    unique_lengths = set(n_windows_per_sim.values())
    if len(unique_lengths) != 1:
        raise ValueError(
            "plot_trajectory_clustergram: ragged trajectories are not supported; "
            f"simulations have differing window counts {n_windows_per_sim}. "
            "Re-window the upstream ensemble so every sim contributes the same "
            "number of windows, or filter to a uniform subset before calling."
        )

    n_window = next(iter(unique_lengths))
    matrix = np.empty((n_sim, n_window), dtype=np.int64)
    for row_idx, sid in enumerate(sim_ids_ordered):
        pairs = sorted(per_sim_windows[sid], key=lambda p: p[0])
        if [p[0] for p in pairs] != list(range(n_window)):
            raise ValueError(
                f"plot_trajectory_clustergram: simulation {sid!r} has non-contiguous "
                f"window_index_in_sim values {[p[0] for p in pairs]}; expected "
                f"{list(range(n_window))}. The Phase 4 orchestrator emits "
                "contiguous indices — re-run the upstream pipeline if you see this."
            )
        matrix[row_idx, :] = [p[1] for p in pairs]

    return matrix, sim_ids_ordered


__all__ = [
    "plot_state_feature_clustermap",
    "plot_trajectory_clustergram",
]
