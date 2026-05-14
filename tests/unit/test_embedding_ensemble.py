"""Unit tests for ``tmelandscape.embedding.embed_ensemble``.

These tests focus on the Zarr orchestrator's contract (set down in
``tasks/05-embedding-implementation.md`` and ADR 0006):

* The input Zarr is byte-immutable across a call.
* The output Zarr fails fast (``FileExistsError``) if it already exists.
* ``drop_statistics`` removes named entries from the ``statistic`` coord
  *before* windowing; ``embedding_feature`` reflects the post-drop count.
* Unknown ``drop_statistics`` entries raise ``ValueError``.
* Provenance ``.zattrs`` (``embedding_config``, ``source_input_zarr``,
  ``source_variable``, ``window_size``, ``n_skipped_simulations``,
  ``created_at_utc``, ``tmelandscape_version``) survive the round trip.
* ``source_normalize_config`` and ``source_manifest_hash`` forward from
  the input attrs when present and are absent otherwise.
* Per-simulation coords (``parameter_*``, ``ic_id``,
  ``parameter_combination_id``) broadcast along the ``window`` dimension
  to match each window's source simulation.
* ``source_variable`` can switch to a different array (e.g. raw ``value``
  instead of ``value_normalized``).
* Skipped-sim warning surfaces (``warnings.warn``) when a sim is too short.
* ``output_variable == source_variable`` raises ``ValueError``
  (defence-in-depth even when the config validator is bypassed).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import xarray as xr

import tmelandscape
from tmelandscape.embedding import embed_ensemble

# --- helpers ----------------------------------------------------------------


def _try_import_embedding_config() -> Any:
    """Import Stream C's EmbeddingConfig if available, else return None."""
    try:
        from tmelandscape.config.embedding import (
            EmbeddingConfig,  # type: ignore[attr-defined]
        )
    except ImportError:
        return None
    return EmbeddingConfig


