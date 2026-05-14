"""Unit tests for ``tmelandscape.normalize.normalize_ensemble``.

These tests focus on the Zarr orchestrator's contract (set down in
``tasks/04-normalize-implementation.md`` and ADR 0006):

* The input Zarr is byte-immutable across a call. The orchestrator opens it
  read-only and never mutates the on-disk bytes.
* The output Zarr fails fast (``FileExistsError``) if it already exists.
* ``drop_columns`` removes those entries from the ``statistic`` coord and
  from the value arrays — and both the raw ``value`` and the new
  ``value_normalized`` array land in the output.
* Provenance ``.zattrs`` (``normalize_config``, ``created_at_utc``,
  ``tmelandscape_version``; ``source_manifest_hash`` if present in input)
  survive the round trip.
* Per-simulation coords (``parameter_*``, ``ic_id``, ``parameter_combination_id``)
  pass through unchanged.
* With ``preserve_time_effect=True``, the per-(timepoint, statistic) mean
  of ``value_normalized`` is approximately equal to the per-(timepoint,
  statistic) mean of ``value`` (reference behaviour).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import xarray as xr

import tmelandscape
from tmelandscape.normalize import normalize_ensemble

# --- helpers ----------------------------------------------------------------


def _try_import_normalize_config() -> Any:
    """Import Stream C's NormalizeConfig if available, else return None."""
    try:
        from tmelandscape.config.normalize import (
            NormalizeConfig,  # type: ignore[attr-defined]
        )
    except ImportError:
        return None
    return NormalizeConfig


def _make_config(
    *,
    strategy: str = "within_timestep",
    preserve_time_effect: bool = True,
    drop_columns: list[str] | None = None,
    fill_nan_with: float = 0.0,
    output_variable: str = "value_normalized",
) -> Any:
    """Construct a NormalizeConfig (or duck-typed stand-in if Stream C
    has not landed yet).

    The orchestrator only reads attributes off this object plus
    ``model_dump_json`` — duck typing works for both halves of the
    buddy-pair handoff.
    """
    cls = _try_import_normalize_config()
    drop_cols = list(drop_columns) if drop_columns is not None else []
    if cls is not None:
        return cls(
            strategy=strategy,
            preserve_time_effect=preserve_time_effect,
            drop_columns=drop_cols,
            fill_nan_with=fill_nan_with,
            output_variable=output_variable,
        )
    # Duck-typed fallback that mimics the Pydantic BaseModel surface we use:
    # attribute access for fields, and `model_dump_json` for provenance.
    payload = {
        "strategy": strategy,
        "preserve_time_effect": preserve_time_effect,
        "drop_columns": drop_cols,
        "fill_nan_with": fill_nan_with,
        "output_variable": output_variable,
    }

    class _ConfigStub(SimpleNamespace):
        def model_dump_json(self) -> str:
            return json.dumps(payload)

        def model_dump(self) -> dict[str, Any]:
            return dict(payload)

    return _ConfigStub(**payload)


def _build_input_zarr(
    path: Path,
    *,
    n_sim: int = 2,
    n_tp: int = 3,
    n_stat: int = 4,
    statistic_names: list[str] | None = None,
    include_source_hash: bool = True,
    seed: int = 0,
) -> dict[str, Any]:
    """Build a tiny ensemble Zarr mirroring Stream B's aggregator output.

    Returns a dict carrying the canonical numpy arrays so tests can compare
    the round-tripped result without re-deriving them.
    """
    if statistic_names is None:
        statistic_names = [f"stat_{i}" for i in range(n_stat)]
    assert len(statistic_names) == n_stat

    rng = np.random.default_rng(seed)
    # Non-degenerate values so the within-timestep transform has signal.
    # Use a positive-skewed distribution to make Yeo-Johnson do meaningful
    # work but stay well-behaved (no NaN/inf).
    value = rng.lognormal(mean=0.0, sigma=0.5, size=(n_sim, n_tp, n_stat)).astype(np.float64)

    simulation_ids = np.array([f"sim_{i:03d}" for i in range(n_sim)], dtype=np.str_)
    timepoints = np.arange(n_tp, dtype=np.int64)
    statistics = np.array(statistic_names, dtype=np.str_)
    ic_ids = np.arange(n_sim, dtype=np.int64)
    pc_ids = np.zeros(n_sim, dtype=np.int64)
    param_a = rng.uniform(0.0, 1.0, size=n_sim).astype(np.float64)
    param_b = rng.uniform(1.0, 10.0, size=n_sim).astype(np.float64)

    ds = xr.Dataset(
        data_vars={"value": (("simulation", "timepoint", "statistic"), value)},
        coords={
            "simulation": simulation_ids,
            "timepoint": timepoints,
            "statistic": statistics,
            "ic_id": ("simulation", ic_ids),
            "parameter_combination_id": ("simulation", pc_ids),
            "parameter_alpha": ("simulation", param_a),
            "parameter_beta": ("simulation", param_b),
        },
    )
    if include_source_hash:
        ds.attrs["manifest_hash"] = "deadbeef" * 8  # fake but well-formed hex
    ds.attrs["tmelandscape_version"] = tmelandscape.__version__

    ds.to_zarr(path, mode="w")
    return {
        "value": value,
        "simulation_ids": simulation_ids,
        "timepoints": timepoints,
        "statistics": statistics,
        "ic_ids": ic_ids,
        "pc_ids": pc_ids,
        "param_a": param_a,
        "param_b": param_b,
    }


