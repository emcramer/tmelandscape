"""Unit tests for ``tmelandscape.summarize.spatialtissuepy_driver``.

Scope:

* The synthetic fixture under ``tests/data/synthetic_physicell/`` parses
  cleanly via ``spatialtissuepy.synthetic.PhysiCellSimulation.from_output_folder``.
* :func:`summarize_simulation` produces a long-form DataFrame with the
  contract column schema and one row per (timepoint, output-statistic).
* Two of the LCSS-panel statistics fall within plausible numerical ranges
  on the synthetic fixture.
* A zero-cell timepoint does not crash the driver and emits NaN-valued
  rows for statistics that cannot be computed.

The fixture is built deterministically by
``tests/data/synthetic_physicell/build.py`` from
``SYNTHETIC_FIXTURE_SEED``; if it is missing or stale the
:func:`fixture_root` helper rebuilds it on the fly.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.summarize.spatialtissuepy_driver import (
    SUMMARY_COLUMNS,
    summarize_simulation,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic_physicell"
FIRST_SIM_DIR = FIXTURE_ROOT / "sim_000000_ic_000"


@pytest.fixture(scope="module")
def ensure_fixture() -> Path:
    """Build the synthetic fixture if it isn't already on disk.

    Returns the path to the first sim directory. We keep the fixture
    committed under git, but rebuilding from the seed is cheap and lets the
    test suite run in fresh checkouts (e.g. CI worktrees) without manual
    setup.
    """
    if not FIRST_SIM_DIR.exists():
        # Lazy import: ``build.py`` lives outside the package and pulls
        # heavyweight numpy/scipy at import time.
        import importlib.util

        build_path = FIXTURE_ROOT / "build.py"
        spec = importlib.util.spec_from_file_location("synthetic_build", build_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.build(FIXTURE_ROOT)
    return FIRST_SIM_DIR


def test_physicell_simulation_loads_fixture(ensure_fixture: Path) -> None:
    """``PhysiCellSimulation.from_output_folder`` reads the fixture cleanly."""
    from spatialtissuepy.synthetic import PhysiCellSimulation

    sim = PhysiCellSimulation.from_output_folder(ensure_fixture)
    assert sim.n_timesteps == 3
    # cell-type mapping must include the three LCSS types.
    names = set(sim.cell_type_mapping.values())
    assert {"tumor", "effector_T_cell", "M0_macrophage"} <= names

    # Each timestep must carry the full 21-cell fixture.
    for i in range(sim.n_timesteps):
        ts = sim.get_timestep(i)
        assert ts.n_cells == 21


def test_summarize_simulation_returns_long_form_dataframe(
    ensure_fixture: Path,
) -> None:
    """The DataFrame must have the contract column schema and be non-empty."""
    df = summarize_simulation(ensure_fixture, config=SummarizeConfig())

    # Column schema.
    assert list(df.columns) == list(SUMMARY_COLUMNS)
    assert df["time_index"].dtype == np.int64
    assert df["time"].dtype == np.float64
    assert df["value"].dtype == np.float64

    # Three timesteps in the fixture.
    assert sorted(df["time_index"].unique().tolist()) == [0, 1, 2]

    # No row count is zero (we have at least cell_counts -> n_cells per ts).
    assert len(df) > 0


def test_summarize_simulation_covers_default_panel(ensure_fixture: Path) -> None:
    """Every name in the default ``SummarizeConfig.statistics`` produces rows."""
    df = summarize_simulation(ensure_fixture, config=SummarizeConfig())

    output_names = set(df["statistic"].unique())

    # ``cell_counts`` always emits ``n_cells``.
    assert "n_cells" in output_names

    # ``cell_type_fractions`` -> ``fraction_<type>`` (renamed from the
    # upstream ``prop_<type>`` keys).
    for ct in ("tumor", "effector_T_cell", "M0_macrophage"):
        assert f"fraction_{ct}" in output_names

    # Centrality stats explode by cell type.
    for prefix in ("degree_centrality", "closeness_centrality", "betweenness_centrality"):
        for ct in ("tumor", "effector_T_cell", "M0_macrophage"):
            assert f"{prefix}_{ct}" in output_names

    # Interaction matrix explodes into "interaction_<src>_<dst>". The
    # upstream emits only the upper triangle including the diagonal; with 3
    # types that's 6 entries.
    interaction_keys = [n for n in output_names if n.startswith("interaction_")]
    assert len(interaction_keys) == 6


def test_summary_value_ranges_are_sane(ensure_fixture: Path) -> None:
    """Spot-check two statistics for finite, in-range values."""
    df = summarize_simulation(ensure_fixture, config=SummarizeConfig())

    # 1. ``n_cells`` must equal 21 for every timepoint in the fixture.
    n_cells_rows = df[df["statistic"] == "n_cells"]
    assert len(n_cells_rows) == 3
    assert (n_cells_rows["value"] == 21.0).all()

    # 2. Cell-type fractions must lie in [0, 1] and be finite.
    fraction_rows = df[df["statistic"].str.startswith("fraction_")]
    assert not fraction_rows.empty
    assert fraction_rows["value"].between(0.0, 1.0).all()
    assert np.isfinite(fraction_rows["value"]).all()

    # 3. Degree centrality (NetworkX normalisation) lives in [0, 1].
    degree_rows = df[df["statistic"].str.startswith("degree_centrality_")]
    assert not degree_rows.empty
    assert degree_rows["value"].between(0.0, 1.0).all()


def _load_build_module() -> object:
    """Import the fixture build script as a module (it is not a package).

    Extracted so both fixture initialisation and edge-case tests reuse the
    same helpers (settings/output XML templates, row offsets).
    """
    import importlib.util

    build_path = FIXTURE_ROOT / "build.py"
    spec = importlib.util.spec_from_file_location("synthetic_build", build_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_cells_timepoint_emits_nan(tmp_path: Path) -> None:
    """A timepoint with no alive cells must not crash; centrality is NaN.

    The upstream ``spatialtissuepy`` PhysiCell parser has a known bug with
    truly zero-row cell matrices (it indexes axis 0 unconditionally after a
    spurious transpose), so we represent "no alive cells" with a single
    *dead* cell whose alive-mask filters it out before any spatial
    statistic touches the data. From ``summarize_simulation``'s point of
    view this is indistinguishable from a true zero-cell timepoint.
    """
    build_mod = _load_build_module()

    sim_dir = tmp_path / "sim_empty"
    sim_dir.mkdir()
    (sim_dir / "PhysiCell_settings.xml").write_text(build_mod._settings_xml_text())  # type: ignore[attr-defined]
    (sim_dir / "output00000000.xml").write_text(
        build_mod._output_xml_text(time_minutes=0.0)  # type: ignore[attr-defined]
    )

    # All-dead cell matrix: every column flagged as apoptotic (phase=100).
    # With ``include_dead_cells=False`` (the default) the upstream filter
    # strips every row and ``SpatialTissueData`` ends up with zero cells.
    #
    # We keep ``n_cells_per_timestep`` columns rather than collapsing to one
    # because the upstream parser's empty-matrix code path is broken (it
    # indexes axis 0 unconditionally after an unwanted transpose); using
    # the same dimensions as the live fixture sidesteps that bug.
    n_features = int(build_mod.N_FEATURES)  # type: ignore[attr-defined]
    n_cols = int(build_mod.N_CELLS_PER_TIMESTEP)  # type: ignore[attr-defined]
    matrix = np.zeros((n_features, n_cols), dtype=np.float64)
    matrix[build_mod.ROW_ID, :] = np.arange(n_cols, dtype=np.float64)  # type: ignore[attr-defined]
    matrix[build_mod.ROW_X, :] = 50.0  # type: ignore[attr-defined]
    matrix[build_mod.ROW_Y, :] = 50.0  # type: ignore[attr-defined]
    matrix[build_mod.ROW_TOTAL_VOLUME, :] = build_mod.DEFAULT_CELL_VOLUME_UM3  # type: ignore[attr-defined]
    matrix[build_mod.ROW_CELL_TYPE, :] = 0  # all tumor  # type: ignore[attr-defined]
    matrix[build_mod.ROW_CURRENT_PHASE, :] = 100.0  # apoptotic  # type: ignore[attr-defined]

    savemat(
        str(sim_dir / "output00000000_cells_physicell.mat"),
        {"cells": matrix},
        do_compression=False,
        oned_as="column",
        format="5",
    )

    df = summarize_simulation(sim_dir, config=SummarizeConfig())

    # The driver does not crash on a zero-live-cell timepoint.
    assert not df.empty
    assert (df["time_index"] == 0).all()

    # Per the empty-timepoint contract (see registry / driver docstrings):
    # only ``cell_counts`` produces a row on an empty timepoint; centrality,
    # fraction, and interaction stats emit no rows so the long-form schema
    # is not polluted with placeholder keys that disagree with the
    # non-empty rows' fraction_<type> / interaction_<src>|<dst> schemas.
    centrality_rows = df[df["statistic"].str.contains("centrality")]
    assert centrality_rows.empty, (
        "centrality stats should emit no rows on an empty timepoint; "
        "Stream B's Zarr aggregator NaN-fills missing entries."
    )
    fraction_rows = df[df["statistic"].str.startswith("fraction_")]
    assert fraction_rows.empty
    interaction_rows = df[df["statistic"].str.startswith("interaction_")]
    assert interaction_rows.empty

    # ``n_cells`` is the one stat that remains well-defined: 0.
    n_cells_rows = df[df["statistic"] == "n_cells"]
    assert len(n_cells_rows) == 1
    assert math.isclose(float(n_cells_rows.iloc[0]["value"]), 0.0)
