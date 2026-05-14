"""Step-5 end-to-end: Python API, CLI, and MCP tool produce equivalent output Zarrs.

Exercises both the explicit-``n_final_clusters`` path and the auto-selection
(``cluster_count_metric="wss_elbow"``) path. The input fixture is a
deterministic two-Gaussian-blob synthetic windowed embedding that resembles
Phase 4's output layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.cluster import cluster_ensemble
from tmelandscape.config.cluster import ClusterConfig
from tmelandscape.mcp.tools import (
    cluster_ensemble_tool,
    list_cluster_strategies_tool,
)


def _build_tiny_embedding_input(path: Path, *, seed: int = 0) -> None:
    """Construct a small input Zarr resembling Phase 4's output.

    Two well-separated 3D Gaussian blobs, 60 rows total, so Leiden over a
    sqrt-n kNN graph yields enough communities for Ward to produce a
    well-defined elbow.
    """
    rng = np.random.default_rng(seed)
    half = 30
    blob_a = rng.standard_normal((half, 3)) + np.array([0.0, 0.0, 0.0])
    blob_b = rng.standard_normal((half, 3)) + np.array([8.0, 8.0, 8.0])
    embedding = np.concatenate([blob_a, blob_b], axis=0)
    n_window = embedding.shape[0]
    n_feature = embedding.shape[1]

    # Per-window coordinates that match what `embed_ensemble` writes downstream.
    simulation_id = np.array([f"sim_{i // 10:02d}" for i in range(n_window)], dtype="U16")
    window_index_in_sim = np.tile(np.arange(10, dtype=np.int64), n_window // 10)
    start_timepoint = window_index_in_sim.astype(np.int64)
    end_timepoint = (window_index_in_sim + 3).astype(np.int64)
    parameter_combination_id = (np.arange(n_window) // 10).astype(np.int64)
    ic_id = np.zeros(n_window, dtype=np.int64)
    parameter_alpha = np.linspace(0.1, 1.0, n_window, dtype=np.float64)

    # Optional companion array passed through verbatim by the orchestrator.
    n_stat = 2
    window_averages = rng.standard_normal((n_window, n_stat))

    ds = xr.Dataset(
        data_vars={
            "embedding": (("window", "embedding_feature"), embedding),
            "window_averages": (("window", "statistic"), window_averages),
        },
        coords={
            "window": np.arange(n_window, dtype=np.int64),
            "embedding_feature": np.arange(n_feature, dtype=np.int64),
            "statistic": np.array([f"stat_{j}" for j in range(n_stat)]),
            "simulation_id": ("window", simulation_id),
            "window_index_in_sim": ("window", window_index_in_sim),
            "start_timepoint": ("window", start_timepoint),
            "end_timepoint": ("window", end_timepoint),
            "parameter_combination_id": ("window", parameter_combination_id),
            "ic_id": ("window", ic_id),
            "parameter_alpha": ("window", parameter_alpha),
        },
        attrs={
            "source_manifest_hash": "abc123-test",
            "embedding_config": json.dumps({"strategy": "sliding_window"}),
        },
    )
    ds.to_zarr(path, mode="w")


def _explicit_config() -> ClusterConfig:
    return ClusterConfig(n_final_clusters=2, leiden_seed=42)


def _auto_config() -> ClusterConfig:
    return ClusterConfig(cluster_count_metric="wss_elbow", leiden_seed=42)


def _read_output(path: Path) -> dict[str, np.ndarray]:
    ds = xr.open_zarr(path)
    out = {
        "embedding": np.asarray(ds["embedding"].values),
        "leiden_labels": np.asarray(ds["leiden_labels"].values),
        "cluster_labels": np.asarray(ds["cluster_labels"].values),
        "leiden_cluster_means": np.asarray(ds["leiden_cluster_means"].values),
        "linkage_matrix": np.asarray(ds["linkage_matrix"].values),
        "cluster_count_scores": np.asarray(ds["cluster_count_scores"].values),
    }
    ds.close()
    return out


def test_python_api_writes_output_zarr(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_tiny_embedding_input(input_path)

    out = cluster_ensemble(input_path, output_path, config=_explicit_config())
    assert out == output_path.resolve()
    assert output_path.is_dir()

    ds = xr.open_zarr(output_path)
    for var in (
        "embedding",
        "window_averages",
        "leiden_labels",
        "cluster_labels",
        "leiden_cluster_means",
        "linkage_matrix",
        "cluster_count_scores",
    ):
        assert var in ds.data_vars, f"missing {var}"

    for coord in (
        "simulation_id",
        "window_index_in_sim",
        "start_timepoint",
        "end_timepoint",
        "parameter_combination_id",
        "ic_id",
        "parameter_alpha",
    ):
        assert coord in ds.coords, f"missing coord {coord}"

    assert ds.attrs["n_final_clusters_used"] == 2
    assert ds.attrs["cluster_count_metric_used"] == "user_supplied"
    # User-supplied k path ⇒ empty per-candidate scores.
    assert ds["cluster_count_scores"].sizes["cluster_count_candidate"] == 0
    ds.close()


def test_auto_selection_writes_per_candidate_scores(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_tiny_embedding_input(input_path)

    cluster_ensemble(input_path, output_path, config=_auto_config())

    ds = xr.open_zarr(output_path)
    assert ds.attrs["cluster_count_metric_used"] == "wss_elbow"
    n_candidates = ds["cluster_count_scores"].sizes["cluster_count_candidate"]
    assert n_candidates > 0
    assert ds["cluster_count_scores"].shape == (n_candidates,)
    # The chosen k must be in the candidate range and a valid cut depth.
    chosen = int(ds.attrs["n_final_clusters_used"])
    assert chosen >= 2
    assert chosen <= int(ds.attrs["n_leiden_clusters"])
    ds.close()


def test_cli_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_embedding_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _explicit_config()
    cluster_ensemble(input_path, api_out, config=cfg)
    api_arrays = _read_output(api_out)

    cfg_path = tmp_path / "cluster_config.json"
    cfg_path.write_text(cfg.model_dump_json())
    cli_out = tmp_path / "cli.zarr"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "cluster",
            str(input_path),
            str(cli_out),
            "--config",
            str(cfg_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["strategy"] == "leiden_ward"
    assert summary["n_final_clusters"] == 2

    cli_arrays = _read_output(cli_out)
    for key, api_arr in api_arrays.items():
        np.testing.assert_array_equal(api_arr, cli_arrays[key])


def test_mcp_tool_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_embedding_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _explicit_config()
    cluster_ensemble(input_path, api_out, config=cfg)
    api_arrays = _read_output(api_out)

    mcp_out = tmp_path / "mcp.zarr"
    result = cluster_ensemble_tool(
        input_zarr=str(input_path),
        output_zarr=str(mcp_out),
        cluster_config=cfg.model_dump(),
    )
    assert Path(result["output_zarr"]).exists()
    assert result["strategy"] == "leiden_ward"
    assert result["n_final_clusters"] == 2

    mcp_arrays = _read_output(mcp_out)
    for key, api_arr in api_arrays.items():
        np.testing.assert_array_equal(api_arr, mcp_arrays[key])


def test_mcp_tool_auto_selection_path(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_embedding_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _auto_config()
    cluster_ensemble(input_path, api_out, config=cfg)

    mcp_out = tmp_path / "mcp.zarr"
    cluster_ensemble_tool(
        input_zarr=str(input_path),
        output_zarr=str(mcp_out),
        cluster_config=cfg.model_dump(),
    )

    api_ds = xr.open_zarr(api_out)
    mcp_ds = xr.open_zarr(mcp_out)
    assert api_ds.attrs["n_final_clusters_used"] == mcp_ds.attrs["n_final_clusters_used"]
    assert (
        api_ds.attrs["cluster_count_metric_used"]
        == mcp_ds.attrs["cluster_count_metric_used"]
        == "wss_elbow"
    )
    np.testing.assert_array_equal(
        np.asarray(api_ds["cluster_count_scores"].values),
        np.asarray(mcp_ds["cluster_count_scores"].values),
    )
    api_ds.close()
    mcp_ds.close()


def test_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_embedding_input(input_path)
    output_path = tmp_path / "existing.zarr"
    output_path.mkdir()
    with pytest.raises(FileExistsError):
        cluster_ensemble(input_path, output_path, config=_explicit_config())


def test_list_cluster_strategies_tool_includes_defaults() -> None:
    catalogue = list_cluster_strategies_tool()
    names = {entry["name"] for entry in catalogue}
    assert "leiden_ward" in names
    assert "identity" in names