def _hash_store(store_path: Path) -> tuple[dict[str, str], int]:
    """sha256-hash every file inside a Zarr store, recursively.

    Returns (path -> hex digest, file count). The mapping key is the
    POSIX-style relative path inside the store so a comparison fails loudly
    even if a file is added or removed (not just mutated).
    """
    if not store_path.is_dir():
        raise AssertionError(f"expected a directory store at {store_path!s}")
    hashes: dict[str, str] = {}
    for p in sorted(store_path.rglob("*")):
        if p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            hashes[p.relative_to(store_path).as_posix()] = digest
    return hashes, len(hashes)


# --- happy path -------------------------------------------------------------


def test_round_trip_via_xarray_open_zarr(tmp_path: Path) -> None:
    """Build a tiny Zarr, normalise it, and verify the output schema."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path)

    cfg = _make_config()
    out = normalize_ensemble(input_path, output_path, config=cfg)
    assert out == output_path.resolve()
    assert out.is_dir()

    ds = xr.open_zarr(out)

    # Dims and sizes match the input
    assert tuple(ds["value"].dims) == ("simulation", "timepoint", "statistic")
    assert ds.sizes["simulation"] == 2
    assert ds.sizes["timepoint"] == 3
    assert ds.sizes["statistic"] == 4

    # Index coords mirror the input
    np.testing.assert_array_equal(
        ds.coords["simulation"].values.astype(str), truth["simulation_ids"].astype(str)
    )
    np.testing.assert_array_equal(
        ds.coords["timepoint"].values.astype(np.int64), truth["timepoints"]
    )
    np.testing.assert_array_equal(
        ds.coords["statistic"].values.astype(str), truth["statistics"].astype(str)
    )

    # Both the raw value and the normalised value variables exist
    assert "value" in ds.data_vars
    assert "value_normalized" in ds.data_vars
    np.testing.assert_allclose(ds["value"].values, truth["value"], rtol=0, atol=0)

    # Output values are finite (Yeo-Johnson on positive log-normal data
    # plus z-score plus mean-restore should never produce NaN).
    assert np.all(np.isfinite(ds["value_normalized"].values))


# --- input immutability -----------------------------------------------------


def test_input_zarr_byte_immutable(tmp_path: Path) -> None:
    """The crown jewel: every byte inside the input store survives the call.

    Strategy: walk the store recursively and sha256-hash every file. The
    hash map must compare byte-equal before and after the orchestrator runs.
    Verifies both "file content unchanged" and "file set unchanged" (no
    surprise additions or deletions).
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=3, n_tp=4, n_stat=5)

    hashes_before, count_before = _hash_store(input_path)
    assert count_before > 0, "fixture should have produced at least one file"

    cfg = _make_config()
    normalize_ensemble(input_path, output_path, config=cfg)

    hashes_after, count_after = _hash_store(input_path)
    assert count_before == count_after, (
        f"file count changed: {count_before} -> {count_after}; "
        f"added or removed files {set(hashes_after) ^ set(hashes_before)}"
    )
    assert hashes_before == hashes_after, "at least one input file's bytes changed"


# --- output pre-existence ---------------------------------------------------


