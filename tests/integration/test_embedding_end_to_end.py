"""Step-4 end-to-end: Python API, CLI, and MCP tool produce equivalent output Zarrs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.config.embedding import EmbeddingConfig
from tmelandscape.embedding import embed_ensemble
from tmelandscape.mcp.tools import (
    embed_ensemble_tool,
    list_embed_strategies_tool,
)


def _build_tiny_normalized_input(path: Path, *, seed: int = 0) -> None:
    """Construct a small input Zarr resembling Phase 3.5's output."""
    n_sim, n_tp, n_stat = 3, 8, 2
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal((n_sim, n_tp, n_stat)) + 5.0
    normed = rng.standard_normal((n_sim, n_tp, n_stat))
    ds = xr.Dataset(
        data_vars={
            "value": (("simulation", "timepoint", "statistic"), raw),
            "value_normalized": (("simulation", "timepoint", "statistic"), normed),
        },
        coords={
            "simulation": np.array([f"sim_{i:03d}" for i in range(n_sim)]),
            "timepoint": np.arange(n_tp, dtype=np.int64),
            "statistic": np.array([f"stat_{j}" for j in range(n_stat)]),
            "parameter_alpha": (
                "simulation",
                np.linspace(0.1, 1.0, n_sim, dtype=np.float64),
            ),
            "parameter_combination_id": (
                "simulation",
                np.arange(n_sim, dtype=np.int64),
            ),
            "ic_id": ("simulation", np.zeros(n_sim, dtype=np.int64)),
        },
        attrs={"source_manifest_hash": "abc123-test"},
    )
    ds.to_zarr(path, mode="w")


def _default_config() -> EmbeddingConfig:
    return EmbeddingConfig(window_size=4)


def _read_output(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (embedding, averages) arrays from an output Zarr."""
    ds = xr.open_zarr(path)
    emb = np.asarray(ds["embedding"].values)
    avg = np.asarray(ds["window_averages"].values)
    ds.close()
    return emb, avg


def test_python_api_writes_output_zarr(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_tiny_normalized_input(input_path)
    out = embed_ensemble(input_path, output_path, config=_default_config())
    assert out == output_path
    assert output_path.is_dir()
    ds = xr.open_zarr(output_path)
    assert "embedding" in ds.data_vars
    assert "window_averages" in ds.data_vars
    assert "simulation_id" in ds.coords
    assert "window_index_in_sim" in ds.coords
    assert "start_timepoint" in ds.coords
    assert "end_timepoint" in ds.coords
    assert ds.attrs["window_size"] == 4
    assert ds.attrs["source_variable"] == "value_normalized"
    ds.close()


def test_cli_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_normalized_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _default_config()
    embed_ensemble(input_path, api_out, config=cfg)
    api_emb, api_avg = _read_output(api_out)

    cfg_path = tmp_path / "embedding_config.json"
    cfg_path.write_text(cfg.model_dump_json())
    cli_out = tmp_path / "cli.zarr"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "embed",
            str(input_path),
            str(cli_out),
            "--config",
            str(cfg_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["strategy"] == "sliding_window"
    assert summary["window_size"] == 4

    cli_emb, cli_avg = _read_output(cli_out)
    np.testing.assert_array_equal(api_emb, cli_emb)
    np.testing.assert_array_equal(api_avg, cli_avg)


def test_mcp_tool_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_normalized_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _default_config()
    embed_ensemble(input_path, api_out, config=cfg)
    api_emb, api_avg = _read_output(api_out)

    mcp_out = tmp_path / "mcp.zarr"
    result = embed_ensemble_tool(
        input_zarr=str(input_path),
        output_zarr=str(mcp_out),
        embedding_config=cfg.model_dump(),
    )
    assert Path(result["output_zarr"]).exists()
    assert result["strategy"] == "sliding_window"
    mcp_emb, mcp_avg = _read_output(mcp_out)
    np.testing.assert_array_equal(api_emb, mcp_emb)
    np.testing.assert_array_equal(api_avg, mcp_avg)


def test_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_normalized_input(input_path)
    output_path = tmp_path / "existing.zarr"
    output_path.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        embed_ensemble(input_path, output_path, config=_default_config())


def test_list_embed_strategies_tool_includes_defaults() -> None:
    catalogue = list_embed_strategies_tool()
    names = {entry["name"] for entry in catalogue}
    assert "sliding_window" in names
    assert "identity" in names
