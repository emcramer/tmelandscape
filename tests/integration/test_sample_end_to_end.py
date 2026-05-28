"""Step-1 end-to-end: Python API, CLI, and MCP tool all produce equivalent manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.config.sweep import (
    IcSourceStructured,
    ParameterSpec,
    SweepConfig,
)
from tmelandscape.mcp.tools import generate_sweep_tool
from tmelandscape.sampling import generate_sweep
from tmelandscape.sampling.manifest import SweepManifest


def _tiny_config(source_csv: Path) -> SweepConfig:
    return SweepConfig(
        parameters=[
            ParameterSpec(name="r_exh", low=1e-4, high=1e-2, scale="log10"),
            ParameterSpec(name="r_adh", low=0.1, high=5.0, scale="linear"),
        ],
        n_parameter_samples=3,
        n_initial_conditions=2,
        sampler="pyDOE3",
        seed=20260513,
        ic_source=IcSourceStructured(
            source_csv=str(source_csv),
            description="ring tissue: tumor disc + fibroblast ring + cd8 annulus",
        ),
    )


@pytest.mark.slow
def test_python_api_produces_expected_manifest(tmp_path: Path, structured_source_csv: Path) -> None:
    cfg = _tiny_config(structured_source_csv)
    ic_dir = tmp_path / "ics"
    manifest = generate_sweep(cfg, initial_conditions_dir=ic_dir)

    assert len(manifest.rows) == cfg.n_parameter_samples * cfg.n_initial_conditions
    sim_ids = [row.simulation_id for row in manifest.rows]
    assert len(set(sim_ids)) == len(sim_ids), "simulation_ids must be unique"

    ic_root = manifest.ic_root()
    assert ic_root.is_dir()
    assert manifest.sweep_id is not None and manifest.sweep_id.startswith("sweep_")
    for row in manifest.rows:
        assert set(row.parameter_values) == {"r_exh", "r_adh"}
        assert 1e-4 <= row.parameter_values["r_exh"] <= 1e-2
        assert 0.1 <= row.parameter_values["r_adh"] <= 5.0
        assert (ic_root / row.ic_path).is_file()
        # New per-row diagnostics propagated from generate_initial_conditions:
        assert len(row.ic_sha256) == 64
        assert row.ic_scaffold_seed >= 0
        assert row.ic_sa_final_cost >= 0
        assert sum(row.ic_achieved_proportions.values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.slow
def test_save_load_round_trip(tmp_path: Path, structured_source_csv: Path) -> None:
    cfg = _tiny_config(structured_source_csv)
    manifest = generate_sweep(cfg, initial_conditions_dir=tmp_path / "ics")
    manifest.save(tmp_path / "manifest")
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "manifest.parquet").is_file()
    reloaded = SweepManifest.load(tmp_path / "manifest")
    assert reloaded.rows == manifest.rows
    assert reloaded.config.model_dump() == cfg.model_dump()


@pytest.mark.slow
def test_cli_matches_python_api(tmp_path: Path, structured_source_csv: Path) -> None:
    cfg = _tiny_config(structured_source_csv)
    config_path = tmp_path / "cfg.json"
    config_path.write_text(cfg.model_dump_json())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sample",
            str(config_path),
            "--manifest-out",
            str(tmp_path / "cli_manifest"),
            "--ic-dir",
            str(tmp_path / "cli_ics"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    summary = json.loads(result.stdout)
    assert summary["n_rows"] == cfg.n_parameter_samples * cfg.n_initial_conditions

    api_manifest = generate_sweep(cfg, initial_conditions_dir=tmp_path / "api_ics")
    cli_manifest = SweepManifest.load(tmp_path / "cli_manifest")
    assert [r.parameter_values for r in api_manifest.rows] == [
        r.parameter_values for r in cli_manifest.rows
    ]


@pytest.mark.slow
def test_mcp_tool_matches_python_api(tmp_path: Path, structured_source_csv: Path) -> None:
    cfg = _tiny_config(structured_source_csv)
    summary = generate_sweep_tool(
        config=cfg.model_dump(),
        initial_conditions_dir=str(tmp_path / "mcp_ics"),
        manifest_out=str(tmp_path / "mcp_manifest"),
    )
    assert summary["n_rows"] == cfg.n_parameter_samples * cfg.n_initial_conditions
    assert Path(summary["manifest_json"]).is_file()
    assert Path(summary["manifest_parquet"]).is_file()