def test_output_zarr_exists_raises_file_exists_error(tmp_path: Path) -> None:
    """If output_zarr already exists, raise FileExistsError before opening
    the input — no partial writes, no side effects on input bytes.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)
    # Pre-create the output as an empty directory (simulating a stale store
    # left behind by a previous aborted run).
    output_path.mkdir()

    hashes_before, _ = _hash_store(input_path)
    cfg = _make_config()
    with pytest.raises(FileExistsError, match="already exists"):
        normalize_ensemble(input_path, output_path, config=cfg)

    # No side effects on input
    hashes_after, _ = _hash_store(input_path)
    assert hashes_before == hashes_after

    # The pre-existing output dir is still there and still empty (we did not
    # clobber it before raising).
    assert output_path.is_dir()
    assert list(output_path.iterdir()) == []


def test_input_zarr_missing_raises(tmp_path: Path) -> None:
    """If input_zarr does not exist, surface FileNotFoundError cleanly."""
    cfg = _make_config()
    with pytest.raises(FileNotFoundError):
        normalize_ensemble(tmp_path / "nope.zarr", tmp_path / "out.zarr", config=cfg)


# --- drop_columns -----------------------------------------------------------


def test_drop_columns_removes_statistic_entries(tmp_path: Path) -> None:
    """Dropping 'foo' should leave it out of both the coord and the value array."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    statistic_names = ["foo", "bar", "baz", "qux"]
    truth = _build_input_zarr(input_path, statistic_names=statistic_names)

    cfg = _make_config(drop_columns=["foo"])
    normalize_ensemble(input_path, output_path, config=cfg)

    ds = xr.open_zarr(output_path)
    out_stats = [str(s) for s in ds.coords["statistic"].values.tolist()]
    assert "foo" not in out_stats
    assert out_stats == ["bar", "baz", "qux"]
    assert ds.sizes["statistic"] == 3

    # The retained raw value array should equal the input minus the 'foo' column
    keep_indices = [i for i, name in enumerate(statistic_names) if name != "foo"]
    expected_raw = truth["value"][:, :, keep_indices]
    np.testing.assert_allclose(ds["value"].values, expected_raw, rtol=0, atol=0)

    # value_normalized has the same shape post-drop
    assert ds["value_normalized"].shape == expected_raw.shape


def test_drop_columns_unknown_raises(tmp_path: Path) -> None:
    """Asking to drop a non-existent column is an explicit error, not a silent no-op."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, statistic_names=["a", "b", "c", "d"])
    cfg = _make_config(drop_columns=["does_not_exist"])
    with pytest.raises(ValueError, match="drop_columns entries not present"):
        normalize_ensemble(input_path, output_path, config=cfg)


# --- provenance -------------------------------------------------------------


def test_provenance_zattrs_present(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, include_source_hash=True)

    cfg = _make_config()
    normalize_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert "normalize_config" in ds.attrs
    assert "created_at_utc" in ds.attrs
    assert "tmelandscape_version" in ds.attrs
    assert ds.attrs["tmelandscape_version"] == tmelandscape.__version__

    # normalize_config is a JSON-parseable string
    parsed = json.loads(str(ds.attrs["normalize_config"]))
    assert parsed["strategy"] == "within_timestep"
    assert parsed["preserve_time_effect"] is True
    assert parsed["drop_columns"] == []
    assert parsed["output_variable"] == "value_normalized"

    # created_at_utc parses as an ISO-8601 timestamp with timezone
    parsed_dt = datetime.fromisoformat(str(ds.attrs["created_at_utc"]))
    assert parsed_dt.tzinfo is not None

    # source_manifest_hash is forwarded from the input's manifest_hash
    assert ds.attrs.get("source_manifest_hash") == "deadbeef" * 8


def test_provenance_source_hash_optional(tmp_path: Path) -> None:
    """If the input has no manifest_hash, the output simply omits source_manifest_hash."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, include_source_hash=False)

    cfg = _make_config()
    normalize_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)
    # The other three are required
    assert "normalize_config" in ds.attrs
    assert "created_at_utc" in ds.attrs
    assert "tmelandscape_version" in ds.attrs
    # source_manifest_hash absent when input had no manifest_hash
    assert "source_manifest_hash" not in ds.attrs


# --- coord preservation -----------------------------------------------------


def test_per_simulation_coords_preserved(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path)

    cfg = _make_config()
    normalize_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    # All the per-simulation coords survive
    for name in ("ic_id", "parameter_combination_id", "parameter_alpha", "parameter_beta"):
        assert name in ds.coords, f"missing coord {name}"
        assert tuple(ds.coords[name].dims) == ("simulation",)

    np.testing.assert_array_equal(ds.coords["ic_id"].values.astype(np.int64), truth["ic_ids"])
    np.testing.assert_array_equal(
        ds.coords["parameter_combination_id"].values.astype(np.int64), truth["pc_ids"]
    )
    np.testing.assert_allclose(ds.coords["parameter_alpha"].values, truth["param_a"])
    np.testing.assert_allclose(ds.coords["parameter_beta"].values, truth["param_b"])


