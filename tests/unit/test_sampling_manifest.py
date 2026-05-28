"""Unit tests for ``tmelandscape.sampling.manifest``."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

import tmelandscape
from tmelandscape.config.sweep import IcSourceOwnData, ParameterSpec, SweepConfig
from tmelandscape.sampling.manifest import SweepManifest, SweepRow

_STUB_SOURCE_CSV = "tests/data/ic_source_structured.csv"


def _make_row(
    *,
    sim_id: str,
    combo_id: int,
    ic_id: int,
    values: dict[str, float],
    ic_path: str,
    scaffold_seed: int,
    sha: str,
    cost: float,
) -> SweepRow:
    return SweepRow(
        simulation_id=sim_id,
        parameter_combination_id=combo_id,
        ic_id=ic_id,
        parameter_values=values,
        ic_path=ic_path,
        ic_scaffold_seed=scaffold_seed,
        ic_sha256=sha,
        ic_sa_final_cost=cost,
        ic_achieved_proportions={"tumor": 0.5, "fibroblast": 0.5},
    )


def _build_manifest() -> SweepManifest:
    config = SweepConfig(
        parameters=[
            ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0),
            ParameterSpec(name="cycle_rate", low=1e-4, high=1e-2, scale="log10"),
        ],
        n_parameter_samples=2,
        n_initial_conditions=2,
        seed=42,
        ic_source=IcSourceOwnData(source_csv=_STUB_SOURCE_CSV),
    )
    rows = [
        _make_row(
            sim_id="sim_000000_ic_000",
            combo_id=0,
            ic_id=0,
            values={"oxygen_uptake": 0.5, "cycle_rate": 1e-3},
            ic_path="ic_000.csv",
            scaffold_seed=111,
            sha="a" * 64,
            cost=10.0,
        ),
        _make_row(
            sim_id="sim_000000_ic_001",
            combo_id=0,
            ic_id=1,
            values={"oxygen_uptake": 0.5, "cycle_rate": 1e-3},
            ic_path="ic_001.csv",
            scaffold_seed=222,
            sha="b" * 64,
            cost=12.5,
        ),
        _make_row(
            sim_id="sim_000001_ic_000",
            combo_id=1,
            ic_id=0,
            values={"oxygen_uptake": 1.5, "cycle_rate": 5e-3},
            ic_path="ic_000.csv",
            scaffold_seed=111,
            sha="a" * 64,
            cost=10.0,
        ),
        _make_row(
            sim_id="sim_000001_ic_001",
            combo_id=1,
            ic_id=1,
            values={"oxygen_uptake": 1.5, "cycle_rate": 5e-3},
            ic_path="ic_001.csv",
            scaffold_seed=222,
            sha="b" * 64,
            cost=12.5,
        ),
    ]
    return SweepManifest(
        config=config,
        initial_conditions_dir="initial_conditions",
        rows=rows,
    )


def test_tmelandscape_version_captured_automatically() -> None:
    manifest = _build_manifest()
    assert manifest.tmelandscape_version == tmelandscape.__version__


def test_tmelandscape_version_can_be_overridden() -> None:
    manifest = SweepManifest(
        config=_build_manifest().config,
        initial_conditions_dir="initial_conditions",
        rows=[],
        tmelandscape_version="9.9.9-test",
    )
    assert manifest.tmelandscape_version == "9.9.9-test"


def test_save_writes_both_sibling_files(tmp_path: Path) -> None:
    manifest = _build_manifest()
    stem = tmp_path / "sweep"
    manifest.save(stem)
    assert (tmp_path / "sweep.json").is_file()
    assert (tmp_path / "sweep.parquet").is_file()


def test_save_accepts_explicit_json_suffix(tmp_path: Path) -> None:
    manifest = _build_manifest()
    manifest.save(tmp_path / "sweep.json")
    assert (tmp_path / "sweep.json").is_file()
    assert (tmp_path / "sweep.parquet").is_file()


def test_round_trip_equality(tmp_path: Path) -> None:
    manifest = _build_manifest()
    manifest.save(tmp_path / "sweep")
    loaded = SweepManifest.load(tmp_path / "sweep")
    assert loaded == manifest


def test_load_accepts_path_without_extension(tmp_path: Path) -> None:
    manifest = _build_manifest()
    manifest.save(tmp_path / "sweep")
    loaded_no_ext = SweepManifest.load(tmp_path / "sweep")
    loaded_with_ext = SweepManifest.load(tmp_path / "sweep.json")
    assert loaded_no_ext == loaded_with_ext == manifest


def test_parquet_has_flattened_columns(tmp_path: Path) -> None:
    manifest = _build_manifest()
    manifest.save(tmp_path / "sweep")
    table = pq.read_table(tmp_path / "sweep.parquet")

    expected_columns = {
        "simulation_id",
        "parameter_combination_id",
        "ic_id",
        "ic_path",
        "ic_scaffold_seed",
        "ic_sha256",
        "ic_sa_final_cost",
        "ic_achieved_proportions_json",
        "oxygen_uptake",
        "cycle_rate",
    }
    assert set(table.column_names) == expected_columns
    assert table.num_rows == len(manifest.rows)

    as_dict = table.to_pydict()
    assert as_dict["simulation_id"][0] == "sim_000000_ic_000"
    assert as_dict["parameter_combination_id"][0] == 0
    assert as_dict["ic_id"][0] == 0
    assert as_dict["oxygen_uptake"][0] == 0.5
    assert as_dict["cycle_rate"][0] == 1e-3
    assert as_dict["ic_path"][-1] == "ic_001.csv"
    assert as_dict["ic_scaffold_seed"][0] == 111
    assert as_dict["ic_sha256"][0] == "a" * 64
    assert as_dict["ic_sa_final_cost"][0] == 10.0
    # JSON-encoded with sort_keys so the schema stays stable across vocabularies.
    assert as_dict["ic_achieved_proportions_json"][0] == '{"fibroblast": 0.5, "tumor": 0.5}'


def test_parquet_column_types(tmp_path: Path) -> None:
    manifest = _build_manifest()
    manifest.save(tmp_path / "sweep")
    table = pq.read_table(tmp_path / "sweep.parquet")
    schema = {field.name: str(field.type) for field in table.schema}
    assert schema["ic_scaffold_seed"] == "int64"
    assert schema["ic_sha256"] == "string"
    assert schema["ic_sa_final_cost"] == "double"
    assert schema["ic_achieved_proportions_json"] == "string"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    manifest = _build_manifest()
    nested = tmp_path / "outputs" / "phase2" / "sweep"
    manifest.save(nested)
    assert nested.with_suffix(".json").is_file()
    assert nested.with_suffix(".parquet").is_file()
