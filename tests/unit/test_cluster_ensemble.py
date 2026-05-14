"""Unit tests for ``tmelandscape.cluster.cluster_ensemble``.

These tests focus on the Zarr orchestrator's contract (set down in
``tasks/06-clustering-implementation.md`` and ADRs 0006 / 0007 / 0010):

* The input Zarr is byte-immutable across a call.
* The output Zarr fails fast (``FileExistsError``) if it already exists.
* The six output variable names must all be distinct (defence-in-depth).
* A missing ``source_variable`` raises ``ValueError`` listing the available
  variables.
* Provenance ``.zattrs`` (``cluster_config``, ``n_leiden_clusters``,
  ``knn_neighbors_used``, ``n_final_clusters_used``,
  ``cluster_count_metric_used``, ``source_input_zarr``,
  ``source_variable``, ``created_at_utc``, ``tmelandscape_version``)
  survive the round trip.
* ``source_embedding_config`` / ``source_normalize_config`` /
  ``source_manifest_hash`` forward from the input attrs when present.
* Per-window coords from the input land on the output unchanged.
* ``window_averages`` is passed through when present in the input.
* User-supplied k yields an empty ``cluster_count_scores`` array and
  ``cluster_count_metric_used == "user_supplied"``.
* Auto-selected k yields non-empty candidates + scores and a metric-named
  ``cluster_count_metric_used``.
* A mid-write ``to_zarr`` failure removes the partial directory and
  re-raises the original exception.

All tests mock the underlying ``cluster_leiden_ward`` algorithm with a
canned :class:`~tmelandscape.cluster.leiden_ward.ClusterResult` so that
the orchestrator's behaviour can be exercised independently of Stream A's
algorithm correctness (matching the buddy-pair-decoupling pattern used
in Phase 4's ``test_embedding_ensemble.py``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
import xarray as xr

import tmelandscape
from tmelandscape.cluster import cluster_ensemble
from tmelandscape.cluster.leiden_ward import ClusterResult

# --- helpers ----------------------------------------------------------------


def _try_import_cluster_config() -> Any:
    """Import Stream C's ClusterConfig if available, else return None."""
    try:
        from tmelandscape.config.cluster import (
            ClusterConfig,  # type: ignore[attr-defined]
        )
    except ImportError:
        return None
    return ClusterConfig


def _make_config(
    *,
    knn_neighbors: int | None = None,
    leiden_partition: str = "CPM",
    leiden_resolution: float = 1.0,
    leiden_seed: int = 42,
    n_final_clusters: int | None = 3,
    cluster_count_metric: str = "wss_elbow",
    cluster_count_min: int = 2,
    cluster_count_max: int | None = None,
    source_variable: str = "embedding",
    leiden_labels_variable: str = "leiden_labels",
    final_labels_variable: str = "cluster_labels",
    cluster_means_variable: str = "leiden_cluster_means",
    linkage_variable: str = "linkage_matrix",
    cluster_count_scores_variable: str = "cluster_count_scores",
    strategy: str = "leiden_ward",
) -> Any:
    """Construct a ClusterConfig (or duck-typed stand-in if Stream C has
    not landed yet).

    The orchestrator only reads attributes off this object plus
    ``model_dump_json`` — duck typing keeps the two halves of the
    buddy-pair handoff decoupled.
    """
    payload = {
        "strategy": strategy,
        "knn_neighbors": knn_neighbors,
        "leiden_partition": leiden_partition,
        "leiden_resolution": leiden_resolution,
        "leiden_seed": leiden_seed,
        "n_final_clusters": n_final_clusters,
        "cluster_count_metric": cluster_count_metric,
        "cluster_count_min": cluster_count_min,
        "cluster_count_max": cluster_count_max,
        "source_variable": source_variable,
        "leiden_labels_variable": leiden_labels_variable,
        "final_labels_variable": final_labels_variable,
        "cluster_means_variable": cluster_means_variable,
        "linkage_variable": linkage_variable,
        "cluster_count_scores_variable": cluster_count_scores_variable,
    }
    cls = _try_import_cluster_config()
    if cls is not None:
        try:
            return cls(**payload)
        except Exception:
            pass  # fall through to the duck-typed stub

    class _ConfigStub(SimpleNamespace):
        def model_dump_json(self) -> str:
            return json.dumps(payload)

        def model_dump(self) -> dict[str, Any]:
            return dict(payload)

    return _ConfigStub(**payload)