def test_per_simulation_coords_preserved_with_drop(tmp_path: Path) -> None:
    """Dropping a statistic column must not perturb per-simulation coords."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path, statistic_names=["foo", "bar", "baz", "qux"])

    cfg = _make_config(drop_columns=["foo", "qux"])
    normalize_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert [str(s) for s in ds.coords["statistic"].values.tolist()] == ["bar", "baz"]
    np.testing.assert_array_equal(ds.coords["ic_id"].values.astype(np.int64), truth["ic_ids"])
    np.testing.assert_allclose(ds.coords["parameter_alpha"].values, truth["param_a"])


# --- preserve_time_effect mean property -------------------------------------


def test_preserve_time_effect_keeps_per_step_mean(tmp_path: Path) -> None:
    """With preserve_time_effect=True, the per-(timepoint, statistic) mean
    of value_normalized should be approximately equal to the per-(timepoint,
    statistic) mean of value (within numerical tolerance).

    This is the reference algorithm's defining property — re-adding the
    pre-transform per-step mean restores the temporal trend after z-scoring.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    # Use more sims so the empirical mean is well-behaved
    _build_input_zarr(input_path, n_sim=8, n_tp=4, n_stat=3, seed=1234)

    cfg = _make_config(preserve_time_effect=True)
    normalize_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    raw_mean = ds["value"].mean(dim="simulation").values  # (n_tp, n_stat)
    norm_mean = ds["value_normalized"].mean(dim="simulation").values
    # Loose tolerance: the algorithm may legitimately differ by floating-point
    # accumulation and any approximations in the Yeo-Johnson + z-score path.
    np.testing.assert_allclose(norm_mean, raw_mean, rtol=1e-6, atol=1e-6)


def test_orchestrator_rejects_output_variable_equal_to_value(tmp_path: Path) -> None:
    """Defence-in-depth (Reviewer B2 RISK 6): even if Stream C's validator
    is bypassed (e.g. by a duck-typed stub from older tooling), the
    orchestrator itself must refuse ``output_variable='value'`` because the
    raw passthrough lives under that name and Python dict construction
    would silently dedupe-overwrite it.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=2, n_stat=2)

    # Build a duck-typed config that bypasses Pydantic validation, simulating
    # the failure mode the orchestrator must guard against on its own.
    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="within_timestep",
        preserve_time_effect=True,
        drop_columns=[],
        fill_nan_with=0.0,
        output_variable="value",
    )

    with pytest.raises(ValueError, match=r"output_variable.*'value'"):
        normalize_ensemble(input_path, output_path, config=bad_cfg)

    # And the input/output state must be clean: no partial write left behind.
    assert not output_path.exists()


def test_inherits_input_chunk_grid(tmp_path: Path) -> None:
    """Reviewer B2 SMELL 8: the output Zarr should mirror the input's chunk
    grid so downstream Dask reads don't have to cross mismatched boundaries.
    """
    # Build a fresh xarray Dataset and write it with explicit chunks so the
    # input's encoding cleanly carries the chunk grid we want to mirror.
    n_sim, n_tp, n_stat = 4, 6, 3
    rng = np.random.default_rng(42)
    raw = rng.standard_normal((n_sim, n_tp, n_stat)) + 5.0
    ds_in = xr.Dataset(
        data_vars={"value": (("simulation", "timepoint", "statistic"), raw)},
        coords={
            "simulation": np.array([f"sim_{i:03d}" for i in range(n_sim)]),
            "timepoint": np.arange(n_tp, dtype=np.int64),
            "statistic": np.array([f"stat_{j}" for j in range(n_stat)]),
        },
    )
    ds_in = ds_in.chunk({"simulation": 2, "timepoint": 3, "statistic": 1})
    input_path = tmp_path / "input.zarr"
    ds_in.to_zarr(input_path, mode="w")

    output_path = tmp_path / "output.zarr"
    cfg = _make_config()
    normalize_ensemble(input_path, output_path, config=cfg)

    ds_out = xr.open_zarr(output_path)
    # First-chunk size along each dim must match what we requested.
    value_chunks = ds_out["value"].chunks
    assert value_chunks is not None
    assert value_chunks[0][0] == 2  # simulation
    assert value_chunks[1][0] == 3  # timepoint
    assert value_chunks[2][0] == 1  # statistic
    ds_out.close()