def _make_config(
    *,
    window_size: int = 4,
    step_size: int = 1,
    source_variable: str = "value_normalized",
    output_variable: str = "embedding",
    averages_variable: str = "window_averages",
    drop_statistics: list[str] | None = None,
    strategy: str = "sliding_window",
) -> Any:
    """Construct an EmbeddingConfig (or duck-typed stand-in if Stream C
    has not landed yet).

    The orchestrator only reads attributes off this object plus
    ``model_dump_json`` — duck typing keeps the two halves of the
    buddy-pair handoff decoupled.
    """
    cls = _try_import_embedding_config()
    drops = list(drop_statistics) if drop_statistics is not None else []
    if cls is not None:
        return cls(
            strategy=strategy,
            window_size=window_size,
            step_size=step_size,
            source_variable=source_variable,
            output_variable=output_variable,
            averages_variable=averages_variable,
            drop_statistics=drops,
        )
    payload = {
        "strategy": strategy,
        "window_size": window_size,
        "step_size": step_size,
        "source_variable": source_variable,
        "output_variable": output_variable,
        "averages_variable": averages_variable,
        "drop_statistics": drops,
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
    n_sim: int = 3,
    n_tp: int = 8,
    n_stat: int = 2,
    statistic_names: list[str] | None = None,
    include_value_normalized: bool = True,
    include_manifest_hash: bool = True,
    include_normalize_config: bool = True,
    include_forwarded_hash: bool = False,
    seed: int = 0,
) -> dict[str, Any]:
    """Build a tiny ensemble Zarr that mirrors Stream B's Phase 3.5 output.

    The store carries both ``value`` (raw) and ``value_normalized`` arrays
    plus per-simulation coords (``ic_id``, ``parameter_combination_id``,
    ``parameter_alpha``). Provenance attrs are populated to match what
    ``normalize_ensemble`` writes so the embed step can forward them.
    """
    if statistic_names is None:
        statistic_names = [f"stat_{i}" for i in range(n_stat)]
    assert len(statistic_names) == n_stat

    rng = np.random.default_rng(seed)
    raw_value = rng.standard_normal((n_sim, n_tp, n_stat)).astype(np.float64)
    # Slightly different distribution so tests can distinguish source choice.
    normalized_value = (raw_value - raw_value.mean(axis=0, keepdims=True)) / (
        raw_value.std(axis=0, keepdims=True) + 1e-9
    )

    simulation_ids = np.array([f"sim_{i:03d}" for i in range(n_sim)], dtype=np.str_)
    timepoints = np.arange(n_tp, dtype=np.int64)
    statistics = np.array(statistic_names, dtype=np.str_)
    ic_ids = np.arange(n_sim, dtype=np.int64) + 100
    pc_ids = np.arange(n_sim, dtype=np.int64)
    param_alpha = rng.uniform(0.0, 1.0, size=n_sim).astype(np.float64)

    data_vars: dict[str, Any] = {
        "value": (("simulation", "timepoint", "statistic"), raw_value),
    }
    if include_value_normalized:
        data_vars["value_normalized"] = (
            ("simulation", "timepoint", "statistic"),
            normalized_value,
        )

    ds = xr.Dataset(
        data_vars=data_vars,
        coords={
            "simulation": simulation_ids,
            "timepoint": timepoints,
            "statistic": statistics,
            "ic_id": ("simulation", ic_ids),
            "parameter_combination_id": ("simulation", pc_ids),
            "parameter_alpha": ("simulation", param_alpha),
        },
    )
    if include_manifest_hash:
        ds.attrs["manifest_hash"] = "deadbeef" * 8
    if include_forwarded_hash:
        ds.attrs["source_manifest_hash"] = "cafef00d" * 8
    if include_normalize_config:
        ds.attrs["normalize_config"] = json.dumps(
            {
                "strategy": "within_timestep",
                "preserve_time_effect": True,
                "drop_columns": [],
                "fill_nan_with": 0.0,
                "output_variable": "value_normalized",
            }
        )
    ds.attrs["tmelandscape_version"] = tmelandscape.__version__

    ds.to_zarr(path, mode="w")
    return {
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "simulation_ids": simulation_ids,
        "timepoints": timepoints,
        "statistics": statistics,
        "ic_ids": ic_ids,
        "pc_ids": pc_ids,
        "param_alpha": param_alpha,
    }


def _hash_store(store_path: Path) -> tuple[dict[str, str], int]:
    """sha256-hash every file inside a Zarr store, recursively.

    Returns (path -> hex digest, file count). Hash map keyed by POSIX-
    relative path so a comparison fails loudly even if a file is added or
    removed (not just mutated).
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


def test_round_trip_basic_shape(tmp_path: Path) -> None:
    """Build a tiny Zarr, embed it, and verify the output schema/shape.

    n_sim=3, n_tp=8, n_stat=2, window_size=4, step_size=1
        per-sim windows = (8 - 4) // 1 + 1 = 5
        total windows   = 3 * 5 = 15
        embedding_feature = window_size * n_stat = 4 * 2 = 8
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path, n_sim=3, n_tp=8, n_stat=2)

    cfg = _make_config(window_size=4, step_size=1)
    out = embed_ensemble(input_path, output_path, config=cfg)
    assert out == output_path.resolve()
    assert out.is_dir()

    ds = xr.open_zarr(out)

    # Dims and sizes
    assert ds.sizes["window"] == 15
    assert ds.sizes["embedding_feature"] == 8
    assert ds.sizes["statistic"] == 2

    # Data variables
    assert "embedding" in ds.data_vars
    assert "window_averages" in ds.data_vars
    assert ds["embedding"].dims == ("window", "embedding_feature")
    assert ds["window_averages"].dims == ("window", "statistic")
    assert ds["embedding"].shape == (15, 8)
    assert ds["window_averages"].shape == (15, 2)

    # Per-window coords are aligned to the window dim
    for coord_name in (
        "simulation_id",
        "window_index_in_sim",
        "start_timepoint",
        "end_timepoint",
        "ic_id",
        "parameter_combination_id",
        "parameter_alpha",
    ):
        assert coord_name in ds.coords, f"missing per-window coord {coord_name}"
        assert ds.coords[coord_name].dims == ("window",)

    # statistic coord matches the input
    np.testing.assert_array_equal(
        ds.coords["statistic"].values.astype(str), truth["statistics"].astype(str)
    )


