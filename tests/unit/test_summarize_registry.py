"""Unit tests for ``tmelandscape.summarize.registry`` (post ADR 0009).

The registry no longer hardcodes a panel. It queries ``spatialtissuepy``'s
global registry dynamically and dispatches via ``StatisticsPanel.compute``.
"""

from __future__ import annotations

import numpy as np

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.summarize.registry import (
    available_metric_names,
    compute_panel,
    describe_metric,
    list_available_statistics,
    rewrite_interaction_keys_with_types,
)


def _tiny_spatial_data() -> object:
    """Build a 6-cell, 3-type SpatialTissueData for tests."""
    from spatialtissuepy.core import SpatialTissueData

    rng = np.random.default_rng(0)
    coords = rng.uniform(0.0, 50.0, size=(6, 2))
    types = np.array(
        [
            "tumor",
            "tumor",
            "M0_macrophage",
            "M0_macrophage",
            "effector_T_cell",
            "effector_T_cell",
        ]
    )
    return SpatialTissueData(coordinates=coords, cell_types=types)


class TestAvailableMetricNames:
    def test_returns_a_frozenset(self) -> None:
        names = available_metric_names()
        assert isinstance(names, frozenset)

    def test_includes_classic_metrics(self) -> None:
        names = available_metric_names()
        for n in ("cell_counts", "cell_proportions", "interaction_strength_matrix"):
            assert n in names, f"{n!r} should be in spatialtissuepy's registry"

    def test_idempotent(self) -> None:
        a = available_metric_names()
        b = available_metric_names()
        assert a == b


class TestDescribeMetric:
    def test_returns_json_friendly_dict(self) -> None:
        info = describe_metric("cell_counts")
        assert info["name"] == "cell_counts"
        assert isinstance(info["category"], str)
        assert isinstance(info["description"], str)
        assert isinstance(info["parameters"], dict)

    def test_parameter_types_are_strings(self) -> None:
        info = describe_metric("cell_type_ratio")
        for _key, type_name in info["parameters"].items():
            assert isinstance(type_name, str)


class TestListAvailableStatistics:
    def test_returns_a_list_of_dicts(self) -> None:
        catalogue = list_available_statistics()
        assert isinstance(catalogue, list)
        assert all(isinstance(m, dict) for m in catalogue)
        names = {m["name"] for m in catalogue}
        assert "cell_counts" in names


class TestComputePanel:
    def test_default_panel_against_tiny_data(self) -> None:
        cfg = SummarizeConfig(statistics=["cell_counts", "cell_proportions"])
        out = compute_panel(spatial_data=_tiny_spatial_data(), config=cfg)
        assert isinstance(out, dict)
        assert all(isinstance(v, float) for v in out.values())
        assert "n_cells" in out

    def test_interaction_key_rewrite(self) -> None:
        cfg = SummarizeConfig(
            statistics=[{"name": "interaction_strength_matrix", "parameters": {"radius": 25.0}}],
            rewrite_interaction_keys=True,
        )
        out = compute_panel(spatial_data=_tiny_spatial_data(), config=cfg)
        pair_keys = [k for k in out if k.startswith("interaction_") and "|" in k]
        assert pair_keys
        for k in out:
            if k.startswith("interaction_"):
                assert "|" in k, f"interaction key without `|` separator: {k!r}"

    def test_rewrite_disabled_preserves_upstream_keys(self) -> None:
        cfg = SummarizeConfig(
            statistics=[{"name": "interaction_strength_matrix", "parameters": {"radius": 25.0}}],
            rewrite_interaction_keys=False,
        )
        out = compute_panel(spatial_data=_tiny_spatial_data(), config=cfg)
        assert any(k.startswith("interaction_") and "|" not in k for k in out)


class TestRewriteInteractionKeysWithTypes:
    def test_vocabulary_aware_rewrite(self) -> None:
        cell_types = ["tumor", "M0_macrophage", "effector_T_cell"]
        raw = {
            "interaction_tumor_M0_macrophage": 1.0,
            "interaction_M0_macrophage_effector_T_cell": 2.0,
            "interaction_tumor_tumor": 3.0,
            "n_cells": 10.0,
        }
        out = rewrite_interaction_keys_with_types(raw, cell_types)
        assert out["interaction_tumor|M0_macrophage"] == 1.0
        assert out["interaction_M0_macrophage|effector_T_cell"] == 2.0
        assert out["interaction_tumor|tumor"] == 3.0
        assert out["n_cells"] == 10.0

    def test_unknown_pair_falls_back_to_heuristic(self) -> None:
        out = rewrite_interaction_keys_with_types({"interaction_alpha_beta": 1.0}, [])
        assert "interaction_alpha|beta" in out