def _build_input_zarr(
    path: Path,
    *,
    n_window: int = 9,
    n_feature: int = 4,
    n_stat: int = 2,
    include_embedding: bool = True,
    include_window_averages: bool = True,
    include_manifest_hash: bool = True,
    include_normalize_config: bool = True,
    include_embedding_config: bool = True,
    include_forwarded_embedding_config: bool = False,
    seed: int = 0,
) -> dict[str, Any]:
    """Build a tiny Phase 4-shaped Zarr fixture.

    Mirrors the Phase 4 orchestrator's output: ``embedding`` of shape
    ``(window, embedding_feature)``, optionally ``window_averages`` of
    shape ``(window, statistic)``, plus per-window coords (simulation_id,
    window_index_in_sim, start_timepoint, end_timepoint, ic_id,
    parameter_combination_id, parameter_alpha).
    """
    rng = np.random.default_rng(seed)
    coords: dict[str, Any] = {
        "simulation_id": (
            "window",
            np.array([f"sim_{i // 3:03d}" for i in range(n_window)], dtype=np.str_),
        ),
        "window_index_in_sim": (
            "window",
            np.tile(np.arange(3, dtype=np.int64), n_window // 3 + 1)[:n_window],
        ),
        "start_timepoint": (
            "window",
            np.arange(n_window, dtype=np.int64),
        ),
        "end_timepoint": (
            "window",
            np.arange(n_window, dtype=np.int64) + 3,
        ),
        "ic_id": (
            "window",
            np.arange(n_window, dtype=np.int64) + 100,
        ),
        "parameter_combination_id": (
            "window",
            np.arange(n_window, dtype=np.int64) % 3,
        ),
        "parameter_alpha": (
            "window",
            rng.uniform(0.0, 1.0, size=n_window).astype(np.float64),
        ),
        "embedding_feature": (
            "embedding_feature",
            np.arange(n_feature, dtype=np.int64),
        ),
    }

    data_vars: dict[str, Any] = {}
    if include_embedding:
        embedding = rng.standard_normal((n_window, n_feature)).astype(np.float64)
        data_vars["embedding"] = (("window", "embedding_feature"), embedding)
    if include_window_averages:
        coords["statistic"] = (
            "statistic",
            np.array([f"stat_{i}" for i in range(n_stat)], dtype=np.str_),
        )
        averages = rng.standard_normal((n_window, n_stat)).astype(np.float64)
        data_vars["window_averages"] = (("window", "statistic"), averages)

    ds = xr.Dataset(data_vars=data_vars, coords=coords)

    if include_manifest_hash:
        ds.attrs["source_manifest_hash"] = "feedface" * 8
    if include_normalize_config:
        ds.attrs["source_normalize_config"] = json.dumps(
            {"strategy": "within_timestep", "preserve_time_effect": True}
        )
    if include_embedding_config:
        ds.attrs["embedding_config"] = json.dumps({"strategy": "sliding_window", "window_size": 4})
    if include_forwarded_embedding_config:
        ds.attrs["source_embedding_config"] = json.dumps(
            {"strategy": "sliding_window", "window_size": 5, "forwarded": True}
        )
    ds.attrs["tmelandscape_version"] = tmelandscape.__version__

    ds.to_zarr(path, mode="w")
    return {
        "embedding": data_vars.get("embedding", (None, None))[1],
        "window_averages": data_vars.get("window_averages", (None, None))[1],
        "n_window": n_window,
        "n_feature": n_feature,
        "n_stat": n_stat,
    }


def _hash_store(store_path: Path) -> tuple[dict[str, str], int]:
    """sha256-hash every file inside a Zarr store, recursively.

    Returns (path -> hex digest, file count). The path keys are
    POSIX-relative so an added / removed file fails the comparison even if
    no existing file mutates.
    """
    if not store_path.is_dir():
        raise AssertionError(f"expected a directory store at {store_path!s}")
    hashes: dict[str, str] = {}
    for p in sorted(store_path.rglob("*")):
        if p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            hashes[p.relative_to(store_path).as_posix()] = digest
    return hashes, len(hashes)


def _canned_result(
    *,
    n_window: int,
    n_feature: int,
    n_leiden: int = 4,
    n_final: int = 3,
    knn_neighbors_used: int = 3,
    cluster_count_metric_used: str = "user_supplied",
    candidates: np.ndarray | None = None,
    scores: np.ndarray | None = None,
) -> ClusterResult:
    """Build a deterministic ClusterResult for mocking the algorithm.

    Shapes follow the contract on :class:`ClusterResult` so the orchestrator
    can stitch the arrays into the output Dataset without surprises.
    """
    rng = np.random.default_rng(0)
    leiden_labels = (np.arange(n_window) % n_leiden).astype(np.int_)
    # Build a Leiden -> final mapping that uses every final label at least
    # once and is deterministic for assertion convenience.
    leiden_to_final = (np.arange(n_leiden) % n_final + 1).astype(np.int_)
    final_labels = leiden_to_final[leiden_labels].astype(np.int_)
    leiden_cluster_means = rng.standard_normal((n_leiden, n_feature)).astype(np.float64)
    linkage_matrix = np.column_stack(
        [
            np.arange(n_leiden - 1, dtype=np.float64),
            np.arange(1, n_leiden, dtype=np.float64),
            np.linspace(1.0, 2.0, n_leiden - 1, dtype=np.float64),
            np.arange(2, n_leiden + 1, dtype=np.float64),
        ]
    )
    if candidates is None:
        candidates = np.empty(0, dtype=np.int_)
    if scores is None:
        scores = np.empty(0, dtype=np.float64)
    return ClusterResult(
        leiden_labels=leiden_labels,
        final_labels=final_labels,
        leiden_cluster_means=leiden_cluster_means,
        linkage_matrix=linkage_matrix,
        leiden_to_final=leiden_to_final,
        n_leiden_clusters=n_leiden,
        knn_neighbors_used=knn_neighbors_used,
        n_final_clusters_used=n_final,
        cluster_count_metric_used=cluster_count_metric_used,
        cluster_count_candidates=candidates.astype(np.int_, copy=False),
        cluster_count_scores=scores.astype(np.float64, copy=False),
    )


def _patch_algorithm(result: ClusterResult) -> Any:
    """Patch ``cluster_leiden_ward`` AS IMPORTED BY the orchestrator module.

    The orchestrator imports the symbol at module load (``from
    tmelandscape.cluster.leiden_ward import cluster_leiden_ward``), so we
    must patch ``tmelandscape.cluster.cluster_leiden_ward`` (the bound
    name) rather than the source module's attribute.
    """
    return patch(
        "tmelandscape.cluster.cluster_leiden_ward",
        return_value=result,
    )


# --- happy path -------------------------------------------------------------


def test_round_trip_basic_shape_user_supplied_k(tmp_path: Path) -> None:
    """Build a tiny Zarr, cluster it with explicit ``n_final_clusters``, and
    verify the output schema/shape.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, n_window=9, n_feature=4, n_stat=2)

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4, n_leiden=4, n_final=3)

    with _patch_algorithm(result):
        out = cluster_ensemble(input_path, output_path, config=cfg)

    assert out == output_path.resolve()
    assert out.is_dir()

    ds = xr.open_zarr(out)
    assert ds.sizes["window"] == 9
    assert ds.sizes["embedding_feature"] == 4
    assert ds.sizes["leiden_cluster"] == 4
    assert ds.sizes["linkage_step"] == 3
    assert ds.sizes["linkage_field"] == 4
    assert ds.sizes["cluster_count_candidate"] == 0

    for name in (
        "embedding",
        "window_averages",
        "leiden_labels",
        "cluster_labels",
        "leiden_cluster_means",
        "linkage_matrix",
        "cluster_count_scores",
    ):
        assert name in ds.data_vars, f"missing output data variable {name}"
    assert ds["leiden_labels"].dims == ("window",)
    assert ds["cluster_labels"].dims == ("window",)
    assert ds["leiden_cluster_means"].dims == ("leiden_cluster", "embedding_feature")
    assert ds["linkage_matrix"].dims == ("linkage_step", "linkage_field")
    assert ds["cluster_count_scores"].dims == ("cluster_count_candidate",)
    assert ds["cluster_count_scores"].shape == (0,)


# --- input immutability -----------------------------------------------------


def test_input_zarr_byte_immutable(tmp_path: Path) -> None:
    """Every byte inside the input store survives the call."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    hashes_before, count_before = _hash_store(input_path)
    assert count_before > 0

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

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
    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result), pytest.raises(FileExistsError, match="already exists"):
        cluster_ensemble(input_path, output_path, config=cfg)

    hashes_after, _ = _hash_store(input_path)
    assert hashes_before == hashes_after
    assert output_path.is_dir()
    assert list(output_path.iterdir()) == []


