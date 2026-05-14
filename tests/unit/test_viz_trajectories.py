"""Unit tests for ``tmelandscape.viz.trajectories``.

Strategy (per ``tasks/07-visualisation-implementation.md`` testing section):

* Smoke — each public function returns a ``Figure`` with the expected
  Axes count (clustermap: seaborn's four axes; clustergram: dendro +
  heatmap).
* Determinism — same inputs produce the same heatmap pixel array.
* Data correctness — the heatmap data matches the analytically computed
  collapsed matrix / the reshaped ``cluster_labels``.
* ``save_path`` round-trip — a valid PNG lands on disk.
* Error cases — missing variables, palette overflow.

A small synthetic cluster Zarr (5 sims x 10 windows, ~3 statistics, 6
final states) is built per-test via a local helper rather than a global
fixture; this keeps the tests self-contained and avoids coupling to
Stream A's ``conftest.py`` additions.
"""

from __future__ import annotations

import struct
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
import xarray as xr


def _build_cluster_zarr(
    path: Path,
    *,
    n_sim: int = 5,
    n_window_per_sim: int = 10,
    window_size: int = 4,
    n_statistic: int = 3,
    n_leiden_clusters: int = 6,
    n_final_states: int = 4,
    seed: int = 0,
    ragged: bool = False,
    drop_vars: tuple[str, ...] = (),
    drop_coords: tuple[str, ...] = (),
) -> Path:
    """Write a synthetic cluster Zarr matching the Phase 5 output layout.

    Mirrors the layout described in the Phase 5 orchestrator
    docstring: ``embedding`` ``(window, embedding_feature)`` float64,
    ``window_averages`` ``(window, statistic)`` float64,
    ``leiden_labels`` ``(window,)`` int64, ``cluster_labels``
    ``(window,)`` int64, ``leiden_cluster_means``
    ``(leiden_cluster, embedding_feature)`` float64,
    ``linkage_matrix`` ``(linkage_step, linkage_field=4)`` float64,
    plus per-window coords ``simulation_id`` / ``window_index_in_sim``
    and the ``statistic`` coord. The ``ragged`` flag drops the final
    window of the first sim so the trajectories cannot be rectangularised.
    """
    rng = np.random.default_rng(seed)

    if ragged:
        per_sim_windows = [n_window_per_sim] * n_sim
        per_sim_windows[0] = n_window_per_sim - 2
    else:
        per_sim_windows = [n_window_per_sim] * n_sim
    n_window_total = int(sum(per_sim_windows))

    n_embedding_feature = window_size * n_statistic

    embedding = rng.normal(size=(n_window_total, n_embedding_feature)).astype(np.float64)
    window_averages = rng.normal(size=(n_window_total, n_statistic)).astype(np.float64)
    leiden_labels = rng.integers(0, n_leiden_clusters, size=n_window_total, dtype=np.int64)
    cluster_labels = rng.integers(1, n_final_states + 1, size=n_window_total, dtype=np.int64)

    leiden_cluster_means = rng.normal(size=(n_leiden_clusters, n_embedding_feature)).astype(
        np.float64
    )

    n_linkage_steps = n_leiden_clusters - 1
    linkage_matrix = np.zeros((n_linkage_steps, 4), dtype=np.float64)
    next_node = n_leiden_clusters
    available = list(range(n_leiden_clusters))
    for step in range(n_linkage_steps):
        a, b = available[0], available[1]
        linkage_matrix[step, 0] = float(a)
        linkage_matrix[step, 1] = float(b)
        linkage_matrix[step, 2] = float(step + 1)
        linkage_matrix[step, 3] = float(step + 2)
        available = [next_node, *available[2:]]
        next_node += 1

    simulation_id = np.array(
        [f"sim_{s:03d}" for s, n in enumerate(per_sim_windows) for _ in range(n)],
        dtype=object,
    )
    window_index_in_sim = np.array(
        [i for n in per_sim_windows for i in range(n)],
        dtype=np.int64,
    )
    statistic_names = np.array([f"stat_{i}" for i in range(n_statistic)], dtype=object)

    data_vars: dict[str, tuple[tuple[str, ...], np.ndarray]] = {
        "embedding": (("window", "embedding_feature"), embedding),
        "window_averages": (("window", "statistic"), window_averages),
        "leiden_labels": (("window",), leiden_labels),
        "cluster_labels": (("window",), cluster_labels),
        "leiden_cluster_means": (
            ("leiden_cluster", "embedding_feature"),
            leiden_cluster_means,
        ),
        "linkage_matrix": (("linkage_step", "linkage_field"), linkage_matrix),
    }
    coords: dict[str, tuple[tuple[str, ...], np.ndarray]] = {
        "simulation_id": (("window",), simulation_id),
        "window_index_in_sim": (("window",), window_index_in_sim),
        "statistic": (("statistic",), statistic_names),
        "embedding_feature": (
            ("embedding_feature",),
            np.arange(n_embedding_feature, dtype=np.int64),
        ),
    }
    for v in drop_vars:
        data_vars.pop(v, None)
    for c in drop_coords:
        coords.pop(c, None)

    ds = xr.Dataset(data_vars=data_vars, coords=coords)
    ds.to_zarr(path, mode="w")
    return path


