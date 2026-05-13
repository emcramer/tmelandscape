"""Unit tests for ``tmelandscape.summarize.registry``.

These tests exercise :func:`compute_statistic` against a tiny synthetic
``SpatialTissueData``. If a particular ``spatialtissuepy`` submodule is
missing (optional extras not installed), the affected statistic is skipped
via :func:`pytest.importorskip`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.summarize.registry import KNOWN_STATISTICS, compute_statistic

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def spatial_data() -> Any:
    """Return a tiny three-cell-type ``SpatialTissueData``.

    Skips the test module if ``spatialtissuepy`` cannot be imported (e.g.
    upstream dep gap during CI bring-up).
    """
    pytest.importorskip("spatialtissuepy.core.spatial_data")
    from spatialtissuepy.core.spatial_data import SpatialTissueData

    rng = np.random.default_rng(0)
    # 12 cells, 4 per type, scattered in a 100um x 100um box. Small enough
    # to stay well under the 2s-per-test budget but large enough that each
    # cell type has > 1 cell (needed for centrality-by-type and the
    # interaction matrix).
    coords = rng.uniform(0.0, 100.0, size=(12, 2))
    cell_types = np.array(["tumor"] * 4 + ["effector_T_cell"] * 4 + ["M0_macrophage"] * 4)
    return SpatialTissueData(coordinates=coords, cell_types=cell_types)


@pytest.fixture(scope="module")
def cell_graph(spatial_data: Any) -> Any:
    """Return a proximity ``CellGraph`` built once for the module."""
    pytest.importorskip("spatialtissuepy.network.cell_graph")
    from spatialtissuepy.network.cell_graph import CellGraph

    return CellGraph.from_spatial_data(spatial_data, method="proximity", radius=30.0)


@pytest.fixture(scope="module")
def default_config() -> SummarizeConfig:
    return SummarizeConfig()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKnownStatistics:
    def test_known_statistics_is_frozenset_of_str(self) -> None:
        assert isinstance(KNOWN_STATISTICS, frozenset)
        assert all(isinstance(name, str) for name in KNOWN_STATISTICS)

    def test_known_statistics_covers_lcss_default(self) -> None:
        for name in SummarizeConfig().statistics:
            assert name in KNOWN_STATISTICS


class TestComputeStatistic:
    @pytest.mark.parametrize(
        "stat_name",
        # Parametrise over the LCSS-default panel so a missing handler
        # surfaces here rather than at runtime in the driver.
        SummarizeConfig().statistics,
    )
    def test_default_statistic_returns_nonempty_float_dict(
        self,
        stat_name: str,
        spatial_data: Any,
        cell_graph: Any,
        default_config: SummarizeConfig,
    ) -> None:
        result = compute_statistic(
            stat_name,
            spatial_data=spatial_data,
            graph=cell_graph,
            config=default_config,
        )
        assert isinstance(result, dict)
        assert len(result) > 0, f"{stat_name} produced no outputs"
        for key, value in result.items():
            assert isinstance(key, str)
            # All outputs must be plain Python floats so downstream Zarr /
            # pandas code doesn't have to handle numpy scalars.
            assert isinstance(value, float), f"{stat_name}[{key!r}] is {type(value)}"

    def test_unknown_name_raises_keyerror(
        self,
        spatial_data: Any,
        cell_graph: Any,
        default_config: SummarizeConfig,
    ) -> None:
        with pytest.raises(KeyError, match="totally_made_up_stat"):
            compute_statistic(
                "totally_made_up_stat",
                spatial_data=spatial_data,
                graph=cell_graph,
                config=default_config,
            )

    def test_cell_counts_total_matches_n_cells(
        self,
        spatial_data: Any,
        cell_graph: Any,
        default_config: SummarizeConfig,
    ) -> None:
        out = compute_statistic(
            "cell_counts",
            spatial_data=spatial_data,
            graph=cell_graph,
            config=default_config,
        )
        # Sanity check: cell_counts always reports the grand total under
        # the key ``n_cells``.
        assert out["n_cells"] == float(spatial_data.n_cells)

    def test_cell_type_fractions_sum_to_one(
        self,
        spatial_data: Any,
        cell_graph: Any,
        default_config: SummarizeConfig,
    ) -> None:
        out = compute_statistic(
            "cell_type_fractions",
            spatial_data=spatial_data,
            graph=cell_graph,
            config=default_config,
        )
        # Every output key from this stat should start with the renamed
        # ``fraction_`` prefix (not the upstream ``prop_`` prefix).
        assert all(k.startswith("fraction_") for k in out)
        assert sum(out.values()) == pytest.approx(1.0)

    def test_interaction_strength_matrix_has_pair_keys(
        self,
        spatial_data: Any,
        cell_graph: Any,
        default_config: SummarizeConfig,
    ) -> None:
        out = compute_statistic(
            "interaction_strength_matrix",
            spatial_data=spatial_data,
            graph=cell_graph,
            config=default_config,
        )
        # Three cell types -> upper triangle including diagonal -> 6 pairs.
        assert len(out) == 6
        for key in out:
            assert key.startswith("interaction_")