# --- input immutability -----------------------------------------------------


def test_input_zarr_byte_immutable(tmp_path: Path) -> None:
    """The crown jewel: every byte inside the input store survives the call.

    Strategy: walk the store recursively and sha256-hash every file. The
    hash map must be byte-equal before and after the orchestrator runs.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=3, n_tp=8, n_stat=2)

    hashes_before, count_before = _hash_store(input_path)
    assert count_before > 0

    cfg = _make_config(window_size=4)
    embed_ensemble(input_path, output_path, config=cfg)

    hashes_after, count_after = _hash_store(input_path)
    assert count_before == count_after, (
        f"file count changed: {count_before} -> {count_after}; "
        f"added/removed {set(hashes_after) ^ set(hashes_before)}"
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
    output_path.mkdir()  # simulate a stale store from an aborted run

    hashes_before, _ = _hash_store(input_path)
    cfg = _make_config(window_size=4)
    with pytest.raises(FileExistsError, match="already exists"):
        embed_ensemble(input_path, output_path, config=cfg)

    # No side effects on input
    hashes_after, _ = _hash_store(input_path)
    assert hashes_before == hashes_after

    # The pre-existing output dir is untouched
    assert output_path.is_dir()
    assert list(output_path.iterdir()) == []


def test_input_zarr_missing_raises(tmp_path: Path) -> None:
    cfg = _make_config(window_size=4)
    with pytest.raises(FileNotFoundError):
        embed_ensemble(tmp_path / "nope.zarr", tmp_path / "out.zarr", config=cfg)


def test_source_variable_missing_raises(tmp_path: Path) -> None:
    """If the named source_variable is not in the input, fail with a clear
    ValueError that names the available data variables.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    # Skip writing value_normalized so the default source pick fails.
    _build_input_zarr(input_path, include_value_normalized=False)
    cfg = _make_config(window_size=4)  # source_variable defaults to value_normalized
    with pytest.raises(ValueError, match="no 'value_normalized' data variable"):
        embed_ensemble(input_path, output_path, config=cfg)
    # And no partial output was left behind.
    assert not output_path.exists()


# --- per-window coord broadcasting ------------------------------------------