def test_input_zarr_missing_raises(tmp_path: Path) -> None:
    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result), pytest.raises(FileNotFoundError):
        cluster_ensemble(tmp_path / "nope.zarr", tmp_path / "out.zarr", config=cfg)


# --- variable-collision defence-in-depth ------------------------------------


def test_variable_collision_raises_value_error(tmp_path: Path) -> None:
    """A duck-typed config whose leiden_labels_variable == final_labels_variable
    must be rejected by the orchestrator even though Stream C's Pydantic
    validator forbids it. Defence-in-depth.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="leiden_ward",
        knn_neighbors=None,
        leiden_partition="CPM",
        leiden_resolution=1.0,
        leiden_seed=42,
        n_final_clusters=3,
        cluster_count_metric="wss_elbow",
        cluster_count_min=2,
        cluster_count_max=None,
        source_variable="embedding",
        leiden_labels_variable="collision",
        final_labels_variable="collision",  # collides with leiden labels
        cluster_means_variable="leiden_cluster_means",
        linkage_variable="linkage_matrix",
        cluster_count_scores_variable="cluster_count_scores",
    )

    with pytest.raises(ValueError, match=r"variable names must all be distinct"):
        cluster_ensemble(input_path, output_path, config=bad_cfg)
    assert not output_path.exists()


def test_variable_collision_with_source_raises(tmp_path: Path) -> None:
    """A duck-typed config whose final_labels_variable equals source_variable
    must also be rejected — collision with the embedding passthrough.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    class _BadConfig(SimpleNamespace):
        def model_dump_json(self) -> str:
            return "{}"

        def model_dump(self) -> dict[str, Any]:
            return {}

    bad_cfg = _BadConfig(
        strategy="leiden_ward",
        knn_neighbors=None,
        leiden_partition="CPM",
        leiden_resolution=1.0,
        leiden_seed=42,
        n_final_clusters=3,
        cluster_count_metric="wss_elbow",
        cluster_count_min=2,
        cluster_count_max=None,
        source_variable="embedding",
        leiden_labels_variable="leiden_labels",
        final_labels_variable="embedding",  # collides with the source array
        cluster_means_variable="leiden_cluster_means",
        linkage_variable="linkage_matrix",
        cluster_count_scores_variable="cluster_count_scores",
    )

    with pytest.raises(ValueError, match=r"variable names must all be distinct"):
        cluster_ensemble(input_path, output_path, config=bad_cfg)
    assert not output_path.exists()


