"""Unit tests for ``tmelandscape.summarize.spatialtissuepy_driver`` (post ADR 0009).

Scope:

* The synthetic fixture under ``tests/data/synthetic_physicell/`` parses cleanly
  via ``spatialtissuepy.synthetic.PhysiCellSimulation.from_output_folder``.
* :func:`summarize_simulation` produces a long-form DataFrame with the contract
  column schema; tests supply explicit ``statistics=[...]`` panels (no defaults
  per ADR 0009).
* Sanity values for ``cell_counts`` and ``cell_proportions``.
* Zero-cell timepoints emit only the ``cell_counts`` row.

The fixture is built deterministically by
``tests/data/synthetic_physicell/build.py``; if it is missing or stale the
:func:`ensure_fixture` helper rebuilds it on the fly.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from tmelandscape.config.summarize import StatisticSpec, SummarizeConfig
from tmelandscape.summarize.spatialtissuepy_driver import (
    SUMMARY_COLUMNS,
    summarize_simulation,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic_physicell"
FIRST_SIM_DIR = FIXTURE_ROOT / "sim_000000_ic_000"

# Test panels. We deliberately use small, parameter-free panels so the tests
# do not creep into "default panel" territory.
PANEL_POPULATION = SummarizeConfig(statistics=["cell_counts", "cell_proportions"])
PANEL_INTERACTION = SummarizeConfig(
    statistics=[
        "cell_counts",
        StatisticSpec(name="interaction_strength_matrix", parameters={"radius": 25.0}),
    ]
)


@pytest.fixture(scope="module")
def ensure_fixture() -> Path:
    """Build the synthetic fixture if it isn't already on disk."""
    if not FIRST_SIM_DIR.exists():
        import importlib.util

        build_path = FIXTURE_ROOT / "build.py"
        spec = importlib.util.spec_from_file_location("synthetic_build", build_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.build(FIXTURE_ROOT)
    return FIRST_SIM_DIR


def test_physicell_simulation_loads_fixture(ensure_fixture: Path) -> None:
    from spatialtissuepy.synthetic import PhysiCellSimulation

    sim = PhysiCellSimulation.from_output_folder(ensure_fixture)
    assert sim.n_timesteps == 3
    names = set(sim.cell_type_mapping.values())
    assert {"tumor", "effector_T_cell", "M0_macrophage"} <= names
    for i in range(sim.n_timesteps):
        ts = sim.get_timestep(i)
        assert ts.n_cells == 21


def test_summarize_simulation_returns_long_form_dataframe(ensure_fixture: Path) -> None:
    df = summarize_simulation(ensure_fixture, config=PANEL_POPULATION)
    assert list(df.columns) == list(SUMMARY_COLUMNS)
    assert df["time_index"].dtype == np.int64
    assert df["time"].dtype == np.float64
    assert df["value"].dtype == np.float64
    assert sorted(df["time_index"].unique().tolist()) == [0, 1, 2]
    assert len(df) > 0


def test_cell_counts_and_proportions_panel(ensure_fixture: Path) -> None:
    df = summarize_simulation(ensure_fixture, config=PANEL_POPULATION)
    output_names = set(df["statistic"].unique())
    # cell_counts always emits the `n_cells` summary row.
    assert "n_cells" in output_names
    # cell_proportions emits per-type proportion keys; upstream names them
    # `prop_<type>` (we no longer rewrite).
    prop_keys = [n for n in output_names if n.startswith("prop_")]
    assert prop_keys


def test_summary_value_ranges_are_sane(ensure_fixture: Path) -> None:
    df = summarize_simulation(ensure_fixture, config=PANEL_POPULATION)
    # n_cells == 21 in every timepoint of the fixture.
    n_cells_rows = df[df["statistic"] == "n_cells"]
    assert len(n_cells_rows) == 3
    assert (n_cells_rows["value"] == 21.0).all()
    # Proportions lie in [0, 1].
    prop_rows = df[df["statistic"].str.startswith("prop_")]
    assert not prop_rows.empty
    assert prop_rows["value"].between(0.0, 1.0).all()
    assert np.isfinite(prop_rows["value"]).all()


def test_interaction_matrix_keys_use_pipe_delimiter(ensure_fixture: Path) -> None:
    df = summarize_simulation(ensure_fixture, config=PANEL_INTERACTION)
    interaction_rows = df[df["statistic"].str.startswith("interaction_")]
    assert not interaction_rows.empty
    for key in interaction_rows["statistic"].unique():
        assert "|" in key, f"interaction key without `|` separator: {key!r}"


def _load_build_module() -> object:
    import importlib.util

    build_path = FIXTURE_ROOT / "build.py"
    spec = importlib.util.spec_from_file_location("synthetic_build", build_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_cells_timepoint_emits_only_n_cells(tmp_path: Path) -> None:
    """An all-dead timepoint emits the cell_counts row and nothing else."""
    build_mod = _load_build_module()

    sim_dir = tmp_path / "sim_empty"
    sim_dir.mkdir()
    (sim_dir / "PhysiCell_settings.xml").write_text(build_mod._settings_xml_text())  # type: ignore[attr-defined]
    (sim_dir / "output00000000.xml").write_text(
        build_mod._output_xml_text(time_minutes=0.0)  # type: ignore[attr-defined]
    )

    n_features = int(build_mod.N_FEATURES)  # type: ignore[attr-defined]
    n_cols = int(build_mod.N_CELLS_PER_TIMESTEP)  # type: ignore[attr-defined]
    matrix = np.zeros((n_features, n_cols), dtype=np.float64)
    matrix[build_mod.ROW_ID, :] = np.arange(n_cols, dtype=np.float64)  # type: ignore[attr-defined]
    matrix[build_mod.ROW_X, :] = 50.0  # type: ignore[attr-defined]
    matrix[build_mod.ROW_Y, :] = 50.0  # type: ignore[attr-defined]
    matrix[build_mod.ROW_TOTAL_VOLUME, :] = build_mod.DEFAULT_CELL_VOLUME_UM3  # type: ignore[attr-defined]
    matrix[build_mod.ROW_CELL_TYPE, :] = 0  # type: ignore[attr-defined]
    matrix[build_mod.ROW_CURRENT_PHASE, :] = 100.0  # type: ignore[attr-defined]

    savemat(
        str(sim_dir / "output00000000_cells_physicell.mat"),
        {"cells": matrix},
        do_compression=False,
        oned_as="column",
        format="5",
    )

    df = summarize_simulation(sim_dir, config=PANEL_POPULATION)
    assert not df.empty
    assert (df["time_index"] == 0).all()

    # Only the n_cells row should be present; cell_proportions emits nothing
    # on a zero-cell timepoint.
    statistics = set(df["statistic"].unique())
    assert statistics == {"n_cells"}
    n_cells_rows = df[df["statistic"] == "n_cells"]
    assert len(n_cells_rows) == 1
    assert math.isclose(float(n_cells_rows.iloc[0]["value"]), 0.0)
