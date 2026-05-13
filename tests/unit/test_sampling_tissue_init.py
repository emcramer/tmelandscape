"""Tests for the tissue_simulator wrapper that produces initial-condition CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tmelandscape.sampling.tissue_init import generate_initial_conditions

_REQUIRED_COLUMNS = {"x", "y", "z", "radius", "cell_type", "is_boundary"}


def test_writes_expected_files_and_columns(tmp_path: Path) -> None:
    paths = generate_initial_conditions(
        n_replicates=2,
        output_dir=tmp_path,
        seed=42,
        target_n_cells=20,
        tissue_dims_um=(50.0, 50.0, 10.0),
    )

    assert len(paths) == 2
    assert [p.name for p in paths] == ["ic_0000.csv", "ic_0001.csv"]
    for p in paths:
        assert p.is_absolute()
        assert p.exists()
        df = pd.read_csv(p)
        assert _REQUIRED_COLUMNS.issubset(df.columns)
        assert len(df) > 0


def test_same_seed_yields_identical_csvs(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    paths_a = generate_initial_conditions(
        n_replicates=2,
        output_dir=dir_a,
        seed=2026,
        target_n_cells=20,
        tissue_dims_um=(50.0, 50.0, 10.0),
    )
    paths_b = generate_initial_conditions(
        n_replicates=2,
        output_dir=dir_b,
        seed=2026,
        target_n_cells=20,
        tissue_dims_um=(50.0, 50.0, 10.0),
    )

    for pa, pb in zip(paths_a, paths_b, strict=True):
        assert pa.read_bytes() == pb.read_bytes()


def test_creates_output_dir_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    paths = generate_initial_conditions(
        n_replicates=1,
        output_dir=nested,
        seed=0,
        target_n_cells=20,
        tissue_dims_um=(50.0, 50.0, 10.0),
    )
    assert nested.is_dir()
    assert paths[0].parent == nested.resolve()
