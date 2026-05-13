"""Unit tests for ``tmelandscape.config.summarize``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.summarize import SummarizeConfig, _default_statistics
from tmelandscape.summarize.registry import KNOWN_STATISTICS

# The LCSS-paper default panel. Hard-coded here (rather than reused from
# ``_default_statistics``) so a regression in the default list also breaks
# this test — the partner Reviewer should be able to compare *this list*
# against the contract in ``tasks/03-summarize-implementation.md``.
LCSS_DEFAULT_PANEL: list[str] = [
    "cell_counts",
    "cell_type_fractions",
    "mean_degree_centrality_by_type",
    "mean_closeness_centrality_by_type",
    "mean_betweenness_centrality_by_type",
    "interaction_strength_matrix",
]


class TestDefaults:
    def test_default_construction_succeeds(self) -> None:
        cfg = SummarizeConfig()
        assert cfg.graph_method == "proximity"
        assert cfg.graph_radius_um == 30.0
        assert cfg.n_workers == 1
        assert cfg.include_dead_cells is False

    def test_default_statistics_matches_lcss_panel_exactly(self) -> None:
        # Order and contents must both match the contract.
        assert SummarizeConfig().statistics == LCSS_DEFAULT_PANEL

    def test_default_statistics_helper_agrees_with_field_default(self) -> None:
        assert _default_statistics() == LCSS_DEFAULT_PANEL

    def test_every_default_statistic_is_known(self) -> None:
        # If the registry's KNOWN_STATISTICS shrinks below the default panel,
        # we'd start handing users a config whose default doesn't validate.
        for name in LCSS_DEFAULT_PANEL:
            assert name in KNOWN_STATISTICS, name

    def test_default_factory_returns_fresh_list_each_call(self) -> None:
        # Pydantic's default_factory should not share mutable state across
        # instances; mutating one instance's list must not bleed into another.
        a = SummarizeConfig()
        b = SummarizeConfig()
        a.statistics.append("cell_counts")
        assert b.statistics == LCSS_DEFAULT_PANEL


class TestStatisticsValidation:
    def test_rejects_unknown_statistic_name_with_clear_message(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SummarizeConfig(statistics=["definitely_not_a_real_stat"])
        message = str(exc_info.value)
        assert "definitely_not_a_real_stat" in message
        assert "Unknown statistic" in message

    def test_rejects_mix_of_known_and_unknown(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SummarizeConfig(statistics=["cell_counts", "bogus_metric"])
        message = str(exc_info.value)
        assert "bogus_metric" in message
        # The known one should not be reported as unknown.
        assert "'cell_counts'" not in message.split("Unknown statistic")[-1].split("Known")[0]

    def test_accepts_custom_subset(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts"])
        assert cfg.statistics == ["cell_counts"]

    def test_accepts_empty_statistics_list(self) -> None:
        # Empty is degenerate but not invalid: it just means "compute nothing".
        # If we ever decide otherwise, this test is the canary.
        cfg = SummarizeConfig(statistics=[])
        assert cfg.statistics == []


class TestGraphMethod:
    @pytest.mark.parametrize("method", ["proximity", "knn", "delaunay", "gabriel"])
    def test_accepts_documented_values(self, method: str) -> None:
        cfg = SummarizeConfig(graph_method=method)  # type: ignore[arg-type]
        assert cfg.graph_method == method

    def test_rejects_unknown_method(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(graph_method="voronoi")  # type: ignore[arg-type]

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(graph_method="")  # type: ignore[arg-type]


class TestGraphRadius:
    def test_accepts_positive_radius(self) -> None:
        cfg = SummarizeConfig(graph_radius_um=12.5)
        assert cfg.graph_radius_um == 12.5

    def test_rejects_zero_radius(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(graph_radius_um=0.0)

    def test_rejects_negative_radius(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(graph_radius_um=-1.0)


class TestNWorkers:
    def test_accepts_one_worker(self) -> None:
        cfg = SummarizeConfig(n_workers=1)
        assert cfg.n_workers == 1

    def test_accepts_many_workers(self) -> None:
        cfg = SummarizeConfig(n_workers=32)
        assert cfg.n_workers == 32

    def test_rejects_zero_workers(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(n_workers=0)

    def test_rejects_negative_workers(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(n_workers=-1)


class TestRoundTrip:
    def test_default_roundtrip_via_model_dump(self) -> None:
        original = SummarizeConfig()
        rebuilt = SummarizeConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_customised_roundtrip_preserves_all_fields(self) -> None:
        original = SummarizeConfig(
            statistics=["cell_counts", "cell_type_fractions"],
            graph_method="knn",
            graph_radius_um=42.5,
            n_workers=4,
            include_dead_cells=True,
        )
        dumped = original.model_dump()
        rebuilt = SummarizeConfig.model_validate(dumped)
        assert rebuilt == original
        # Spot-check each field survives intact.
        assert rebuilt.statistics == ["cell_counts", "cell_type_fractions"]
        assert rebuilt.graph_method == "knn"
        assert rebuilt.graph_radius_um == 42.5
        assert rebuilt.n_workers == 4
        assert rebuilt.include_dead_cells is True

    def test_roundtrip_rejects_unknown_statistic_on_revalidate(self) -> None:
        # If someone hand-edits a dumped config to inject a bogus stat, the
        # field_validator must catch it on model_validate.
        dumped = SummarizeConfig().model_dump()
        dumped["statistics"] = ["not_a_thing"]
        with pytest.raises(ValidationError, match="not_a_thing"):
            SummarizeConfig.model_validate(dumped)

    def test_json_string_roundtrip_preserves_all_fields(self) -> None:
        # Regression: the dict round-trip is covered above, but the JSON
        # string path is the surface MCP tools and on-disk artefacts use.
        original = SummarizeConfig(
            statistics=["cell_counts", "interaction_strength_matrix"],
            graph_method="delaunay",
            graph_radius_um=12.5,
            n_workers=2,
            include_dead_cells=True,
        )
        rebuilt = SummarizeConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original