def _is_valid_png(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as fh:
        header = fh.read(8)
    return header == struct.pack(">8B", 137, 80, 78, 71, 13, 10, 26, 10)


# --- plot_state_feature_clustermap ------------------------------------------


def test_state_feature_clustermap_smoke(tmp_path: Path) -> None:
    """Returns a Figure with the four axes seaborn.clustermap produces."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr")
    fig = plot_state_feature_clustermap(zarr_path)
    # seaborn.clustermap: row dendro, col dendro, row colors, heatmap, cbar -> 5
    # but row_colors adds an axis only if supplied; we always supply it, so we
    # expect at least four axes. Accept >= 4 to remain tolerant across seaborn
    # minor versions (some add a hidden cbar-spacer axis).
    assert len(fig.axes) >= 4
    plt.close("all")


def test_state_feature_clustermap_determinism(tmp_path: Path) -> None:
    """Two invocations on the same Zarr produce identical heatmap data."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr", seed=7)
    fig1 = plot_state_feature_clustermap(zarr_path)
    fig2 = plot_state_feature_clustermap(zarr_path)

    arr1 = _heatmap_array(fig1)
    arr2 = _heatmap_array(fig2)
    np.testing.assert_array_equal(arr1, arr2)
    plt.close("all")


def test_state_feature_clustermap_data_correctness(tmp_path: Path) -> None:
    """The heatmap data equals the collapsed-repeated-measure matrix up to
    seaborn's column z-scoring + dendrogram reordering."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    n_leiden = 6
    n_statistic = 3
    window_size = 4
    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        n_leiden_clusters=n_leiden,
        n_statistic=n_statistic,
        window_size=window_size,
        seed=13,
    )

    fig = plot_state_feature_clustermap(zarr_path, z_score=None)

    with xr.open_zarr(zarr_path) as ds:
        means = np.asarray(ds["leiden_cluster_means"].values, dtype=np.float64)
    collapsed_expected = means.reshape(n_leiden, window_size, n_statistic).mean(axis=1)

    rendered = _heatmap_array(fig)
    # The clustermap reorders rows/columns; check the set of column means
    # matches (this is order-invariant and pins the collapsing).
    expected_col_means = np.sort(collapsed_expected.mean(axis=0))
    rendered_col_means = np.sort(rendered.mean(axis=0))
    np.testing.assert_allclose(rendered_col_means, expected_col_means, rtol=1e-10, atol=1e-12)

    # Stronger check: the multiset of cell values must agree.
    np.testing.assert_allclose(
        np.sort(rendered.ravel()), np.sort(collapsed_expected.ravel()), rtol=1e-10, atol=1e-12
    )
    plt.close("all")


def test_state_feature_clustermap_save_path_roundtrip(tmp_path: Path) -> None:
    """`save_path` writes a non-empty PNG with a valid header."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr")
    out = tmp_path / "out.png"
    fig = plot_state_feature_clustermap(zarr_path, save_path=out)
    assert isinstance(fig, plt.Figure)
    assert _is_valid_png(out)
    plt.close("all")


