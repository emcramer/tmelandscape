"""Unit tests for ``tmelandscape.config.summarize`` (post ADR 0009).

Key contract:
- ``SummarizeConfig.statistics`` is required (no default panel).
- Metric names are validated against ``spatialtissuepy``'s live registry.
- Plain strings are accepted as shorthand for ``StatisticSpec(name=...)``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.summarize import StatisticSpec, SummarizeConfig
from tmelandscape.summarize.registry import available_metric_names


class TestSummarizeConfigRequired:
    def test_default_construction_rejects_missing_statistics(self) -> None:
        # No default panel: constructing without `statistics` must fail.
        with pytest.raises(ValidationError, match="statistics"):
            SummarizeConfig()  # type: ignore[call-arg]

    def test_empty_statistics_list_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 1 item"):
            SummarizeConfig(statistics=[])

    def test_unknown_statistic_rejected_with_helpful_message(self) -> None:
        with pytest.raises(ValidationError, match="not_a_metric"):
            SummarizeConfig(statistics=["not_a_metric"])

    def test_plain_string_coerced_to_statistic_spec(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts"])
        assert isinstance(cfg.statistics[0], StatisticSpec)
        assert cfg.statistics[0].name == "cell_counts"
        assert cfg.statistics[0].parameters == {}

    def test_dict_coerced_to_statistic_spec(self) -> None:
        cfg = SummarizeConfig(
            statistics=[
                {"name": "cell_counts", "parameters": {}},
                {"name": "cell_proportions", "parameters": {}},
            ]
        )
        assert len(cfg.statistics) == 2
        assert cfg.statistics[0].name == "cell_counts"

    def test_statistic_spec_passed_through(self) -> None:
        spec = StatisticSpec(name="cell_counts")
        cfg = SummarizeConfig(statistics=[spec])
        assert cfg.statistics[0].name == "cell_counts"

    def test_mixed_string_and_spec_accepted(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts", StatisticSpec(name="cell_proportions")])
        assert [s.name for s in cfg.statistics] == ["cell_counts", "cell_proportions"]


class TestStatisticSpec:
    def test_name_required(self) -> None:
        with pytest.raises(ValidationError):
            StatisticSpec()  # type: ignore[call-arg]

    def test_parameters_default_empty(self) -> None:
        spec = StatisticSpec(name="cell_counts")
        assert spec.parameters == {}

    def test_parameters_accepts_typed_values(self) -> None:
        spec = StatisticSpec(
            name="cell_type_ratio",
            parameters={"numerator": "tumor", "denominator": "M0_macrophage"},
        )
        assert spec.parameters["numerator"] == "tumor"

    def test_extra_keys_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StatisticSpec(name="cell_counts", parameters={}, extra_key="nope")  # type: ignore[call-arg]


class TestSummarizeConfigOtherFields:
    def test_n_workers_minimum_one(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeConfig(statistics=["cell_counts"], n_workers=0)

    def test_include_dead_cells_default_false(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts"])
        assert cfg.include_dead_cells is False

    def test_rewrite_interaction_keys_default_true(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts"])
        assert cfg.rewrite_interaction_keys is True


class TestSummarizeConfigRoundtrip:
    def test_dict_roundtrip(self) -> None:
        original = SummarizeConfig(
            statistics=["cell_counts", "cell_proportions"],
            n_workers=4,
            include_dead_cells=True,
            rewrite_interaction_keys=False,
        )
        rebuilt = SummarizeConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_string_roundtrip(self) -> None:
        original = SummarizeConfig(
            statistics=[
                StatisticSpec(name="cell_counts"),
                StatisticSpec(name="interaction_strength_matrix", parameters={"radius": 25.0}),
            ],
            n_workers=2,
        )
        rebuilt = SummarizeConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_roundtrip_rejects_unknown_statistic_on_revalidate(self) -> None:
        dumped = SummarizeConfig(statistics=["cell_counts"]).model_dump()
        dumped["statistics"] = [{"name": "not_a_metric"}]
        with pytest.raises(ValidationError, match="not_a_metric"):
            SummarizeConfig.model_validate(dumped)


class TestDynamicDiscovery:
    def test_available_metric_names_returns_nonempty_frozenset(self) -> None:
        names = available_metric_names()
        assert isinstance(names, frozenset)
        assert len(names) > 0
        # The classics should always be present in spatialtissuepy.
        assert "cell_counts" in names
        assert "cell_proportions" in names
