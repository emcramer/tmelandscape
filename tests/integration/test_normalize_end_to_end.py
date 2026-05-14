"""Step-3.5 end-to-end: Python API, CLI, and MCP tool produce equivalent output Zarrs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.config.normalize import NormalizeConfig
from tmelandscape.mcp.tools import (
    list_normalize_strategies_tool,
    normalize_ensemble_tool,
)
from tmelandscape.normalize import normalize_ensemble


def _build_tiny_input(path: Path, *, seed: int = 0) -> None:
    """Construct a small but non-degenerate input Zarr at ``path``."""
    n_sim, n_tp, n_stat = 4, 5, 3
    rng = np.random.default_rng(seed)
    raw = rng.lognormal(mean=0.0, sigma=0.5, size=(n_sim, n_tp, n_stat))
    ds = xr.Dataset(
        data_vars={"value": (("simulation", "timepoint", "statistic"), raw)},
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
        attrs={"manifest_hash": "abc123-test"},
    )
    ds.to_zarr(path, mode="w")


def _default_config() -> NormalizeConfig:
    return NormalizeConfig(preserve_time_effect=True, drop_columns=[])


def _read_output_arrays(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(value, value_normalized)`` arrays from an output Zarr."""
    ds = xr.open_zarr(path)
    raw = np.asarray(ds["value"].values)
    norm = np.asarray(ds["value_normalized"].values)
    ds.close()
    return raw, norm


def test_python_api_writes_output_zarr(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    output_path = tmp_path / "output.zarr"
    _build_tiny_input(input_path)
    out = normalize_ensemble(input_path, output_path, config=_default_config())
    assert out == output_path
    assert output_path.is_dir()
    ds = xr.open_zarr(output_path)
    assert "value" in ds.data_vars
    assert "value_normalized" in ds.data_vars
    assert "manifest_hash" not in ds.attrs  # only `source_manifest_hash` is set
    assert ds.attrs["source_manifest_hash"] == "abc123-test"
    ds.close()


def test_cli_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_input(input_path)

    # Reference via Python API.
    api_out = tmp_path / "api.zarr"
    cfg = _default_config()
    normalize_ensemble(input_path, api_out, config=cfg)
    api_raw, api_norm = _read_output_arrays(api_out)

    # CLI invocation with the same config.
    cfg_path = tmp_path / "normalize_config.json"
    cfg_path.write_text(cfg.model_dump_json())
    cli_out = tmp_path / "cli.zarr"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "normalize",
            str(input_path),
            str(cli_out),
            "--config",
            str(cfg_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["strategy"] == "within_timestep"
    assert summary["output_variable"] == "value_normalized"

    cli_raw, cli_norm = _read_output_arrays(cli_out)
    np.testing.assert_array_equal(api_raw, cli_raw)
    np.testing.assert_array_equal(api_norm, cli_norm)


def test_mcp_tool_matches_python_api(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_input(input_path)

    api_out = tmp_path / "api.zarr"
    cfg = _default_config()
    normalize_ensemble(input_path, api_out, config=cfg)
    api_raw, api_norm = _read_output_arrays(api_out)

    mcp_out = tmp_path / "mcp.zarr"
    result = normalize_ensemble_tool(
        input_zarr=str(input_path),
        output_zarr=str(mcp_out),
        normalize_config=cfg.model_dump(),
    )
    assert Path(result["output_zarr"]).exists()
    assert result["strategy"] == "within_timestep"
    mcp_raw, mcp_norm = _read_output_arrays(mcp_out)
    np.testing.assert_array_equal(api_raw, mcp_raw)
    np.testing.assert_array_equal(api_norm, mcp_norm)


def test_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.zarr"
    _build_tiny_input(input_path)
    output_path = tmp_path / "existing.zarr"
    output_path.mkdir()  # pre-existing directory triggers the guard
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        normalize_ensemble(input_path, output_path, config=_default_config())


def test_list_normalize_strategies_tool_includes_default() -> None:
    catalogue = list_normalize_strategies_tool()
    names = {entry["name"] for entry in catalogue}
    assert "within_timestep" in names
    assert "identity" in names
