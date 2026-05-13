"""Step-3 end-to-end: Python API, CLI, and MCP tool produce equivalent Zarr ensembles.

Every test supplies an explicit ``SummarizeConfig.statistics`` panel — there is
no default in tmelandscape (ADR 0009).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.config.sweep import ParameterSpec, SweepConfig
from tmelandscape.mcp.tools import summarize_ensemble_tool
from tmelandscape.sampling.manifest import SweepManifest, SweepRow
from tmelandscape.summarize import summarize_ensemble

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_physicell"
SIM_IDS = ("sim_000000_ic_000", "sim_000001_ic_000", "sim_000002_ic_000")

# Small, parameter-free panel — kept identical across all tests so api/CLI/MCP
# results are comparable.
TEST_PANEL = ["cell_counts", "cell_proportions"]


def _fixture_manifest(initial_conditions_dir: Path) -> SweepManifest:
    """Build a SweepManifest whose rows reference the synthetic fixture sims."""
    cfg = SweepConfig(
        parameters=[
            ParameterSpec(name="r_exh", low=1e-4, high=1e-2, scale="log10"),
            ParameterSpec(name="r_adh", low=0.1, high=5.0, scale="linear"),
        ],
        n_parameter_samples=len(SIM_IDS),
        n_initial_conditions=1,
        sampler="pyDOE3",
        seed=20260513,
    )
    initial_conditions_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        SweepRow(
            simulation_id=sim_id,
            parameter_combination_id=i,
            ic_id=0,
            parameter_values={"r_exh": 10 ** -(2 + i), "r_adh": 1.0 + i},
            ic_path=f"ic_000{i}.csv",
        )
        for i, sim_id in enumerate(SIM_IDS)
    ]
    return SweepManifest(
        config=cfg,
        initial_conditions_dir=str(initial_conditions_dir),
        rows=rows,
        tmelandscape_version="0.3.0-test",
    )


def _write_summarize_config(tmp_path: Path) -> Path:
    """Persist a SummarizeConfig.json for the CLI."""
    cfg = SummarizeConfig(statistics=list(TEST_PANEL))
    path = tmp_path / "summarize_config.json"
    path.write_text(cfg.model_dump_json())
    return path


def test_python_api_writes_ensemble_zarr(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "ics")
    zarr_path = summarize_ensemble(
        manifest,
        physicell_root=FIXTURE_DIR,
        output_zarr=tmp_path / "ensemble.zarr",
        config=SummarizeConfig(statistics=list(TEST_PANEL)),
    )
    assert zarr_path.exists()

    ds = xr.open_zarr(str(zarr_path), consolidated=False)
    assert ds.sizes["simulation"] == len(SIM_IDS)
    assert ds.sizes["timepoint"] >= 1
    assert ds.sizes["statistic"] >= 1
    n_cells_slab = ds["value"].sel(statistic="n_cells").to_numpy()
    assert np.all(np.isfinite(n_cells_slab))
    assert np.all(n_cells_slab > 0)


def test_cli_summarize_matches_python_api(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "ics")
    manifest.save(tmp_path / "manifest")
    cfg_path = _write_summarize_config(tmp_path)

    runner = CliRunner()
    cli_zarr = tmp_path / "cli_ensemble.zarr"
    result = runner.invoke(
        app,
        [
            "summarize",
            str(tmp_path / "manifest.json"),
            str(cfg_path),
            "--physicell-root",
            str(FIXTURE_DIR),
            "--output-zarr",
            str(cli_zarr),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["n_simulations"] == len(SIM_IDS)
    assert cli_zarr.exists()


def test_mcp_tool_summarize_matches_python_api(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "ics")
    manifest_path = tmp_path / "manifest"
    manifest.save(manifest_path)
    mcp_zarr = tmp_path / "mcp_ensemble.zarr"
    cfg = SummarizeConfig(statistics=list(TEST_PANEL))
    result = summarize_ensemble_tool(
        manifest_path=str(manifest_path),
        physicell_root=str(FIXTURE_DIR),
        output_zarr=str(mcp_zarr),
        summarize_config=cfg.model_dump(),
    )
    assert result["n_simulations"] == len(SIM_IDS)
    assert Path(result["zarr_path"]).exists()


def test_summarize_raises_on_missing_simulation_dir(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "ics")
    empty_root = tmp_path / "empty_physicell"
    empty_root.mkdir()
    with pytest.raises(FileNotFoundError, match="simulation directory missing"):
        summarize_ensemble(
            manifest,
            physicell_root=empty_root,
            output_zarr=tmp_path / "ensemble.zarr",
            config=SummarizeConfig(statistics=list(TEST_PANEL)),
        )


def test_python_and_cli_produce_equivalent_value_arrays(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "ics")
    manifest.save(tmp_path / "manifest")
    cfg_path = _write_summarize_config(tmp_path)

    api_zarr = tmp_path / "api.zarr"
    summarize_ensemble(
        manifest,
        physicell_root=FIXTURE_DIR,
        output_zarr=api_zarr,
        config=SummarizeConfig(statistics=list(TEST_PANEL)),
    )

    runner = CliRunner()
    cli_zarr = tmp_path / "cli.zarr"
    result = runner.invoke(
        app,
        [
            "summarize",
            str(tmp_path / "manifest.json"),
            str(cfg_path),
            "--physicell-root",
            str(FIXTURE_DIR),
            "--output-zarr",
            str(cli_zarr),
        ],
    )
    assert result.exit_code == 0

    api_ds = xr.open_zarr(str(api_zarr), consolidated=False)
    cli_ds = xr.open_zarr(str(cli_zarr), consolidated=False)
    np.testing.assert_array_equal(api_ds["value"].to_numpy(), cli_ds["value"].to_numpy())
    api_ds.close()
    cli_ds.close()
    shutil.rmtree(api_zarr)
    shutil.rmtree(cli_zarr)
