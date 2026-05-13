"""Unit tests for ``tmelandscape.summarize.aggregate.build_ensemble_zarr``.

Stream B (the ensemble aggregator) is the only producer of the
``(simulation, timepoint, statistic)`` Zarr store consumed by step 3.5 /
step 4. These tests cover the happy path (round-trip via
``xarray.open_zarr``), the edge cases enumerated in
``tasks/03-summarize-implementation.md`` for Reviewer B2 (empty manifest,
ragged timepoints, non-default chunking), and the provenance contract
(``tmelandscape_version`` / ``manifest_hash`` / ``created_at_utc`` in
``.zattrs``, and the manifest hash is reproducible).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import tmelandscape
from tmelandscape.config.sweep import ParameterSpec, SweepConfig
from tmelandscape.sampling.manifest import SweepManifest, SweepRow
from tmelandscape.summarize.aggregate import build_ensemble_zarr
from tmelandscape.summarize.schema import ENSEMBLE_DIMS, manifest_to_coords

# --- fixture helpers ---------------------------------------------------------


def _build_manifest(n_param_combinations: int = 2, n_ic: int = 2) -> SweepManifest:
    """Build a minimal in-memory manifest with two scalar parameters."""
    config = SweepConfig(
        parameters=[
            ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0),
            ParameterSpec(name="cycle_rate", low=1e-4, high=1e-2, scale="log10"),
        ],
        n_parameter_samples=n_param_combinations,
        n_initial_conditions=n_ic,
        seed=42,
    )
    rows: list[SweepRow] = []
    for pc_id in range(n_param_combinations):
        # Distinct scaled parameter values per combination so the per-sim
        # coord arrays carry detectable signal.
        oxy = 0.5 + pc_id * 1.0
        cyc = 1e-3 * (pc_id + 1)
        for ic_id in range(n_ic):
            rows.append(
                SweepRow(
                    simulation_id=f"sim_{pc_id:06d}_ic_{ic_id:03d}",
                    parameter_combination_id=pc_id,
                    ic_id=ic_id,
                    parameter_values={"oxygen_uptake": oxy, "cycle_rate": cyc},
                    ic_path=f"ic_{ic_id:03d}.csv",
                )
            )
    return SweepManifest(
        config=config,
        initial_conditions_dir="initial_conditions",
        rows=rows,
    )


def _summary_frame(
    statistics: list[str],
    timepoints: list[int],
    *,
    base: float = 0.0,
) -> pd.DataFrame:
    """Long-form summary DataFrame: one row per (timepoint, statistic)."""
    rows: list[dict[str, float | int | str]] = []
    for tp in timepoints:
        for s_i, stat in enumerate(statistics):
            rows.append(
                {
                    "time_index": tp,
                    "time": float(tp) * 10.0,
                    "statistic": stat,
                    "value": base + tp * 100.0 + s_i,
                }
            )
    return pd.DataFrame(rows)


def _summary_frames_for(
    manifest: SweepManifest,
    statistics: list[str],
    timepoints: list[int],
) -> dict[str, pd.DataFrame]:
    """One identical-shape frame per manifest row."""
    return {
        row.simulation_id: _summary_frame(statistics, timepoints, base=float(i) * 1000.0)
        for i, row in enumerate(manifest.rows)
    }


# --- happy path / round-trip -------------------------------------------------


def test_build_ensemble_zarr_writes_store(tmp_path: Path) -> None:
    manifest = _build_manifest()  # 2 sims x 2 ICs = 4 rows
    statistics = ["cell_counts.tumor", "cell_counts.macrophage"]
    timepoints = [0, 1, 2]
    frames = _summary_frames_for(manifest, statistics, timepoints)

    out = build_ensemble_zarr(manifest, frames, tmp_path / "ensemble.zarr")
    assert out.is_dir()
    # Zarr v3 uses zarr.json at the group root; v2 used .zgroup. Either is
    # fine as long as xarray can re-open it.
    assert (out / "zarr.json").is_file() or (out / ".zgroup").is_file()


def test_round_trip_via_xarray_open_zarr(tmp_path: Path) -> None:
    manifest = _build_manifest()
    statistics = ["s_alpha", "s_beta"]
    timepoints = [0, 1, 2]
    frames = _summary_frames_for(manifest, statistics, timepoints)

    out = build_ensemble_zarr(manifest, frames, tmp_path / "ensemble.zarr")
    ds = xr.open_zarr(out)

    # Dims and sizes
    assert tuple(ds["value"].dims) == ENSEMBLE_DIMS
    assert ds.sizes["simulation"] == len(manifest.rows)
    assert ds.sizes["timepoint"] == len(timepoints)
    assert ds.sizes["statistic"] == len(statistics)

    # Index coords align with our inputs
    assert list(ds.coords["simulation"].values) == [r.simulation_id for r in manifest.rows]
    assert list(ds.coords["timepoint"].values) == timepoints
    assert sorted(ds.coords["statistic"].values.tolist()) == sorted(statistics)

    # Per-simulation coords from the manifest
    assert "parameter_oxygen_uptake" in ds.coords
    assert "parameter_cycle_rate" in ds.coords
    assert "ic_id" in ds.coords
    assert "parameter_combination_id" in ds.coords
    np.testing.assert_array_equal(
        ds.coords["ic_id"].values,
        np.array([r.ic_id for r in manifest.rows], dtype=np.int64),
    )

    # Values: reconstruct the expected (sim, tp, stat) cube directly from
    # the input frames and compare element-wise.
    stat_order = list(ds.coords["statistic"].values)
    expected = np.full(
        (len(manifest.rows), len(timepoints), len(stat_order)), np.nan, dtype=np.float64
    )
    for i, row in enumerate(manifest.rows):
        df = frames[row.simulation_id]
        for _, frame_row in df.iterrows():
            t_idx = timepoints.index(int(frame_row["time_index"]))
            s_idx = stat_order.index(str(frame_row["statistic"]))
            expected[i, t_idx, s_idx] = float(frame_row["value"])

    np.testing.assert_allclose(ds["value"].values, expected, rtol=0, atol=0)


def test_manifest_to_coords_alignment() -> None:
    manifest = _build_manifest()
    coords = manifest_to_coords(manifest)
    n = len(manifest.rows)
    assert coords["simulation"].shape == (n,)
    assert coords["ic_id"].shape == (n,)
    assert coords["parameter_combination_id"].shape == (n,)
    assert coords["parameter_oxygen_uptake"].shape == (n,)
    assert coords["parameter_cycle_rate"].shape == (n,)
    # ordering: same as manifest.rows
    assert [str(s) for s in coords["simulation"]] == [r.simulation_id for r in manifest.rows]


# --- edge cases --------------------------------------------------------------


def test_empty_manifest_produces_zero_sim_dim(tmp_path: Path) -> None:
    """Edge case 1: empty manifest -> zero-sized `simulation` dim, no crash."""
    config = SweepConfig(
        parameters=[ParameterSpec(name="alpha", low=0.0, high=1.0)],
        n_parameter_samples=1,
        n_initial_conditions=1,
        seed=0,
    )
    manifest = SweepManifest(config=config, initial_conditions_dir="ic", rows=[])

    out = build_ensemble_zarr(manifest, {}, tmp_path / "empty.zarr")
    ds = xr.open_zarr(out)
    assert ds.sizes["simulation"] == 0
    # timepoint / statistic also collapse to zero when no frames provided
    assert ds.sizes["timepoint"] == 0
    assert ds.sizes["statistic"] == 0
    # Even on a zero-row manifest the manifest-derived coords exist with the
    # right (zero-length) shape so the schema is stable.
    assert "parameter_alpha" in ds.coords
    assert ds.coords["parameter_alpha"].shape == (0,)


def test_ragged_timepoints_fill_with_nan(tmp_path: Path) -> None:
    """Edge case 2: one sim short by a timepoint -> NaN at that slot."""
    config = SweepConfig(
        parameters=[ParameterSpec(name="alpha", low=0.0, high=1.0)],
        n_parameter_samples=2,
        n_initial_conditions=1,
        seed=1,
    )
    manifest = SweepManifest(
        config=config,
        initial_conditions_dir="ic",
        rows=[
            SweepRow(
                simulation_id="sim_A",
                parameter_combination_id=0,
                ic_id=0,
                parameter_values={"alpha": 0.1},
                ic_path="ic_000.csv",
            ),
            SweepRow(
                simulation_id="sim_B",
                parameter_combination_id=1,
                ic_id=0,
                parameter_values={"alpha": 0.9},
                ic_path="ic_000.csv",
            ),
        ],
    )
    frames = {
        # sim_A reached all 3 timepoints
        "sim_A": _summary_frame(["s1"], [0, 1, 2], base=0.0),
        # sim_B only reached 2 (no timepoint 2)
        "sim_B": _summary_frame(["s1"], [0, 1], base=10.0),
    }
    out = build_ensemble_zarr(manifest, frames, tmp_path / "ragged.zarr")
    ds = xr.open_zarr(out)

    assert ds.sizes["timepoint"] == 3
    assert list(ds.coords["timepoint"].values) == [0, 1, 2]

    sim_a_series = ds["value"].sel(simulation="sim_A", statistic="s1").values
    sim_b_series = ds["value"].sel(simulation="sim_B", statistic="s1").values

    assert not np.any(np.isnan(sim_a_series))
    # sim_B is NaN at timepoint 2 (index 2), finite elsewhere
    assert np.isnan(sim_b_series[2])
    assert np.all(np.isfinite(sim_b_series[:2]))


def test_chunking_one_chunk_per_simulation(tmp_path: Path) -> None:
    """Edge case 3: chunk_simulations=1 -> one chunk per sim along that axis."""
    manifest = _build_manifest()  # 4 sims
    frames = _summary_frames_for(manifest, ["s1", "s2"], [0, 1])

    out = build_ensemble_zarr(
        manifest,
        frames,
        tmp_path / "chunked.zarr",
        chunk_simulations=1,
        chunk_timepoints=-1,
        chunk_statistics=-1,
    )

    # Re-opening via xarray with chunks={} reflects the on-disk chunk grid.
    ds = xr.open_zarr(out, chunks={})
    value_chunks = ds["value"].chunks
    assert value_chunks is not None
    # Per-axis chunking: 4 chunks of size 1 along `simulation`, one chunk
    # along each of `timepoint` / `statistic`.
    assert value_chunks[0] == (1, 1, 1, 1)
    assert value_chunks[1] == (2,)
    assert value_chunks[2] == (2,)


def test_chunk_simulations_oversized_clamps_to_axis(tmp_path: Path) -> None:
    """``chunk_simulations=32`` on 4 sims should not produce empty trailing chunks."""
    manifest = _build_manifest()
    frames = _summary_frames_for(manifest, ["s1"], [0])

    out = build_ensemble_zarr(
        manifest,
        frames,
        tmp_path / "clamped.zarr",
        chunk_simulations=32,
    )
    ds = xr.open_zarr(out, chunks={})
    value_chunks = ds["value"].chunks
    assert value_chunks is not None
    assert value_chunks[0] == (4,)


# --- provenance --------------------------------------------------------------


def test_provenance_attrs_present_and_manifest_hash_reproducible(
    tmp_path: Path,
) -> None:
    manifest = _build_manifest()
    frames = _summary_frames_for(manifest, ["s1", "s2"], [0, 1, 2])

    out = build_ensemble_zarr(manifest, frames, tmp_path / "with_provenance.zarr")
    ds = xr.open_zarr(out)

    assert ds.attrs.get("tmelandscape_version") == tmelandscape.__version__
    assert "manifest_hash" in ds.attrs
    assert "created_at_utc" in ds.attrs

    # Recompute the hash from the manifest itself and confirm equality.
    expected_hash = hashlib.sha256(manifest.model_dump_json().encode("utf-8")).hexdigest()
    assert ds.attrs["manifest_hash"] == expected_hash

    # created_at_utc must parse as an ISO-8601 datetime.
    from datetime import datetime

    parsed = datetime.fromisoformat(str(ds.attrs["created_at_utc"]))
    assert parsed.tzinfo is not None


def test_provenance_includes_summarize_config_when_provided(tmp_path: Path) -> None:
    """If a SummarizeConfig is passed, its JSON dump lands in the .zattrs."""

    class _FakeConfig:
        """Stand-in for the real ``SummarizeConfig`` (Stream C, not yet landed).

        ``build_ensemble_zarr`` only needs ``model_dump_json``; anything that
        supplies that method should be serialised verbatim.
        """

        def model_dump_json(self) -> str:
            return json.dumps({"statistics": ["s1", "s2"], "include_dead_cells": False})

    manifest = _build_manifest()
    frames = _summary_frames_for(manifest, ["s1"], [0])
    out = build_ensemble_zarr(
        manifest,
        frames,
        tmp_path / "with_config.zarr",
        config=_FakeConfig(),  # type: ignore[arg-type]
    )
    ds = xr.open_zarr(out)
    assert "summarize_config" in ds.attrs
    parsed = json.loads(str(ds.attrs["summarize_config"]))
    assert parsed["statistics"] == ["s1", "s2"]


# --- argument validation -----------------------------------------------------


def test_chunk_zero_rejected(tmp_path: Path) -> None:
    manifest = _build_manifest()
    frames = _summary_frames_for(manifest, ["s1"], [0])
    with pytest.raises(ValueError, match="positive integer or -1"):
        build_ensemble_zarr(manifest, frames, tmp_path / "bad.zarr", chunk_simulations=0)
