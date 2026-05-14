"""Unit tests for ``tmelandscape.landscape.join_manifest_cluster``.

The join helper is the Phase 6 prerequisite for the two parameter-state
figures (LCSS-6, TNBC-6c). Tests cover:

* All manifest sim ids surface on the output index.
* ``terminal_cluster_label`` is the mode of the last
  ``terminal_window_count`` window labels.
* ``terminal_window_count=1`` returns the last window's label only.
* A mismatched sim set on either side raises ``ValueError``.
* ``terminal_window_count < 1`` raises ``ValueError``.
* Every manifest parameter shows up as a ``parameter_<name>`` column.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from tmelandscape.config.sweep import ParameterSpec, SweepConfig
from tmelandscape.landscape import join_manifest_cluster
from tmelandscape.sampling.manifest import SweepManifest, SweepRow


def _build_manifest(sim_ids: list[str]) -> SweepManifest:
    config = SweepConfig(
        parameters=[
            ParameterSpec(name="alpha", low=0.0, high=1.0),
            ParameterSpec(name="beta", low=0.1, high=10.0, scale="log10"),
        ],
        n_parameter_samples=len(sim_ids),
        n_initial_conditions=1,
        seed=0,
    )
    rows = [
        SweepRow(
            simulation_id=sid,
            parameter_combination_id=i,
            ic_id=0,
            parameter_values={"alpha": 0.1 * i, "beta": 1.0 + i},
            ic_path=f"ic_{i:03d}.csv",
        )
        for i, sid in enumerate(sim_ids)
    ]
    return SweepManifest(
        config=config,
        initial_conditions_dir="ic_dir",
        rows=rows,
    )


def _build_cluster_zarr(
    path: Path,
    *,
    sim_ids: list[str],
    labels_per_sim: dict[str, list[int]],
) -> None:
    rows_sim: list[str] = []
    rows_win: list[int] = []
    rows_label: list[int] = []
    for sid in sim_ids:
        labels = labels_per_sim[sid]
        for w, lbl in enumerate(labels):
            rows_sim.append(sid)
            rows_win.append(w)
            rows_label.append(lbl)
    ds = xr.Dataset(
        data_vars={
            "cluster_labels": (("window",), np.asarray(rows_label, dtype=np.int64)),
        },
        coords={
            "simulation_id": (("window",), np.asarray(rows_sim, dtype=np.str_)),
            "window_index_in_sim": (("window",), np.asarray(rows_win, dtype=np.int64)),
        },
    )
    ds.to_zarr(path, mode="w")


def test_join_returns_all_manifest_sim_ids(tmp_path: Path) -> None:
    sim_ids = ["sim_a", "sim_b", "sim_c"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={sid: [1] * 10 for sid in sim_ids},
    )

    joined = join_manifest_cluster(manifest_path, cluster_path)
    assert sorted(joined.index.tolist()) == sorted(sim_ids)


def test_terminal_label_is_mode_of_last_n_windows(tmp_path: Path) -> None:
    sim_ids = ["sim_a"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={"sim_a": [1, 1, 1, 1, 1, 2, 3, 3, 3, 3]},
    )

    joined = join_manifest_cluster(manifest_path, cluster_path, terminal_window_count=5)
    assert int(joined.loc["sim_a", "terminal_cluster_label"]) == 3


def test_terminal_window_count_one_returns_last_label(tmp_path: Path) -> None:
    sim_ids = ["sim_a"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={"sim_a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 7]},
    )

    joined = join_manifest_cluster(manifest_path, cluster_path, terminal_window_count=1)
    assert int(joined.loc["sim_a", "terminal_cluster_label"]) == 7


def test_n_windows_matches_input(tmp_path: Path) -> None:
    sim_ids = ["sim_a", "sim_b"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={"sim_a": [1] * 12, "sim_b": [2] * 7},
    )

    joined = join_manifest_cluster(manifest_path, cluster_path)
    assert int(joined.loc["sim_a", "n_windows"]) == 12
    assert int(joined.loc["sim_b", "n_windows"]) == 7


def test_mismatched_sim_set_raises_value_error(tmp_path: Path) -> None:
    manifest = _build_manifest(["sim_a", "sim_b"])
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=["sim_a", "sim_x"],
        labels_per_sim={"sim_a": [1] * 5, "sim_x": [2] * 5},
    )

    # The error message must name both the offending manifest-only sim and
    # the offending cluster-only sim so callers can diagnose which side is
    # stale. Reviewer C2 R5.
    with pytest.raises(ValueError) as excinfo:
        join_manifest_cluster(manifest_path, cluster_path)
    msg = str(excinfo.value)
    assert "mismatched simulation_id sets" in msg
    assert "sim_b" in msg, f"manifest-only sim not named in error: {msg!r}"
    assert "sim_x" in msg, f"cluster-only sim not named in error: {msg!r}"


def test_terminal_window_count_zero_raises(tmp_path: Path) -> None:
    sim_ids = ["sim_a"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={"sim_a": [1] * 5},
    )

    with pytest.raises(ValueError, match="terminal_window_count must be >= 1"):
        join_manifest_cluster(manifest_path, cluster_path, terminal_window_count=0)


def test_parameter_columns_surface_on_output(tmp_path: Path) -> None:
    sim_ids = ["sim_a", "sim_b", "sim_c"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    _build_cluster_zarr(
        cluster_path,
        sim_ids=sim_ids,
        labels_per_sim={sid: [1] * 5 for sid in sim_ids},
    )

    joined = join_manifest_cluster(manifest_path, cluster_path)
    assert "parameter_alpha" in joined.columns
    assert "parameter_beta" in joined.columns
    assert float(joined.loc["sim_a", "parameter_alpha"]) == 0.0
    assert float(joined.loc["sim_b", "parameter_alpha"]) == pytest.approx(0.1)


def test_join_is_robust_to_shuffled_window_order(tmp_path: Path) -> None:
    """Cluster Zarr rows arrive in arbitrary order; the join must sort
    by ``window_index_in_sim`` per sim before taking the terminal mode."""
    sim_ids = ["sim_a"]
    manifest = _build_manifest(sim_ids)
    manifest_path = tmp_path / "sweep.json"
    manifest.save(manifest_path)

    cluster_path = tmp_path / "cluster.zarr"
    # Shuffle the (win, label) pairs so the trailing windows are not at
    # the tail of the underlying array.
    sim = ["sim_a"] * 10
    win = [9, 8, 7, 6, 5, 0, 1, 2, 3, 4]
    labels = [3, 3, 3, 3, 3, 1, 1, 1, 1, 1]
    ds = xr.Dataset(
        data_vars={"cluster_labels": (("window",), np.asarray(labels, dtype=np.int64))},
        coords={
            "simulation_id": (("window",), np.asarray(sim, dtype=np.str_)),
            "window_index_in_sim": (("window",), np.asarray(win, dtype=np.int64)),
        },
    )
    ds.to_zarr(cluster_path, mode="w")

    joined = join_manifest_cluster(manifest_path, cluster_path, terminal_window_count=3)
    assert int(joined.loc["sim_a", "terminal_cluster_label"]) == 3