# --- missing source variable -----------------------------------------------


def test_source_variable_missing_raises(tmp_path: Path) -> None:
    """If the input Zarr has no ``embedding`` variable, raise ValueError that
    names the available variables.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, include_embedding=False)

    cfg = _make_config(n_final_clusters=3)  # source_variable defaults to "embedding"
    result = _canned_result(n_window=9, n_feature=4)
    with (
        _patch_algorithm(result),
        pytest.raises(ValueError, match=r"available variables: \[.+\]"),
    ):
        cluster_ensemble(input_path, output_path, config=cfg)
    assert not output_path.exists()


# --- provenance .zattrs -----------------------------------------------------


def test_provenance_zattrs_present(tmp_path: Path) -> None:
    """All nine required provenance keys land on the output."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(
        n_window=9,
        n_feature=4,
        n_leiden=4,
        n_final=3,
        knn_neighbors_used=3,
        cluster_count_metric_used="user_supplied",
    )
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    for key in (
        "cluster_config",
        "n_leiden_clusters",
        "knn_neighbors_used",
        "n_final_clusters_used",
        "cluster_count_metric_used",
        "source_input_zarr",
        "source_variable",
        "created_at_utc",
        "tmelandscape_version",
    ):
        assert key in ds.attrs, f"missing provenance attr {key}"

    # cluster_config round-trips through JSON to a dict
    parsed = json.loads(str(ds.attrs["cluster_config"]))
    assert isinstance(parsed, dict)
    assert parsed["strategy"] == "leiden_ward"
    assert parsed["n_final_clusters"] == 3

    assert int(ds.attrs["n_leiden_clusters"]) == 4
    assert int(ds.attrs["knn_neighbors_used"]) == 3
    assert int(ds.attrs["n_final_clusters_used"]) == 3
    assert ds.attrs["cluster_count_metric_used"] == "user_supplied"
    assert ds.attrs["source_variable"] == "embedding"
    assert ds.attrs["tmelandscape_version"] == tmelandscape.__version__
    assert Path(str(ds.attrs["source_input_zarr"])).resolve() == input_path.resolve()

    parsed_dt = datetime.fromisoformat(str(ds.attrs["created_at_utc"]))
    assert parsed_dt.tzinfo is not None