def test_per_window_coords_match_source_simulation(tmp_path: Path) -> None:
    """Each window's ``parameter_alpha``, ``ic_id``,
    ``parameter_combination_id`` must equal the source simulation's value.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path, n_sim=3, n_tp=8, n_stat=2)

    cfg = _make_config(window_size=4, step_size=1)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    # 3 sims * 5 windows = 15 rows; sim_index runs [0,0,0,0,0, 1,1,1,1,1, 2,2,2,2,2]
    sim_ids = [str(s) for s in ds.coords["simulation_id"].values.tolist()]
    win_idx = ds.coords["window_index_in_sim"].values.astype(np.int64)
    starts = ds.coords["start_timepoint"].values.astype(np.int64)
    ends = ds.coords["end_timepoint"].values.astype(np.int64)
    ic_ids = ds.coords["ic_id"].values.astype(np.int64)
    pc_ids = ds.coords["parameter_combination_id"].values.astype(np.int64)
    alphas = ds.coords["parameter_alpha"].values.astype(np.float64)

    # Expected per-window mapping
    expected_sim_idx = np.repeat(np.arange(3), 5)
    expected_sim_ids = truth["simulation_ids"][expected_sim_idx].astype(str).tolist()
    expected_ic = truth["ic_ids"][expected_sim_idx]
    expected_pc = truth["pc_ids"][expected_sim_idx]
    expected_alpha = truth["param_alpha"][expected_sim_idx]
    expected_win_idx = np.tile(np.arange(5), 3)
    expected_start = expected_win_idx * 1  # step_size=1
    expected_end = expected_start + 4 - 1  # window_size=4

    assert sim_ids == expected_sim_ids
    np.testing.assert_array_equal(win_idx, expected_win_idx)
    np.testing.assert_array_equal(starts, expected_start)
    np.testing.assert_array_equal(ends, expected_end)
    np.testing.assert_array_equal(ic_ids, expected_ic)
    np.testing.assert_array_equal(pc_ids, expected_pc)
    np.testing.assert_allclose(alphas, expected_alpha)


# --- drop_statistics --------------------------------------------------------


def test_drop_statistics_removes_named_entries(tmp_path: Path) -> None:
    """Dropping 'foo' should leave it out of both the coord and shrink
    ``embedding_feature`` by ``window_size``.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        n_sim=2,
        n_tp=6,
        n_stat=4,
        statistic_names=["foo", "bar", "baz", "qux"],
    )

    cfg = _make_config(window_size=3, drop_statistics=["foo"])
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    out_stats = [str(s) for s in ds.coords["statistic"].values.tolist()]
    assert out_stats == ["bar", "baz", "qux"]
    assert ds.sizes["statistic"] == 3
    # embedding_feature = window_size * (n_stat - n_dropped) = 3 * 3 = 9
    assert ds.sizes["embedding_feature"] == 9
    assert ds["embedding"].shape[1] == 9
    assert ds["window_averages"].shape[1] == 3


def test_drop_statistics_unknown_raises(tmp_path: Path) -> None:
    """An unknown stat name in drop_statistics is an explicit error."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, statistic_names=["a", "b"])
    cfg = _make_config(window_size=2, drop_statistics=["does_not_exist"])
    with pytest.raises(ValueError, match="drop_statistics entries not present"):
        embed_ensemble(input_path, output_path, config=cfg)
    assert not output_path.exists()


# --- source_variable switch -------------------------------------------------


def test_source_variable_switch_to_raw_value(tmp_path: Path) -> None:
    """Pointing source_variable at ``value`` (raw) instead of
    ``value_normalized`` should produce a same-shape output but with
    different numerical content.
    """
    input_path_a = tmp_path / "in_a.zarr"
    input_path_b = tmp_path / "in_b.zarr"
    output_a = tmp_path / "out_a.zarr"
    output_b = tmp_path / "out_b.zarr"
    _build_input_zarr(input_path_a, n_sim=2, n_tp=6, n_stat=2, seed=42)
    _build_input_zarr(input_path_b, n_sim=2, n_tp=6, n_stat=2, seed=42)

    cfg_norm = _make_config(window_size=3, source_variable="value_normalized")
    cfg_raw = _make_config(window_size=3, source_variable="value")

    embed_ensemble(input_path_a, output_a, config=cfg_norm)
    embed_ensemble(input_path_b, output_b, config=cfg_raw)

    ds_norm = xr.open_zarr(output_a)
    ds_raw = xr.open_zarr(output_b)

    # Identical shapes
    assert ds_norm["embedding"].shape == ds_raw["embedding"].shape
    assert ds_norm["window_averages"].shape == ds_raw["window_averages"].shape
    # Differing numerical content (since normalized != raw)
    assert not np.allclose(ds_norm["embedding"].values, ds_raw["embedding"].values)
    # Provenance records the choice
    assert ds_norm.attrs["source_variable"] == "value_normalized"
    assert ds_raw.attrs["source_variable"] == "value"


# --- provenance -------------------------------------------------------------


def test_provenance_zattrs_present(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_manifest_hash=True,
        include_normalize_config=True,
    )

    cfg = _make_config(window_size=4)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    # All required keys present
    for key in (
        "embedding_config",
        "source_input_zarr",
        "source_variable",
        "window_size",
        "n_skipped_simulations",
        "created_at_utc",
        "tmelandscape_version",
    ):
        assert key in ds.attrs, f"missing provenance attr {key}"

    # Round-trip semantics
    parsed = json.loads(str(ds.attrs["embedding_config"]))
    assert parsed["strategy"] == "sliding_window"
    assert parsed["window_size"] == 4
    assert parsed["step_size"] == 1
    assert parsed["source_variable"] == "value_normalized"
    assert parsed["output_variable"] == "embedding"
    assert parsed["averages_variable"] == "window_averages"
    assert parsed["drop_statistics"] == []

    assert int(ds.attrs["window_size"]) == 4
    assert int(ds.attrs["n_skipped_simulations"]) == 0
    assert ds.attrs["source_variable"] == "value_normalized"
    assert ds.attrs["tmelandscape_version"] == tmelandscape.__version__
    assert Path(str(ds.attrs["source_input_zarr"])).resolve() == input_path.resolve()

    parsed_dt = datetime.fromisoformat(str(ds.attrs["created_at_utc"]))
    assert parsed_dt.tzinfo is not None

    # Forwarded attrs present
    assert ds.attrs.get("source_manifest_hash") == "deadbeef" * 8
    fwd_norm = json.loads(str(ds.attrs["source_normalize_config"]))
    assert fwd_norm["strategy"] == "within_timestep"


def test_provenance_forwarded_attrs_optional(tmp_path: Path) -> None:
    """When the input has neither manifest_hash nor normalize_config, the
    forwarded provenance keys are simply absent on the output.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_manifest_hash=False,
        include_normalize_config=False,
    )

    cfg = _make_config(window_size=4)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert "source_manifest_hash" not in ds.attrs
    assert "source_normalize_config" not in ds.attrs
    # Required keys still present
    assert "embedding_config" in ds.attrs
    assert "tmelandscape_version" in ds.attrs


