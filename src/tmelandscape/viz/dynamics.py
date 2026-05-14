"""Phase 6 — phase-space dynamics and parameter-state figures.

Three publication figures, all read-only with respect to the inputs and
returning :class:`matplotlib.figure.Figure` objects:

- :func:`plot_phase_space_vector_field` — TNBC-6b. Per-state mean
  displacement quiver overlaid on per-state 2D occupancy histogram in a
  user-supplied ``(x_feature, y_feature)`` phase space drawn from the
  cluster Zarr's ``window_averages`` array.
- :func:`plot_parameter_by_state` — TNBC-6c. Violin plot of one
  user-supplied sweep parameter by terminal cluster label, with pairwise
  Mann-Whitney U significance + Benjamini-Hochberg FDR correction.
- :func:`plot_attractor_basins` — LCSS-6. 2D parameter-space scatter of
  sims coloured by terminal cluster, k-NN decision-boundary regions
  painted as a shaded background.

Parameter and feature names are **always user-supplied**, never
hardcoded to manuscript-specific values, per
[ADR 0009](../../../docs/adr/0009-no-hardcoded-statistics-panel.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib.figure as mfig
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import xarray as xr
from matplotlib.axes import Axes
from matplotlib.colors import ListedColormap
from numpy.typing import NDArray
from scipy.stats import mannwhitneyu
from sklearn.neighbors import KNeighborsClassifier

from tmelandscape.landscape import join_manifest_cluster


def plot_phase_space_vector_field(
    cluster_zarr: str | Path,
    *,
    x_feature: str,
    y_feature: str,
    states: Sequence[int],
    grid_size: int = 20,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6b — vector field in ``(x_feature, y_feature)`` phase space.

    For each state in ``states``:

    1. Pull the windows currently in that state. Order them by
       ``(simulation_id, window_index_in_sim)``.
    2. Compute consecutive Δ in ``(x_feature, y_feature)`` within a
       single simulation; drop transitions that cross sim boundaries.
    3. Bin the source positions onto a ``grid_size x grid_size`` grid
       over the union ``(x, y)`` bounding box; aggregate per-cell mean
       ``(Δx, Δy)`` ⇒ one quiver overlay per state.
    4. Background heatmap = per-state 2D occupancy histogram (count of
       windows per cell).
    5. Cross marker at the per-state entry-point centroid — the mean
       ``(x, y)`` of the first window per sim in that state.

    Parameters
    ----------
    cluster_zarr
        Path to the Phase 5 cluster Zarr. Must carry ``cluster_labels``,
        ``simulation_id``, ``window_index_in_sim``, and a
        ``window_averages`` array with a ``statistic`` coord listing
        ``x_feature`` and ``y_feature``.
    x_feature, y_feature
        Statistic names; both must appear in the Zarr's ``statistic``
        coord. No defaults — user-supplied per ADR 0009.
    states
        Sequence of terminal-cluster integer labels to overlay. Must be
        non-empty.
    grid_size
        Bins per axis for the quiver / occupancy grid.
    save_path
        If given, the figure is saved to this path at dpi=150,
        bbox_inches='tight'.

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ValueError
        If ``states`` is empty; if ``x_feature`` or ``y_feature`` is
        missing from the Zarr's ``statistic`` coord.
    """
    if len(states) == 0:
        raise ValueError("states must be a non-empty sequence of terminal-cluster labels.")

    cluster_path = Path(cluster_zarr).expanduser().resolve()
    with xr.open_zarr(cluster_path) as ds:
        if "window_averages" not in ds.data_vars:
            raise ValueError(
                f"cluster Zarr at {cluster_path!s} has no 'window_averages' variable; "
                "the phase-space vector field needs the per-window statistic averages "
                "produced by Phase 3."
            )
        available = [str(s) for s in np.asarray(ds["statistic"].values).tolist()]
        for feat_name, feat_value in (("x_feature", x_feature), ("y_feature", y_feature)):
            if feat_value not in available:
                raise ValueError(
                    f"{feat_name}={feat_value!r} not in cluster Zarr 'statistic' coord; "
                    f"available statistics: {available}"
                )
        wa = ds["window_averages"]
        stat_index = available.index
        x_vals = np.asarray(wa.isel(statistic=stat_index(x_feature)).values, dtype=np.float64)
        y_vals = np.asarray(wa.isel(statistic=stat_index(y_feature)).values, dtype=np.float64)
        cluster_labels = np.asarray(ds["cluster_labels"].values).astype(np.int64)
        sim_ids = np.asarray(ds["simulation_id"].values).astype(str)
        win_idx = np.asarray(ds["window_index_in_sim"].values).astype(np.int64)

    sort_order = np.lexsort((win_idx, sim_ids))
    x_sorted = x_vals[sort_order]
    y_sorted = y_vals[sort_order]
    sim_sorted = sim_ids[sort_order]
    win_sorted = win_idx[sort_order]
    label_sorted = cluster_labels[sort_order]

    x_min, x_max = float(np.min(x_sorted)), float(np.max(x_sorted))
    y_min, y_max = float(np.min(y_sorted)), float(np.max(y_sorted))
    if x_max == x_min:
        x_max = x_min + 1.0
    if y_max == y_min:
        y_max = y_min + 1.0
    x_edges = np.linspace(x_min, x_max, grid_size + 1)
    y_edges = np.linspace(y_min, y_max, grid_size + 1)
    x_centres = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_centres = 0.5 * (y_edges[:-1] + y_edges[1:])
    grid_x, grid_y = np.meshgrid(x_centres, y_centres, indexing="xy")

    fig, axes = plt.subplots(
        1,
        len(states),
        figsize=(4 * len(states), 4),
        squeeze=False,
    )
    palette = plt.get_cmap("tab10")

    for idx, state in enumerate(states):
        ax = axes[0, idx]
        state_mask = label_sorted == int(state)
        state_x = x_sorted[state_mask]
        state_y = y_sorted[state_mask]
        state_sim = sim_sorted[state_mask]
        state_win = win_sorted[state_mask]

        occupancy, _, _ = np.histogram2d(
            state_x,
            state_y,
            bins=[x_edges, y_edges],
        )
        # occupancy has shape (n_x, n_y); plot with origin lower so y goes up
        ax.imshow(
            occupancy.T,
            origin="lower",
            extent=(x_min, x_max, y_min, y_max),
            aspect="auto",
            cmap="Greys",
            interpolation="nearest",
        )

        u_grid, v_grid = _mean_displacement_grid(
            x=state_x,
            y=state_y,
            sim=state_sim,
            win=state_win,
            x_edges=x_edges,
            y_edges=y_edges,
        )

        ax.quiver(
            grid_x,
            grid_y,
            u_grid,
            v_grid,
            color=palette(idx % 10),
            angles="xy",
            scale_units="xy",
            scale=1.0,
            pivot="middle",
        )

        entry_x, entry_y = _state_entry_centroid(
            x=state_x,
            y=state_y,
            sim=state_sim,
            win=state_win,
        )
        if entry_x is not None and entry_y is not None:
            ax.plot(
                entry_x,
                entry_y,
                marker="x",
                markersize=12,
                markeredgewidth=2,
                color=palette(idx % 10),
                linestyle="",
            )

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_xlabel(x_feature)
        ax.set_ylabel(y_feature)
        ax.set_title(f"state {state}")

    fig.suptitle(f"phase-space vector field: {x_feature} vs {y_feature}")
    fig.tight_layout()

    if save_path is not None:
        fig.savefig(save_path, bbox_inches="tight", dpi=150)
    return fig