# --- provenance forwarding --------------------------------------------------


def test_provenance_forwards_upstream_attrs(tmp_path: Path) -> None:
    """source_embedding_config, source_normalize_config, source_manifest_hash
    forward from the input attrs when present.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_manifest_hash=True,
        include_normalize_config=True,
        include_embedding_config=False,
        include_forwarded_embedding_config=True,
    )

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert ds.attrs.get("source_manifest_hash") == "feedface" * 8
    fwd_norm = json.loads(str(ds.attrs["source_normalize_config"]))
    assert fwd_norm["strategy"] == "within_timestep"
    fwd_embed = json.loads(str(ds.attrs["source_embedding_config"]))
    assert fwd_embed["forwarded"] is True


def test_provenance_lifts_embedding_config_to_forwarded_key(tmp_path: Path) -> None:
    """When the input carries its own ``embedding_config`` (i.e. the upstream
    Phase 4 store, not a previously-clustered store), the orchestrator
    surfaces it under ``source_embedding_config`` so the chain stays
    auditable.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_embedding_config=True,
        include_forwarded_embedding_config=False,
    )

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    fwd_embed = json.loads(str(ds.attrs["source_embedding_config"]))
    assert fwd_embed["strategy"] == "sliding_window"


def test_provenance_forwarded_attrs_optional(tmp_path: Path) -> None:
    """When the input has none of the upstream provenance attrs, the
    forwarded keys are simply absent on the output.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(
        input_path,
        include_manifest_hash=False,
        include_normalize_config=False,
        include_embedding_config=False,
    )

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)
    ds = xr.open_zarr(output_path)

    assert "source_manifest_hash" not in ds.attrs
    assert "source_normalize_config" not in ds.attrs
    assert "source_embedding_config" not in ds.attrs
    # Required keys still present
    assert "cluster_config" in ds.attrs
    assert "tmelandscape_version" in ds.attrs


# --- per-window coord propagation -------------------------------------------


def test_per_window_coords_propagate(tmp_path: Path) -> None:
    """Every ``window``-dim coord on the input lands on the output verbatim."""
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(input_path, n_window=9, n_feature=4, n_stat=2)
    assert truth["embedding"] is not None

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

    ds_in = xr.open_zarr(input_path)
    ds_out = xr.open_zarr(output_path)
    for coord_name in (
        "simulation_id",
        "window_index_in_sim",
        "start_timepoint",
        "end_timepoint",
        "ic_id",
        "parameter_combination_id",
        "parameter_alpha",
    ):
        assert coord_name in ds_out.coords, f"missing per-window coord {coord_name}"
        assert ds_out.coords[coord_name].dims == ("window",)
        np.testing.assert_array_equal(
            ds_out.coords[coord_name].values, ds_in.coords[coord_name].values
        )


# --- window_averages passthrough --------------------------------------------


def test_window_averages_passthrough_when_present(tmp_path: Path) -> None:
    """When the input has ``window_averages``, the output preserves it
    verbatim (same shape, same values, same dims).
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    truth = _build_input_zarr(
        input_path,
        n_window=9,
        n_feature=4,
        n_stat=2,
        include_window_averages=True,
    )
    averages_truth = truth["window_averages"]
    assert averages_truth is not None

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

    ds_out = xr.open_zarr(output_path)
    assert "window_averages" in ds_out.data_vars
    assert ds_out["window_averages"].dims == ("window", "statistic")
    assert ds_out["window_averages"].shape == averages_truth.shape
    np.testing.assert_allclose(ds_out["window_averages"].values, averages_truth)