def test_provenance_forwards_source_manifest_hash_when_only_forwarded(
    tmp_path: Path,
) -> None:
    """If the input has only ``source_manifest_hash`` (e.g. it is itself a
    Phase 3.5 output, not the raw Phase 3 store), the embed step still
    surfaces the upstream hash so the chain is auditable.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_manifest_hash=False,
        include_forwarded_hash=True,
    )

    cfg = _make_config(window_size=4)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert ds.attrs.get("source_manifest_hash") == "cafef00d" * 8


# --- skipped-sim warning ----------------------------------------------------


def test_skipped_simulation_warning(tmp_path: Path) -> None:
    """A simulation with fewer than ``window_size`` timepoints contributes
    zero windows; the orchestrator must emit a warnings.warn naming the
    affected simulation_id, and the count lands in n_skipped_simulations.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    # n_tp=3, window_size=5 -> every sim is too short.
    _build_input_zarr(input_path, n_sim=2, n_tp=3, n_stat=2)

    cfg = _make_config(window_size=5)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        embed_ensemble(input_path, output_path, config=cfg)

    msgs = [str(w.message) for w in caught]
    assert any("sim_000" in m and "sim_001" in m for m in msgs), msgs
    assert any("fewer than window_size=5" in m for m in msgs), msgs

    ds = xr.open_zarr(output_path)
    assert int(ds.attrs["n_skipped_simulations"]) == 2
    # Zero windows survived
    assert ds.sizes["window"] == 0
    # embedding_feature still well-defined
    assert ds.sizes["embedding_feature"] == 5 * 2


def test_no_warning_when_all_sims_fit(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=8, n_stat=2)
    cfg = _make_config(window_size=4)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        embed_ensemble(input_path, output_path, config=cfg)
    skipped_msgs = [str(w.message) for w in caught if "fewer than window_size" in str(w.message)]
    assert skipped_msgs == []
    ds = xr.open_zarr(output_path)
    assert int(ds.attrs["n_skipped_simulations"]) == 0