def plot_parameter_by_state(
    cluster_zarr: str | Path,
    manifest_path: str | Path,
    *,
    parameter: str,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6c — violin plot of one parameter by terminal state.

    Joins the manifest with the cluster Zarr via
    :func:`tmelandscape.landscape.join_manifest_cluster`, groups by
    ``terminal_cluster_label``, and draws a seaborn violin per state.
    Pairwise Mann-Whitney U + Benjamini-Hochberg FDR correction
    annotates significantly different state pairs.

    Parameters
    ----------
    cluster_zarr
        Phase 5 cluster Zarr.
    manifest_path
        Phase 2 sweep manifest JSON.
    parameter
        Column name on the joined frame — must be one of the
        ``parameter_<name>`` columns. No default, per ADR 0009.
    save_path
        Optional output path; ``dpi=150``, ``bbox_inches='tight'``.

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ValueError
        If ``parameter`` is not a column on the joined frame.
    """
    joined = join_manifest_cluster(manifest_path, cluster_zarr)
    parameter_columns = [c for c in joined.columns if c.startswith("parameter_")]
    if parameter not in joined.columns:
        raise ValueError(
            f"parameter={parameter!r} not in joined manifest columns. "
            f"available parameter columns: {parameter_columns}"
        )

    plot_df = joined[[parameter, "terminal_cluster_label"]].dropna()
    plot_df = plot_df.assign(terminal_cluster_label=plot_df["terminal_cluster_label"].astype(int))
    states = sorted(plot_df["terminal_cluster_label"].unique().tolist())

    fig, ax = plt.subplots(figsize=(max(4.0, 1.2 * len(states)), 5.0))
    sns.violinplot(
        data=plot_df,
        x="terminal_cluster_label",
        y=parameter,
        order=states,
        ax=ax,
    )
    ax.set_xlabel("terminal cluster label")
    ax.set_ylabel(parameter)
    ax.set_title(f"{parameter} by terminal state")

    pairwise = _pairwise_mannwhitney_bh(plot_df, parameter, states)
    _annotate_significance(ax, plot_df, parameter, states, pairwise)

    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, bbox_inches="tight", dpi=150)
    return fig


def plot_attractor_basins(
    cluster_zarr: str | Path,
    manifest_path: str | Path,
    *,
    x_parameter: str,
    y_parameter: str,
    states: Sequence[int] | None = None,
    knn_neighbors: int = 2,
    grid_size: int = 200,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS-6 — parameter-space attractor basins via k-NN decision regions.

    Joins the manifest with the cluster Zarr, fits a
    :class:`~sklearn.neighbors.KNeighborsClassifier` on
    ``(x_parameter, y_parameter) -> terminal_cluster_label`` (restricted
    to ``states`` if provided), predicts on a dense
    ``grid_size x grid_size`` grid spanning the parameter bounding box,
    and paints the prediction with ``ax.contourf``. The training points
    are overlaid as a scatter coloured by terminal label.

    Parameters
    ----------
    cluster_zarr, manifest_path
        Phase 5 cluster Zarr + Phase 2 manifest JSON.
    x_parameter, y_parameter
        Column names on the joined frame; must be ``parameter_<name>``
        entries. User-supplied per ADR 0009.
    states
        If given, restrict both the classifier and scatter to sims with
        a terminal label in this set. ``None`` ⇒ use every state present.
    knn_neighbors
        ``n_neighbors`` for the k-NN classifier. Default 2 matches the
        LCSS Methods description.
    grid_size
        Bins per axis for the background field.
    save_path
        Optional output path.

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ValueError
        If ``x_parameter`` / ``y_parameter`` not on the joined frame; if
        ``states`` is supplied but empty.
    """
    joined = join_manifest_cluster(manifest_path, cluster_zarr)
    parameter_columns = [c for c in joined.columns if c.startswith("parameter_")]
    for param_name, param_value in (("x_parameter", x_parameter), ("y_parameter", y_parameter)):
        if param_value not in joined.columns:
            raise ValueError(
                f"{param_name}={param_value!r} not in joined manifest columns. "
                f"available parameter columns: {parameter_columns}"
            )

    if states is not None and len(states) == 0:
        raise ValueError("states must be None or a non-empty sequence.")

    plot_df = joined[[x_parameter, y_parameter, "terminal_cluster_label"]].dropna()
    plot_df = plot_df.assign(terminal_cluster_label=plot_df["terminal_cluster_label"].astype(int))
    if states is not None:
        plot_df = plot_df[plot_df["terminal_cluster_label"].isin(list(states))]
    if plot_df.empty:
        raise ValueError("no sims remain after filtering by states; nothing to plot.")

    x_arr = plot_df[x_parameter].to_numpy(dtype=np.float64)
    y_arr = plot_df[y_parameter].to_numpy(dtype=np.float64)
    label_arr = plot_df["terminal_cluster_label"].to_numpy(dtype=np.int64)

    classifier = KNeighborsClassifier(n_neighbors=min(knn_neighbors, len(plot_df)))
    classifier.fit(np.column_stack([x_arr, y_arr]), label_arr)

    x_min, x_max = float(x_arr.min()), float(x_arr.max())
    y_min, y_max = float(y_arr.min()), float(y_arr.max())
    if x_max == x_min:
        x_max = x_min + 1.0
    if y_max == y_min:
        y_max = y_min + 1.0
    x_pad = 0.05 * (x_max - x_min)
    y_pad = 0.05 * (y_max - y_min)
    grid_x_vals = np.linspace(x_min - x_pad, x_max + x_pad, grid_size)
    grid_y_vals = np.linspace(y_min - y_pad, y_max + y_pad, grid_size)
    grid_xx, grid_yy = np.meshgrid(grid_x_vals, grid_y_vals)
    grid_points = np.column_stack([grid_xx.ravel(), grid_yy.ravel()])
    grid_pred = classifier.predict(grid_points).reshape(grid_xx.shape)

    unique_states = sorted(np.unique(label_arr).tolist())
    palette = plt.get_cmap("tab10")
    colours = [palette(s % 10) for s in unique_states]
    cmap = ListedColormap(colours)

    fig, ax = plt.subplots(figsize=(6.0, 5.0))
    levels = [s - 0.5 for s in unique_states] + [unique_states[-1] + 0.5]
    ax.contourf(grid_xx, grid_yy, grid_pred, levels=levels, cmap=cmap, alpha=0.35)
    for s_idx, state in enumerate(unique_states):
        mask = label_arr == state
        ax.scatter(
            x_arr[mask],
            y_arr[mask],
            color=colours[s_idx],
            edgecolor="black",
            linewidth=0.5,
            label=f"state {state}",
        )
    ax.set_xlabel(x_parameter)
    ax.set_ylabel(y_parameter)
    ax.set_title(f"attractor basins: {x_parameter} vs {y_parameter}")
    ax.legend(loc="best", fontsize="small")
    fig.tight_layout()

    if save_path is not None:
        fig.savefig(save_path, bbox_inches="tight", dpi=150)
    return fig


def _mean_displacement_grid(
    *,
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    sim: NDArray[np.str_],
    win: NDArray[np.int64],
    x_edges: NDArray[np.float64],
    y_edges: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Mean (Δx, Δy) per (x, y) bin, restricted to same-sim transitions.

    Rows of the inputs are pre-sorted by ``(sim, win)``. For each
    consecutive pair with the same ``sim`` and ``win[i+1] == win[i] + 1``
    we drop the source position into the bin grid and accumulate
    ``(Δx, Δy)``. Bins with zero source positions get ``nan`` displacement
    so the quiver renders nothing there.

    Returns
    -------
    (u, v)
        Each shaped ``(n_y, n_x)`` to match ``np.meshgrid(..., indexing='xy')``.
    """
    n_x = x_edges.size - 1
    n_y = y_edges.size - 1
    u_sum = np.zeros((n_y, n_x), dtype=np.float64)
    v_sum = np.zeros((n_y, n_x), dtype=np.float64)
    counts = np.zeros((n_y, n_x), dtype=np.int64)

    if x.shape[0] < 2:
        return _safe_divide(u_sum, counts), _safe_divide(v_sum, counts)

    same_sim = sim[1:] == sim[:-1]
    consecutive = win[1:] == win[:-1] + 1
    keep = same_sim & consecutive
    if not np.any(keep):
        return _safe_divide(u_sum, counts), _safe_divide(v_sum, counts)

    src_x = x[:-1][keep]
    src_y = y[:-1][keep]
    dst_x = x[1:][keep]
    dst_y = y[1:][keep]
    dx = dst_x - src_x
    dy = dst_y - src_y

    x_bin = np.clip(np.digitize(src_x, x_edges) - 1, 0, n_x - 1)
    y_bin = np.clip(np.digitize(src_y, y_edges) - 1, 0, n_y - 1)
    for xi, yi, dxi, dyi in zip(x_bin, y_bin, dx, dy, strict=False):
        u_sum[yi, xi] += dxi
        v_sum[yi, xi] += dyi
        counts[yi, xi] += 1

    return _safe_divide(u_sum, counts), _safe_divide(v_sum, counts)


def _safe_divide(numerator: NDArray[np.float64], counts: NDArray[np.int64]) -> NDArray[np.float64]:
    """Element-wise ``numerator / counts`` with ``nan`` where counts == 0."""
    out = np.full_like(numerator, np.nan)
    nonzero = counts > 0
    out[nonzero] = numerator[nonzero] / counts[nonzero]
    return out


def _state_entry_centroid(
    *,
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    sim: NDArray[np.str_],
    win: NDArray[np.int64],
) -> tuple[float | None, float | None]:
    """Mean ``(x, y)`` over the first window per sim in this state.

    Inputs are pre-sorted by ``(sim, win)``; the first row of each
    ``sim`` group is its entry into the state.
    """
    if x.shape[0] == 0:
        return None, None
    is_first = np.empty(x.shape[0], dtype=bool)
    is_first[0] = True
    is_first[1:] = sim[1:] != sim[:-1]
    entry_x = float(np.mean(x[is_first]))
    entry_y = float(np.mean(y[is_first]))
    return entry_x, entry_y


def _pairwise_mannwhitney_bh(
    df: pd.DataFrame,
    parameter: str,
    states: Sequence[int],
) -> dict[tuple[int, int], float]:
    """Pairwise Mann-Whitney U + Benjamini-Hochberg FDR adjustment.

    Returns a dict ``(state_i, state_j) -> q_value`` for ``i < j``. When
    a pair has too few samples for the test, the raw p-value is set to
    ``nan`` and that pair drops out of the FDR adjustment but stays in
    the returned dict (with value ``nan``) so the caller can choose to
    annotate it as "n/a" rather than silently omit.

    Implements BH by hand: rank the m valid p-values ascending, multiply
    each by ``m / rank``, then enforce monotone non-decreasing q's by
    cumulative-min from the largest rank back. See Benjamini & Hochberg
    (1995).
    """
    raw: dict[tuple[int, int], float] = {}
    for i, s_i in enumerate(states):
        for s_j in states[i + 1 :]:
            a = df.loc[df["terminal_cluster_label"] == s_i, parameter].to_numpy()
            b = df.loc[df["terminal_cluster_label"] == s_j, parameter].to_numpy()
            if a.size < 2 or b.size < 2:
                raw[(int(s_i), int(s_j))] = float("nan")
                continue
            try:
                stat = mannwhitneyu(a, b, alternative="two-sided")
                raw[(int(s_i), int(s_j))] = float(stat.pvalue)
            except ValueError:
                raw[(int(s_i), int(s_j))] = float("nan")

    finite_pairs = [(pair, p) for pair, p in raw.items() if np.isfinite(p)]
    adjusted: dict[tuple[int, int], float] = dict(raw)
    if finite_pairs:
        finite_pairs.sort(key=lambda kv: kv[1])
        m = len(finite_pairs)
        scaled = np.array(
            [p * m / (rank + 1) for rank, (_, p) in enumerate(finite_pairs)],
            dtype=np.float64,
        )
        scaled = np.minimum.accumulate(scaled[::-1])[::-1]
        scaled = np.clip(scaled, 0.0, 1.0)
        for (pair, _), q in zip(finite_pairs, scaled, strict=False):
            adjusted[pair] = float(q)
    return adjusted


def _annotate_significance(
    ax: Axes,
    df: pd.DataFrame,
    parameter: str,
    states: Sequence[int],
    pairwise: dict[tuple[int, int], float],
    *,
    alpha: float = 0.05,
) -> None:
    """Draw significance bars above the violins for q < ``alpha`` pairs."""
    significant = [(pair, q) for pair, q in pairwise.items() if np.isfinite(q) and q < alpha]
    if not significant:
        return
    y_top = float(df[parameter].max())
    y_bottom = float(df[parameter].min())
    span = y_top - y_bottom
    if span <= 0:
        span = 1.0
    bar_step = 0.06 * span
    bar_base = y_top + 0.05 * span
    state_to_pos = {int(s): idx for idx, s in enumerate(states)}
    significant.sort(key=lambda kv: (state_to_pos[kv[0][0]], state_to_pos[kv[0][1]]))
    for i, ((s_a, s_b), q) in enumerate(significant):
        x1 = state_to_pos[s_a]
        x2 = state_to_pos[s_b]
        y = bar_base + i * bar_step
        ax.plot([x1, x1, x2, x2], [y, y + 0.2 * bar_step, y + 0.2 * bar_step, y], color="black")
        marker = _significance_marker(q)
        ax.text((x1 + x2) / 2.0, y + 0.3 * bar_step, marker, ha="center", va="bottom")
    ax.set_ylim(y_bottom - 0.05 * span, bar_base + (len(significant) + 1) * bar_step)


def _significance_marker(q: float) -> str:
    """Map an FDR-adjusted q-value to a star marker per common convention."""
    if q < 0.001:
        return "***"
    if q < 0.01:
        return "**"
    if q < 0.05:
        return "*"
    return "ns"


__all__ = [
    "plot_attractor_basins",
    "plot_parameter_by_state",
    "plot_phase_space_vector_field",
]