def test_window_averages_absent_when_input_lacks_it(tmp_path: Path) -> None:
    """When the input does NOT carry window_averages, the output also lacks
    it — the orchestrator does not synthesise the array.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path, include_window_averages=False)

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

    ds_out = xr.open_zarr(output_path)
    assert "window_averages" not in ds_out.data_vars
    assert "statistic" not in ds_out.dims


# --- user-supplied k vs auto-selected k -------------------------------------


def test_user_supplied_k_path(tmp_path: Path) -> None:
    """When the algorithm reports user-supplied k, the output has an empty
    cluster_count_scores array and the metric-used attr says so.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(
        n_window=9,
        n_feature=4,
        cluster_count_metric_used="user_supplied",
        candidates=np.empty(0, dtype=np.int_),
        scores=np.empty(0, dtype=np.float64),
    )
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

    ds = xr.open_zarr(output_path)
    assert ds.attrs["cluster_count_metric_used"] == "user_supplied"
    assert ds.sizes["cluster_count_candidate"] == 0
    assert ds["cluster_count_scores"].shape == (0,)


def test_auto_selected_k_path(tmp_path: Path) -> None:
    """When the algorithm auto-selected k, the output carries non-empty
    candidate + score arrays with matching length, and the metric-used attr
    is the metric name.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    cfg = _make_config(n_final_clusters=None, cluster_count_metric="wss_elbow")
    candidates = np.array([2, 3, 4], dtype=np.int_)
    scores = np.array([10.0, 5.0, 4.5], dtype=np.float64)
    result = _canned_result(
        n_window=9,
        n_feature=4,
        n_leiden=4,
        n_final=3,
        cluster_count_metric_used="wss_elbow",
        candidates=candidates,
        scores=scores,
    )
    with _patch_algorithm(result):
        cluster_ensemble(input_path, output_path, config=cfg)

    ds = xr.open_zarr(output_path)
    assert ds.attrs["cluster_count_metric_used"] == "wss_elbow"
    assert ds.sizes["cluster_count_candidate"] == 3
    np.testing.assert_array_equal(
        ds.coords["cluster_count_candidate"].values.astype(np.int_), candidates
    )
    np.testing.assert_allclose(ds["cluster_count_scores"].values, scores)


# --- partial-output cleanup -------------------------------------------------


def test_partial_output_cleanup_on_to_zarr_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``to_zarr`` raises mid-write, the orchestrator removes the
    partial output directory and re-raises the original exception.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_input_zarr(input_path)

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)

    sentinel = RuntimeError("synthetic to_zarr failure")
    original_to_zarr = xr.Dataset.to_zarr

    def _failing_to_zarr(self: xr.Dataset, *args: Any, **kwargs: Any) -> Any:
        # Touch the output path so we can verify cleanup actually deletes it.
        target = Path(args[0]) if args else Path(kwargs["store"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "partial.bin").write_bytes(b"junk")
        raise sentinel

    monkeypatch.setattr(xr.Dataset, "to_zarr", _failing_to_zarr)
    try:
        with _patch_algorithm(result), pytest.raises(RuntimeError) as excinfo:
            cluster_ensemble(input_path, output_path, config=cfg)
        assert excinfo.value is sentinel
        assert not output_path.exists(), "partial output should be cleaned up after to_zarr failure"
    finally:
        monkeypatch.setattr(xr.Dataset, "to_zarr", original_to_zarr)


# --- 2D-source-array guard --------------------------------------------------


def test_source_variable_must_be_2d(tmp_path: Path) -> None:
    """The orchestrator refuses a non-2D source array — clustering needs
    ``(window, embedding_feature)``.
    """
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    # Build a deliberately-wrong 1D embedding to exercise the guard.
    ds = xr.Dataset(
        data_vars={"embedding": (("window",), np.arange(9, dtype=np.float64))},
        coords={
            "simulation_id": ("window", np.array([f"s_{i}" for i in range(9)])),
        },
    )
    ds.to_zarr(input_path, mode="w")

    cfg = _make_config(n_final_clusters=3)
    result = _canned_result(n_window=9, n_feature=4)
    with _patch_algorithm(result), pytest.raises(ValueError, match=r"must be a 2D"):
        cluster_ensemble(input_path, output_path, config=cfg)
    assert not output_path.exists()
