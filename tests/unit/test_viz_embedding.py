"""Unit tests for ``tmelandscape.viz.embedding``.

Covers the six public surfaces in the Stream A contract
(``tasks/07-visualisation-implementation.md``):

* :class:`~tmelandscape.viz.embedding.UMAPResult`
* :func:`~tmelandscape.viz.embedding.fit_umap`
* :func:`~tmelandscape.viz.embedding.plot_state_umap`
* :func:`~tmelandscape.viz.embedding.plot_time_umap`
* :func:`~tmelandscape.viz.embedding.plot_feature_umap`
* :func:`~tmelandscape.viz.embedding.plot_trajectory_umap`
* :func:`~tmelandscape.viz.embedding.plot_state_umap_with_vector_field`

The fixture is a small synthetic cluster Zarr (5 sims x 10 windows x 6
clusters x 3 features) built with a deterministic seed; every test closes
all figures at the end to keep the matplotlib state stack from growing.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as _mpl

_mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
import xarray as xr

from tmelandscape.viz.embedding import (
    UMAPResult,
    fit_umap,
    plot_feature_umap,
    plot_state_umap,
    plot_state_umap_with_vector_field,
    plot_time_umap,
    plot_trajectory_umap,
)

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# --- fixture helpers --------------------------------------------------------


def _make_cluster_zarr(
    path: Path,
    *,
    n_sims: int = 5,
    n_windows_per_sim: int = 10,
    n_states: int = 6,
    n_features: int = 3,
    n_statistics: int = 4,
    seed: int = 0,
) -> Path:
    """Build a small cluster-like Zarr at ``path`` and return the path.

    Layout mirrors what :func:`tmelandscape.cluster.cluster_ensemble`
    writes: an ``embedding`` (window, embedding_feature) array, a
    ``window_averages`` (window, statistic) array, ``cluster_labels``
    (window,), plus the per-window coords ``simulation_id``,
    ``window_index_in_sim``, ``start_timepoint``, ``end_timepoint``.
    """
    rng = np.random.default_rng(seed)
    total_windows = n_sims * n_windows_per_sim

    embedding = rng.standard_normal(size=(total_windows, n_features)).astype(np.float64)
    window_averages = rng.standard_normal(size=(total_windows, n_statistics)).astype(np.float64)

    sim_idx = np.repeat(np.arange(n_sims), n_windows_per_sim)
    sim_ids = np.array([f"sim_{i:02d}" for i in sim_idx])
    window_index_in_sim = np.tile(np.arange(n_windows_per_sim, dtype=np.int64), n_sims)
    start_timepoint = window_index_in_sim.astype(np.int64) * 5
    end_timepoint = start_timepoint + 4

    # Spread labels deterministically across the (n_states) states so we
    # get coverage on every state-coloured panel. Trajectory plots care
    # about consecutive same-state runs; we make each sim spend several
    # consecutive steps in each state so the LCSS-3 path produces
    # non-empty quiver populations.
    labels = np.zeros(total_windows, dtype=np.int64)
    for s in range(n_sims):
        for w in range(n_windows_per_sim):
            labels[s * n_windows_per_sim + w] = (w * n_states // n_windows_per_sim) + 1

    stat_names = np.array([f"stat_{j}" for j in range(n_statistics)])
    feature_index = np.arange(n_features, dtype=np.int64)
    window_index = np.arange(total_windows, dtype=np.int64)

    ds = xr.Dataset(
        data_vars={
            "embedding": (("window", "embedding_feature"), embedding),
            "window_averages": (("window", "statistic"), window_averages),
            "cluster_labels": (("window",), labels),
        },
        coords={
            "window": ("window", window_index),
            "embedding_feature": ("embedding_feature", feature_index),
            "statistic": ("statistic", stat_names),
            "simulation_id": ("window", sim_ids),
            "window_index_in_sim": ("window", window_index_in_sim),
            "start_timepoint": ("window", start_timepoint),
            "end_timepoint": ("window", end_timepoint),
        },
    )
    ds.to_zarr(path, mode="w")
    return path


@pytest.fixture
def cluster_zarr(tmp_path: Path) -> Path:
    return _make_cluster_zarr(tmp_path / "cluster.zarr")


@pytest.fixture
def umap_result(cluster_zarr: Path) -> UMAPResult:
    return fit_umap(cluster_zarr, n_neighbors=5, random_state=42)


# --- fit_umap ---------------------------------------------------------------


def test_fit_umap_returns_expected_shape(cluster_zarr: Path) -> None:
    result = fit_umap(cluster_zarr, n_neighbors=5, random_state=42)
    assert isinstance(result, UMAPResult)
    assert result.coordinates.shape == (50, 2)
    assert result.coordinates.dtype == np.float64
    assert result.n_neighbors == 5
    assert result.min_dist == 0.1
    assert result.random_state == 42
    assert Path(result.source_input_zarr) == cluster_zarr.resolve()
    plt.close("all")


def test_fit_umap_is_deterministic(cluster_zarr: Path) -> None:
    a = fit_umap(cluster_zarr, n_neighbors=5, random_state=7)
    b = fit_umap(cluster_zarr, n_neighbors=5, random_state=7)
    np.testing.assert_array_equal(a.coordinates, b.coordinates)
    plt.close("all")


def test_fit_umap_raises_on_missing_embedding(tmp_path: Path) -> None:
    path = tmp_path / "broken.zarr"
    ds = xr.Dataset(
        data_vars={"other": (("x",), np.arange(3))},
        coords={"x": ("x", np.arange(3))},
    )
    ds.to_zarr(path, mode="w")
    with pytest.raises(ValueError, match="no 'embedding' data variable"):
        fit_umap(path)
    plt.close("all")


# --- plot_state_umap (TNBC-2b) ---------------------------------------------


def test_plot_state_umap_smoke(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig = plot_state_umap(umap_result, cluster_zarr)
    assert len(fig.axes) == 1
    ax = fig.axes[0]
    # One scatter PathCollection per distinct state (6 in the fixture).
    assert len(ax.collections) == 6
    assert ax.get_xlabel() == "UMAP 1"
    assert ax.get_ylabel() == "UMAP 2"
    plt.close("all")


def test_plot_state_umap_deterministic(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig_a = plot_state_umap(umap_result, cluster_zarr)
    fig_b = plot_state_umap(umap_result, cluster_zarr)
    ax_a, ax_b = fig_a.axes[0], fig_b.axes[0]
    assert ax_a.get_xlim() == ax_b.get_xlim()
    assert ax_a.get_ylim() == ax_b.get_ylim()
    for coll_a, coll_b in zip(ax_a.collections, ax_b.collections, strict=True):
        np.testing.assert_array_equal(coll_a.get_offsets(), coll_b.get_offsets())
    plt.close("all")


def test_plot_state_umap_save_round_trip(
    umap_result: UMAPResult, cluster_zarr: Path, tmp_path: Path
) -> None:
    out = tmp_path / "state.png"
    plot_state_umap(umap_result, cluster_zarr, save_path=out)
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 0
    assert data[:8] == PNG_HEADER
    plt.close("all")


def test_plot_state_umap_raises_when_more_than_ten_states(
    tmp_path: Path,
) -> None:
    path = _make_cluster_zarr(
        tmp_path / "many_states.zarr",
        n_sims=4,
        n_windows_per_sim=12,
        n_states=11,
    )
    result = fit_umap(path, n_neighbors=5, random_state=0)
    with pytest.raises(ValueError, match="more than tab10"):
        plot_state_umap(result, path)
    plt.close("all")


def test_plot_state_umap_accepts_user_palette_for_many_states(
    tmp_path: Path,
) -> None:
    path = _make_cluster_zarr(
        tmp_path / "many_states.zarr",
        n_sims=4,
        n_windows_per_sim=12,
        n_states=11,
    )
    result = fit_umap(path, n_neighbors=5, random_state=0)
    palette = {i: f"C{i % 10}" for i in range(1, 12)}
    fig = plot_state_umap(result, path, state_palette=palette)
    assert len(fig.axes) == 1
    plt.close("all")


# --- plot_time_umap (TNBC-2c) -----------------------------------------------


def test_plot_time_umap_smoke(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig = plot_time_umap(umap_result, cluster_zarr)
    # One main axes + one colourbar axes.
    assert len(fig.axes) == 2
    plt.close("all")


def test_plot_time_umap_colour_values_match_mean_time(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    fig = plot_time_umap(umap_result, cluster_zarr)
    ax = fig.axes[0]
    scatter = ax.collections[0]
    colours = np.asarray(scatter.get_array())

    with xr.open_zarr(cluster_zarr) as ds:
        start = np.asarray(ds["start_timepoint"].values, dtype=np.float64)
        end = np.asarray(ds["end_timepoint"].values, dtype=np.float64)
    expected = 0.5 * (start + end)
    np.testing.assert_allclose(colours, expected)
    plt.close("all")


def test_plot_time_umap_save_round_trip(
    umap_result: UMAPResult, cluster_zarr: Path, tmp_path: Path
) -> None:
    out = tmp_path / "time.png"
    plot_time_umap(umap_result, cluster_zarr, save_path=out)
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 0
    assert data[:8] == PNG_HEADER
    plt.close("all")


# --- plot_feature_umap (LCSS-4 / TNBC-2e) -----------------------------------


def test_plot_feature_umap_smoke(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig = plot_feature_umap(
        umap_result,
        cluster_zarr,
        features=["stat_0", "stat_1", "stat_2"],
    )
    # 3 main axes + 3 colourbar axes
    assert len(fig.axes) == 6
    plt.close("all")


def test_plot_feature_umap_raises_on_missing_feature(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    with pytest.raises(ValueError, match="not present"):
        plot_feature_umap(
            umap_result,
            cluster_zarr,
            features=["stat_0", "stat_missing"],
        )
    plt.close("all")


def test_plot_feature_umap_raises_on_empty_features(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        plot_feature_umap(umap_result, cluster_zarr, features=[])
    plt.close("all")


def test_plot_feature_umap_save_round_trip(
    umap_result: UMAPResult, cluster_zarr: Path, tmp_path: Path
) -> None:
    out = tmp_path / "feature.png"
    plot_feature_umap(
        umap_result,
        cluster_zarr,
        features=["stat_0", "stat_1"],
        save_path=out,
    )
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 0
    assert data[:8] == PNG_HEADER
    plt.close("all")


def test_plot_feature_umap_deterministic(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig_a = plot_feature_umap(umap_result, cluster_zarr, features=["stat_0"])
    fig_b = plot_feature_umap(umap_result, cluster_zarr, features=["stat_0"])
    ax_a, ax_b = fig_a.axes[0], fig_b.axes[0]
    assert ax_a.get_xlim() == ax_b.get_xlim()
    assert ax_a.get_ylim() == ax_b.get_ylim()
    np.testing.assert_array_equal(
        ax_a.collections[0].get_offsets(),
        ax_b.collections[0].get_offsets(),
    )
    plt.close("all")


# --- plot_trajectory_umap (TNBC-2d) -----------------------------------------


def test_plot_trajectory_umap_smoke(umap_result: UMAPResult, cluster_zarr: Path) -> None:
    fig = plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=["sim_00", "sim_02"])
    ax = fig.axes[0]
    # Two trajectory polylines on top of the background scatter.
    assert len(ax.lines) == 2
    plt.close("all")


def test_plot_trajectory_umap_raises_on_missing_sim(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    with pytest.raises(ValueError, match="not present"):
        plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=["sim_00", "no_such_sim"])
    plt.close("all")


def test_plot_trajectory_umap_raises_on_empty_sim_ids(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=[])
    plt.close("all")


def test_plot_trajectory_umap_save_round_trip(
    umap_result: UMAPResult, cluster_zarr: Path, tmp_path: Path
) -> None:
    out = tmp_path / "traj.png"
    plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=["sim_01"], save_path=out)
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 0
    assert data[:8] == PNG_HEADER
    plt.close("all")


def test_plot_trajectory_umap_polyline_sorted_by_window_index(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    fig = plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=["sim_00"])
    line = fig.axes[0].lines[0]
    xy = np.column_stack([line.get_xdata(), line.get_ydata()])
    # The polyline should pass through exactly the 10 windows of sim_00 in
    # window-index order, which equals the first 10 rows of the UMAP
    # coordinates by construction of the fixture.
    np.testing.assert_allclose(xy, umap_result.coordinates[:10])
    plt.close("all")


# --- plot_state_umap_with_vector_field (LCSS-3) -----------------------------


def test_plot_state_umap_with_vector_field_smoke(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    fig = plot_state_umap_with_vector_field(
        umap_result, cluster_zarr, grid_size=5, show_density_contours=False
    )
    assert len(fig.axes) == 1
    ax = fig.axes[0]
    # 6 scatter PathCollections (one per state).
    n_scatter = sum(1 for c in ax.collections if np.asarray(c.get_offsets()).shape[0] > 0)
    assert n_scatter >= 6
    # At least one quiver PolyCollection must exist; otherwise the LCSS-3
    # vector field silently rendered no arrows (would mask an algorithm
    # regression). Reviewer A2 R2.
    from matplotlib.collections import PolyCollection

    assert any(isinstance(c, PolyCollection) for c in ax.collections), (
        "no quiver PolyCollection rendered — the vector field is empty"
    )
    plt.close("all")


def test_plot_state_umap_with_vector_field_with_contours(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    # Run with contours and without; assert the contours-on figure adds
    # collections the contours-off figure didn't have (Reviewer A2 R1).
    # `sns.kdeplot` adds a `QuadContourSet` (which lives in `ax.collections`
    # in recent matplotlib), so we count *any* new collection rather than
    # pinning to a specific artist type.
    fig_off = plot_state_umap_with_vector_field(
        umap_result, cluster_zarr, grid_size=5, show_density_contours=False
    )
    n_coll_off = len(fig_off.axes[0].collections)
    plt.close(fig_off)

    fig_on = plot_state_umap_with_vector_field(
        umap_result, cluster_zarr, grid_size=5, show_density_contours=True
    )
    assert len(fig_on.axes) == 1
    n_coll_on = len(fig_on.axes[0].collections)
    assert n_coll_on > n_coll_off, (
        f"contours=True did not add any new artists (off={n_coll_off}, on={n_coll_on})"
    )
    plt.close("all")


def test_plot_state_umap_with_vector_field_save_round_trip(
    umap_result: UMAPResult, cluster_zarr: Path, tmp_path: Path
) -> None:
    out = tmp_path / "lcss3.png"
    plot_state_umap_with_vector_field(
        umap_result,
        cluster_zarr,
        grid_size=5,
        show_density_contours=False,
        save_path=out,
    )
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 0
    assert data[:8] == PNG_HEADER
    plt.close("all")


def test_plot_state_umap_with_vector_field_rejects_bad_grid_size(
    umap_result: UMAPResult, cluster_zarr: Path
) -> None:
    with pytest.raises(ValueError, match=">= 2"):
        plot_state_umap_with_vector_field(umap_result, cluster_zarr, grid_size=1)
    plt.close("all")