# --- output_variable == source_variable defence-in-depth --------------------


def test_orchestrator_rejects_output_variable_equal_to_source(tmp_path: Path) -> None:
    """Defence-in-depth: even if Stream C's validator is bypassed (e.g. by
    a duck-typed stub from older tooling), the orchestrator itself must
    refuse ``output_variable == source_variable``.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=6, n_stat=2)

    # Duck-typed config that bypasses Pydantic validation.
    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="sliding_window",
        window_size=3,
        step_size=1,
        source_variable="value_normalized",
        output_variable="value_normalized",  # collision
        averages_variable="window_averages",
        drop_statistics=[],
    )

    with pytest.raises(ValueError, match=r"output_variable.*source_variable"):
        embed_ensemble(input_path, output_path, config=bad_cfg)
    assert not output_path.exists()


def test_orchestrator_rejects_averages_variable_equal_to_source(tmp_path: Path) -> None:
    """Same defence applies to averages_variable: it must not shadow the
    source array either.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=6, n_stat=2)

    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="sliding_window",
        window_size=3,
        step_size=1,
        source_variable="value_normalized",
        output_variable="embedding",
        averages_variable="value_normalized",  # collision
        drop_statistics=[],
    )

    with pytest.raises(ValueError, match=r"averages_variable.*source_variable"):
        embed_ensemble(input_path, output_path, config=bad_cfg)
    assert not output_path.exists()


def test_orchestrator_rejects_output_variable_equal_to_averages(tmp_path: Path) -> None:
    """Last collision: output_variable == averages_variable would dedupe
    one entry off the data_vars dict and silently lose an array.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=6, n_stat=2)

    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="sliding_window",
        window_size=3,
        step_size=1,
        source_variable="value_normalized",
        output_variable="same_name",
        averages_variable="same_name",
        drop_statistics=[],
    )

    with pytest.raises(ValueError, match=r"output_variable.*averages_variable"):
        embed_ensemble(input_path, output_path, config=bad_cfg)
    assert not output_path.exists()


# --- end_timepoint / start_timepoint reflect step_size ----------------------


def test_step_size_changes_window_starts(tmp_path: Path) -> None:
    """With step_size=2 on a 10-tp sim and window_size=4: starts at
    0, 2, 4, 6 -> 4 windows per sim. Validate via the propagated coords.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_sim=2, n_tp=10, n_stat=2)

    cfg = _make_config(window_size=4, step_size=2)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    # (10 - 4) // 2 + 1 = 4 windows per sim, 2 sims -> 8 total
    assert ds.sizes["window"] == 8
    starts = ds.coords["start_timepoint"].values.astype(np.int64)
    ends = ds.coords["end_timepoint"].values.astype(np.int64)
    np.testing.assert_array_equal(starts, np.tile([0, 2, 4, 6], 2))
    np.testing.assert_array_equal(ends, np.tile([3, 5, 7, 9], 2))


# --- numerical fidelity through the algorithm -------------------------------


def test_embedding_values_match_flatten_of_input(tmp_path: Path) -> None:
    """The first window's flattened embedding row must equal
    ``value_normalized[0, 0:W, :].ravel(order='C')`` (the reference
    flatten order). This is the round-trip integrity check that
    proves the orchestrator hands the algorithm the right array.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path, n_sim=2, n_tp=6, n_stat=3, seed=7)

    cfg = _make_config(window_size=3, step_size=1)
    embed_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    # Row 0: simulation 0, window 0, timepoints 0..2
    expected_row0 = truth["normalized_value"][0, 0:3, :].ravel(order="C")
    np.testing.assert_allclose(ds["embedding"].values[0], expected_row0)
    # Per-window per-stat averages
    expected_avg0 = np.nanmean(truth["normalized_value"][0, 0:3, :], axis=0)
    np.testing.assert_allclose(ds["window_averages"].values[0], expected_avg0)