def test_state_feature_clustermap_raises_on_too_many_states(tmp_path: Path) -> None:
    """More than ten distinct final states is refused (palette guard)."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        n_window_per_sim=40,
        n_final_states=11,
        seed=99,
    )
    # Sanity: confirm the synthetic Zarr really has 11 distinct states.
    with xr.open_zarr(zarr_path) as ds:
        assert np.unique(ds["cluster_labels"].values).size == 11
    with pytest.raises(ValueError, match="tab10"):
        plot_state_feature_clustermap(zarr_path)
    plt.close("all")


def test_state_feature_clustermap_raises_on_missing_leiden_cluster_means(
    tmp_path: Path,
) -> None:
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        drop_vars=("leiden_cluster_means",),
    )
    with pytest.raises(ValueError, match="leiden_cluster_means"):
        plot_state_feature_clustermap(zarr_path)
    plt.close("all")


def test_state_feature_clustermap_raises_on_missing_linkage_matrix(tmp_path: Path) -> None:
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        drop_vars=("linkage_matrix",),
    )
    with pytest.raises(ValueError, match="linkage_matrix"):
        plot_state_feature_clustermap(zarr_path)
    plt.close("all")


def test_state_feature_clustermap_raises_on_missing_statistic_coord(tmp_path: Path) -> None:
    """No `statistic` coord => cannot infer the window stride."""
    from tmelandscape.viz.trajectories import plot_state_feature_clustermap

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        drop_coords=("statistic",),
    )
    with pytest.raises(ValueError, match="statistic"):
        plot_state_feature_clustermap(zarr_path)
    plt.close("all")


# --- plot_trajectory_clustergram --------------------------------------------


def test_trajectory_clustergram_smoke(tmp_path: Path) -> None:
    """Returns a Figure with at least two axes (dendrogram + heatmap)."""
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr")
    fig = plot_trajectory_clustergram(zarr_path)
    assert len(fig.axes) >= 2
    plt.close("all")


def test_trajectory_clustergram_determinism(tmp_path: Path) -> None:
    """Two invocations on the same Zarr produce identical heatmap data."""
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr", seed=21)
    fig1 = plot_trajectory_clustergram(zarr_path)
    fig2 = plot_trajectory_clustergram(zarr_path)

    arr1 = _heatmap_array(fig1)
    arr2 = _heatmap_array(fig2)
    np.testing.assert_array_equal(arr1, arr2)
    plt.close("all")


def test_trajectory_clustergram_data_correctness(tmp_path: Path) -> None:
    """The heatmap's underlying matrix matches `cluster_labels` reshaped
    to (n_sim, n_window_per_sim), modulo row reordering by the dendrogram."""
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    n_sim = 5
    n_window_per_sim = 10
    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        n_sim=n_sim,
        n_window_per_sim=n_window_per_sim,
        n_final_states=4,
        seed=29,
    )
    fig = plot_trajectory_clustergram(zarr_path)

    with xr.open_zarr(zarr_path) as ds:
        labels = np.asarray(ds["cluster_labels"].values, dtype=np.int64)
    expected_matrix = labels.reshape(n_sim, n_window_per_sim)

    rendered = _heatmap_array(fig)
    assert rendered.shape == (n_sim, n_window_per_sim)

    # imshow renders the rank-encoded matrix; reconstruct ranks for the
    # expected matrix and compare as multisets per row (rows are reordered
    # by the dendrogram).
    unique_states = np.unique(labels)
    state_to_rank = {int(s): i for i, s in enumerate(unique_states.tolist())}
    expected_ranked = np.vectorize(state_to_rank.get)(expected_matrix).astype(rendered.dtype)

    rendered_sorted = np.sort(rendered.flatten())
    expected_sorted = np.sort(expected_ranked.flatten())
    np.testing.assert_array_equal(rendered_sorted, expected_sorted)

    # Each rendered row, treated as a sequence, must match exactly one
    # expected sim's sequence (no duplicates of rows across the matrix
    # except by coincidence under the seed).
    expected_rows = {tuple(row.tolist()) for row in expected_ranked}
    for row in rendered:
        assert tuple(row.tolist()) in expected_rows
    plt.close("all")


def test_trajectory_clustergram_save_path_roundtrip(tmp_path: Path) -> None:
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr")
    out = tmp_path / "out.png"
    fig = plot_trajectory_clustergram(zarr_path, save_path=out)
    assert isinstance(fig, plt.Figure)
    assert _is_valid_png(out)
    plt.close("all")


def test_trajectory_clustergram_raises_on_ragged_trajectories(tmp_path: Path) -> None:
    """We refuse ragged trajectories rather than NaN-padding."""
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(tmp_path / "cluster.zarr", ragged=True)
    with pytest.raises(ValueError, match="ragged"):
        plot_trajectory_clustergram(zarr_path)
    plt.close("all")


def test_trajectory_clustergram_raises_on_too_many_states(tmp_path: Path) -> None:
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        n_window_per_sim=40,
        n_final_states=11,
        seed=37,
    )
    with xr.open_zarr(zarr_path) as ds:
        assert np.unique(ds["cluster_labels"].values).size == 11
    with pytest.raises(ValueError, match="tab10"):
        plot_trajectory_clustergram(zarr_path)
    plt.close("all")


def test_trajectory_clustergram_raises_on_missing_cluster_labels(tmp_path: Path) -> None:
    from tmelandscape.viz.trajectories import plot_trajectory_clustergram

    zarr_path = _build_cluster_zarr(
        tmp_path / "cluster.zarr",
        drop_vars=("cluster_labels",),
    )
    with pytest.raises(ValueError, match="cluster_labels"):
        plot_trajectory_clustergram(zarr_path)
    plt.close("all")


# --- helpers ----------------------------------------------------------------


def _heatmap_array(fig: plt.Figure) -> np.ndarray:
    """Return the underlying data array of the figure's main heatmap.

    Both plot functions render their heatmap via ``ax.imshow`` (the
    clustergram and modern seaborn) or ``ax.pcolormesh`` (older seaborn).
    We scan every axes' images and ``QuadMesh`` collections and return the
    array with the largest 2D footprint, which is by construction the
    main heatmap (the colorbar's gradient and the row-colour strip are
    both far smaller).
    """
    candidates: list[np.ndarray] = []
    for ax in fig.axes:
        for img in ax.get_images():
            arr = np.asarray(img.get_array())
            if arr.size:
                candidates.append(arr)
        for coll in ax.collections:
            arr_obj = coll.get_array()
            if arr_obj is None:
                continue
            arr = np.asarray(arr_obj)
            if not arr.size:
                continue
            if arr.ndim == 1:
                # QuadMesh stores values flat. Recover (n_row, n_col) via the
                # collection's coordinates (Nx2 grid -> (n_row+1, n_col+1, 2)).
                coords = getattr(coll, "_coordinates", None)
                if coords is not None and coords.ndim == 3:
                    n_row = coords.shape[0] - 1
                    n_col = coords.shape[1] - 1
                    if n_row * n_col == arr.size:
                        arr = arr.reshape(n_row, n_col)
            candidates.append(arr)
    if not candidates:
        raise AssertionError("could not locate heatmap array on the figure")
    # Filter to genuine 2D heatmaps (>1 row AND >1 column); this excludes
    # the seaborn colorbar gradient (Nx1 or 1xN) and the row-colour strip
    # (n_row x 1). Pick the largest such candidate. Fall back to the
    # largest array overall if every candidate is degenerate.
    two_d = [a for a in candidates if a.ndim == 2 and a.shape[0] > 1 and a.shape[1] > 1]
    pool = two_d if two_d else candidates
    return max(pool, key=lambda a: a.size)
