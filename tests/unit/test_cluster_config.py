"""Unit tests for :class:`tmelandscape.config.cluster.ClusterConfig`.

Contract under test (see ``tasks/06-clustering-implementation.md``,
ADR 0007 and ADR 0010):

* No-arg construction is valid; ``n_final_clusters`` defaults to ``None``
  (no silent "6 TME states" default per ADR 0010); other auto-selection
  knobs have well-defined defaults.
* Explicit ``n_final_clusters`` integer is accepted iff ``>= 2``.
* ``cluster_count_metric`` is a ``Literal`` over exactly six options
  (three original + three added in v0.7.1 per decision log
  ``2026-05-14-wss-elbow-option-5-accepted.md``).
* ``leiden_partition`` is a ``Literal`` over exactly three partition types.
* ``leiden_resolution`` must be ``> 0``.
* ``cluster_count_min`` and ``cluster_count_max`` must each be ``>= 2``.
* The ``_count_range_consistent`` validator rejects empty ranges
  (``cluster_count_max < cluster_count_min``) and accepts equal endpoints.
* The six Dataset-variable names must be pairwise distinct (else dict-dedupe
  on ``data_vars`` would silently drop one).
* ``extra="forbid"`` rejects unknown kwargs.
* JSON round-trip is lossless.
* ``model_json_schema()`` exposes all fields (smoke test for MCP-tool
  surfacing).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.cluster import ClusterConfig


class TestClusterConfigDefaults:
    def test_no_arg_construction_succeeds(self) -> None:
        cfg = ClusterConfig()
        assert cfg.strategy == "leiden_ward"

    def test_n_final_clusters_default_is_none(self) -> None:
        # ADR 0010: no silent default — auto-selection is the path when None.
        assert ClusterConfig().n_final_clusters is None

    def test_cluster_count_metric_default_is_wss_elbow(self) -> None:
        assert ClusterConfig().cluster_count_metric == "wss_elbow"

    def test_cluster_count_min_default_is_two(self) -> None:
        assert ClusterConfig().cluster_count_min == 2

    def test_cluster_count_max_default_is_none(self) -> None:
        # None ⇒ runtime heuristic min(20, n_leiden_clusters); see contract.
        assert ClusterConfig().cluster_count_max is None

    def test_leiden_seed_default_is_42(self) -> None:
        # 42 matches the reference oracle.
        assert ClusterConfig().leiden_seed == 42

    def test_leiden_partition_default_is_cpm(self) -> None:
        assert ClusterConfig().leiden_partition == "CPM"

    def test_leiden_resolution_default_is_one(self) -> None:
        assert ClusterConfig().leiden_resolution == 1.0

    def test_knn_neighbors_default_is_none(self) -> None:
        assert ClusterConfig().knn_neighbors is None

    def test_variable_name_defaults(self) -> None:
        cfg = ClusterConfig()
        assert cfg.source_variable == "embedding"
        assert cfg.leiden_labels_variable == "leiden_labels"
        assert cfg.final_labels_variable == "cluster_labels"
        assert cfg.cluster_means_variable == "leiden_cluster_means"
        assert cfg.linkage_variable == "linkage_matrix"
        assert cfg.cluster_count_scores_variable == "cluster_count_scores"


class TestClusterConfigNFinalClusters:
    def test_explicit_integer_accepted(self) -> None:
        cfg = ClusterConfig(n_final_clusters=6)
        assert cfg.n_final_clusters == 6

    def test_explicit_two_accepted_minimum(self) -> None:
        cfg = ClusterConfig(n_final_clusters=2)
        assert cfg.n_final_clusters == 2

    def test_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(n_final_clusters=1)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(n_final_clusters=-5)

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(n_final_clusters=0)


class TestClusterConfigClusterCountMetric:
    @pytest.mark.parametrize(
        "metric",
        [
            "wss_elbow",
            "calinski_harabasz",
            "silhouette",
            "wss_lmethod",
            "wss_asymptote_fit",
            "wss_variance_explained",
        ],
    )
    def test_all_six_options_accepted(self, metric: str) -> None:
        cfg = ClusterConfig(cluster_count_metric=metric)  # type: ignore[arg-type]
        assert cfg.cluster_count_metric == metric

    def test_unknown_metric_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_metric="unknown")  # type: ignore[arg-type]

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_metric="")  # type: ignore[arg-type]


class TestClusterConfigLeidenPartition:
    @pytest.mark.parametrize("partition", ["CPM", "Modularity", "RBConfiguration"])
    def test_all_three_options_accepted(self, partition: str) -> None:
        cfg = ClusterConfig(leiden_partition=partition)  # type: ignore[arg-type]
        assert cfg.leiden_partition == partition

    def test_other_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(leiden_partition="Other")  # type: ignore[arg-type]


class TestClusterConfigLeidenResolution:
    def test_resolution_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(leiden_resolution=0)

    def test_resolution_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(leiden_resolution=-0.5)

    def test_resolution_small_positive_accepted(self) -> None:
        cfg = ClusterConfig(leiden_resolution=0.01)
        assert cfg.leiden_resolution == 0.01


class TestClusterConfigClusterCountBounds:
    def test_cluster_count_min_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_min=1)

    def test_cluster_count_min_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_min=0)

    def test_cluster_count_max_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_max=1)

    def test_cluster_count_max_none_accepted(self) -> None:
        # None ⇒ runtime-resolved upper bound; explicitly valid.
        cfg = ClusterConfig(cluster_count_max=None)
        assert cfg.cluster_count_max is None

    def test_cluster_count_min_two_accepted(self) -> None:
        cfg = ClusterConfig(cluster_count_min=2)
        assert cfg.cluster_count_min == 2

    def test_cluster_count_max_two_accepted(self) -> None:
        cfg = ClusterConfig(cluster_count_max=2, cluster_count_min=2)
        assert cfg.cluster_count_max == 2


class TestClusterConfigCountRangeConsistency:
    def test_max_less_than_min_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ClusterConfig(cluster_count_min=5, cluster_count_max=3)
        # Error message must surface both numbers so the user can find
        # them in their config without grepping.
        msg = str(exc_info.value)
        assert "3" in msg
        assert "5" in msg

    def test_max_equal_to_min_accepted(self) -> None:
        cfg = ClusterConfig(cluster_count_min=3, cluster_count_max=3)
        assert cfg.cluster_count_min == 3
        assert cfg.cluster_count_max == 3

    def test_max_greater_than_min_accepted(self) -> None:
        cfg = ClusterConfig(cluster_count_min=2, cluster_count_max=10)
        assert cfg.cluster_count_min == 2
        assert cfg.cluster_count_max == 10

    def test_max_none_does_not_trip_range_validator(self) -> None:
        # cluster_count_max=None ⇒ runtime heuristic; validator must not
        # fire on the implicit "None < min" comparison.
        cfg = ClusterConfig(cluster_count_min=10, cluster_count_max=None)
        assert cfg.cluster_count_min == 10
        assert cfg.cluster_count_max is None


class TestClusterConfigVariableNameCollisions:
    @pytest.mark.parametrize(
        ("field_a", "field_b"),
        [
            ("source_variable", "leiden_labels_variable"),
            ("source_variable", "final_labels_variable"),
            ("source_variable", "cluster_means_variable"),
            ("source_variable", "linkage_variable"),
            ("source_variable", "cluster_count_scores_variable"),
            ("leiden_labels_variable", "final_labels_variable"),
            ("leiden_labels_variable", "cluster_means_variable"),
            ("leiden_labels_variable", "linkage_variable"),
            ("leiden_labels_variable", "cluster_count_scores_variable"),
            ("final_labels_variable", "cluster_means_variable"),
            ("final_labels_variable", "linkage_variable"),
            ("final_labels_variable", "cluster_count_scores_variable"),
            ("cluster_means_variable", "linkage_variable"),
            ("cluster_means_variable", "cluster_count_scores_variable"),
            ("linkage_variable", "cluster_count_scores_variable"),
        ],
    )
    def test_any_pair_collision_rejected(self, field_a: str, field_b: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ClusterConfig(**{field_a: "collision_name", field_b: "collision_name"})
        msg = str(exc_info.value)
        # The duplicates list in the error must name the colliding value.
        assert "collision_name" in msg

    def test_collision_message_lists_duplicate(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            ClusterConfig(
                leiden_labels_variable="shared",
                final_labels_variable="shared",
            )

    def test_three_way_collision_rejected(self) -> None:
        with pytest.raises(ValidationError, match="distinct"):
            ClusterConfig(
                leiden_labels_variable="shared",
                final_labels_variable="shared",
                linkage_variable="shared",
            )

    def test_all_six_distinct_accepted(self) -> None:
        cfg = ClusterConfig(
            source_variable="a",
            leiden_labels_variable="b",
            final_labels_variable="c",
            cluster_means_variable="d",
            linkage_variable="e",
            cluster_count_scores_variable="f",
        )
        assert cfg.source_variable == "a"
        assert cfg.cluster_count_scores_variable == "f"


class TestClusterConfigVariableNameNonEmpty:
    def test_rejects_empty_source_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(source_variable="")

    def test_rejects_empty_leiden_labels_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(leiden_labels_variable="")

    def test_rejects_empty_final_labels_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(final_labels_variable="")

    def test_rejects_empty_cluster_means_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_means_variable="")

    def test_rejects_empty_linkage_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(linkage_variable="")

    def test_rejects_empty_cluster_count_scores_variable(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(cluster_count_scores_variable="")


class TestClusterConfigExtraForbid:
    def test_unknown_kwarg_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(foo="bar")  # type: ignore[call-arg]

    def test_unknown_kwarg_alongside_real_kwargs_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(  # type: ignore[call-arg]
                n_final_clusters=6,
                unknown_field=True,
            )

    def test_dict_validate_rejects_unknown_field(self) -> None:
        # The orchestrator may rebuild a config from a JSON dict; the forbid
        # policy must hold over that path too.
        with pytest.raises(ValidationError):
            ClusterConfig.model_validate({"foo": "bar"})


class TestClusterConfigStrategy:
    def test_default_strategy(self) -> None:
        assert ClusterConfig().strategy == "leiden_ward"

    def test_rejects_unknown_strategy(self) -> None:
        with pytest.raises(ValidationError):
            ClusterConfig(strategy="kmeans")  # type: ignore[arg-type]


class TestClusterConfigRoundTrip:
    def test_dict_round_trip_with_defaults(self) -> None:
        original = ClusterConfig()
        rebuilt = ClusterConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_round_trip_with_overrides(self) -> None:
        original = ClusterConfig(n_final_clusters=6, knn_neighbors=15)
        rebuilt = ClusterConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original
        assert rebuilt.n_final_clusters == 6
        assert rebuilt.knn_neighbors == 15

    def test_json_round_trip_preserves_none_defaults(self) -> None:
        # None values for n_final_clusters / knn_neighbors / cluster_count_max
        # must survive the JSON round-trip rather than collapsing to defaults.
        original = ClusterConfig()
        rebuilt = ClusterConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original
        assert rebuilt.n_final_clusters is None
        assert rebuilt.knn_neighbors is None
        assert rebuilt.cluster_count_max is None

    def test_json_round_trip_with_full_overrides(self) -> None:
        original = ClusterConfig(
            knn_neighbors=20,
            leiden_partition="Modularity",
            leiden_resolution=0.7,
            leiden_seed=7,
            n_final_clusters=5,
            cluster_count_metric="silhouette",
            cluster_count_min=3,
            cluster_count_max=12,
            source_variable="emb",
            leiden_labels_variable="leiden",
            final_labels_variable="final",
            cluster_means_variable="means",
            linkage_variable="linkage",
            cluster_count_scores_variable="scores",
        )
        rebuilt = ClusterConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original


class TestClusterConfigJsonSchema:
    def test_schema_has_properties_dict(self) -> None:
        # Smoke test: the MCP server exposes ClusterConfig.model_json_schema()
        # to clients. Confirm the schema lists every field so agent-facing
        # tooling sees them all.
        schema = ClusterConfig.model_json_schema()
        assert "properties" in schema
        expected_fields = {
            "strategy",
            "knn_neighbors",
            "leiden_partition",
            "leiden_resolution",
            "leiden_seed",
            "n_final_clusters",
            "cluster_count_metric",
            "cluster_count_min",
            "cluster_count_max",
            "source_variable",
            "leiden_labels_variable",
            "final_labels_variable",
            "cluster_means_variable",
            "linkage_variable",
            "cluster_count_scores_variable",
        }
        assert expected_fields.issubset(set(schema["properties"].keys()))
