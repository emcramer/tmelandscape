"""Unit tests for :class:`tmelandscape.config.embedding.EmbeddingConfig`.

Contract under test (see ``tasks/05-embedding-implementation.md`` and
ADR 0009):

* ``window_size`` is required; default construction fails.
* ``window_size`` and ``step_size`` must be ``>= 1``.
* ``extra="forbid"`` rejects unknown kwargs.
* ``drop_statistics`` defaults to ``[]`` (no built-in feature drops, per
  ADR 0009) and is a fresh list per instance.
* ``strategy`` ``Literal`` rejects values other than ``"sliding_window"``.
* The three Dataset-variable names (``source_variable``,
  ``output_variable``, ``averages_variable``) must be pairwise distinct so
  none silently shadows the others in the output Zarr.
* The config round-trips losslessly through JSON.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.embedding import EmbeddingConfig


class TestEmbeddingConfigDefaultConstruction:
    def test_default_construction_fails_window_size_required(self) -> None:
        # ``window_size`` has no default per ADR 0009 (no defensible package
        # default) — bare construction must fail.
        with pytest.raises(ValidationError) as exc_info:
            EmbeddingConfig()  # type: ignore[call-arg]
        assert "window_size" in str(exc_info.value)

    def test_minimal_explicit_construction_succeeds(self) -> None:
        cfg = EmbeddingConfig(window_size=5)
        assert cfg.strategy == "sliding_window"
        assert cfg.window_size == 5
        assert cfg.step_size == 1
        assert cfg.source_variable == "value_normalized"
        assert cfg.output_variable == "embedding"
        assert cfg.averages_variable == "window_averages"
        assert cfg.drop_statistics == []

    def test_accepts_full_explicit_overrides(self) -> None:
        cfg = EmbeddingConfig(
            strategy="sliding_window",
            window_size=50,
            step_size=2,
            source_variable="value",
            output_variable="windowed",
            averages_variable="window_means",
            drop_statistics=["density_tumor", "density_M0_macrophage"],
        )
        assert cfg.window_size == 50
        assert cfg.step_size == 2
        assert cfg.source_variable == "value"
        assert cfg.output_variable == "windowed"
        assert cfg.averages_variable == "window_means"
        assert cfg.drop_statistics == ["density_tumor", "density_M0_macrophage"]


class TestEmbeddingConfigWindowSize:
    def test_window_size_one_accepted(self) -> None:
        cfg = EmbeddingConfig(window_size=1)
        assert cfg.window_size == 1

    def test_window_size_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=0)

    def test_window_size_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=-1)

    def test_window_size_large_value_accepted(self) -> None:
        # The reference uses 50; the LCSS paper goes up to 80. Make sure
        # we don't accidentally cap at any small constant.
        cfg = EmbeddingConfig(window_size=80)
        assert cfg.window_size == 80


class TestEmbeddingConfigStepSize:
    def test_step_size_default_is_one(self) -> None:
        cfg = EmbeddingConfig(window_size=5)
        assert cfg.step_size == 1

    def test_step_size_one_accepted(self) -> None:
        cfg = EmbeddingConfig(window_size=5, step_size=1)
        assert cfg.step_size == 1

    def test_step_size_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, step_size=0)

    def test_step_size_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, step_size=-2)


class TestEmbeddingConfigExtraForbid:
    def test_unknown_kwarg_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, Foo=1)  # type: ignore[call-arg]

    def test_unknown_kwarg_with_real_kwargs_still_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(  # type: ignore[call-arg]
                window_size=5,
                step_size=2,
                also_normalise_z=True,
            )


class TestEmbeddingConfigDropStatistics:
    def test_default_is_empty_list(self) -> None:
        # ADR 0009: no built-in feature-drop list.
        assert EmbeddingConfig(window_size=5).drop_statistics == []

    def test_drop_statistics_default_is_a_fresh_list(self) -> None:
        # default_factory must hand out a fresh list per instance — otherwise
        # mutating one config silently mutates the next-constructed one.
        cfg_a = EmbeddingConfig(window_size=5)
        cfg_b = EmbeddingConfig(window_size=5)
        cfg_a.drop_statistics.append("some_statistic")
        assert cfg_b.drop_statistics == []

    def test_accepts_list_of_strings(self) -> None:
        names = ["alpha", "beta", "gamma"]
        cfg = EmbeddingConfig(window_size=5, drop_statistics=names)
        assert cfg.drop_statistics == names

    def test_accepts_empty_list_explicitly(self) -> None:
        cfg = EmbeddingConfig(window_size=5, drop_statistics=[])
        assert cfg.drop_statistics == []

    def test_rejects_non_string_entries(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, drop_statistics=[1, 2, 3])  # type: ignore[list-item]


class TestEmbeddingConfigVariableNameCollisions:
    def test_output_variable_equals_source_variable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="output_variable"):
            EmbeddingConfig(
                window_size=5,
                source_variable="value_normalized",
                output_variable="value_normalized",
            )

    def test_averages_variable_equals_source_variable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="averages_variable"):
            EmbeddingConfig(
                window_size=5,
                source_variable="value_normalized",
                averages_variable="value_normalized",
            )

    def test_output_variable_equals_averages_variable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="output_variable"):
            EmbeddingConfig(
                window_size=5,
                output_variable="shared_name",
                averages_variable="shared_name",
            )

    def test_collision_error_messages_name_offending_value(self) -> None:
        # The error must be actionable — it should mention the colliding
        # value so the user can find it in their config without grepping.
        with pytest.raises(ValidationError, match="value_normalized"):
            EmbeddingConfig(
                window_size=5,
                output_variable="value_normalized",
            )

    def test_renaming_source_variable_lifts_default_collision(self) -> None:
        # If a user wants ``output_variable="embedding"`` (the default) AND
        # ``source_variable="embedding"``, the collision validator must
        # still fire. Defence-in-depth: the orchestrator could otherwise
        # write the windowed array on top of the input variable's namespace.
        with pytest.raises(ValidationError):
            EmbeddingConfig(
                window_size=5,
                source_variable="embedding",
                # output_variable defaults to "embedding"
            )


class TestEmbeddingConfigVariableNames:
    def test_rejects_empty_source_variable(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, source_variable="")

    def test_rejects_empty_output_variable(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, output_variable="")

    def test_rejects_empty_averages_variable(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, averages_variable="")


class TestEmbeddingConfigStrategy:
    def test_default_is_sliding_window(self) -> None:
        assert EmbeddingConfig(window_size=5).strategy == "sliding_window"

    def test_rejects_unknown_strategy(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, strategy="fnn_optimised")  # type: ignore[arg-type]

    def test_rejects_empty_strategy(self) -> None:
        with pytest.raises(ValidationError):
            EmbeddingConfig(window_size=5, strategy="")  # type: ignore[arg-type]


class TestEmbeddingConfigRoundTrip:
    def test_dict_round_trip_with_defaults(self) -> None:
        original = EmbeddingConfig(window_size=5)
        rebuilt = EmbeddingConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_dict_round_trip_with_overrides(self) -> None:
        original = EmbeddingConfig(
            window_size=30,
            step_size=2,
            source_variable="value",
            output_variable="windowed",
            averages_variable="window_means",
            drop_statistics=["a", "b"],
        )
        rebuilt = EmbeddingConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_string_round_trip(self) -> None:
        original = EmbeddingConfig(
            window_size=50,
            step_size=3,
            source_variable="value_normalized",
            output_variable="embedding_v2",
            averages_variable="window_avg_v2",
            drop_statistics=["density_tumor"],
        )
        rebuilt = EmbeddingConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_json_round_trip_preserves_defaults(self) -> None:
        original = EmbeddingConfig(window_size=5)
        rebuilt = EmbeddingConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original
        assert rebuilt.drop_statistics == []
        assert rebuilt.strategy == "sliding_window"
        assert rebuilt.step_size == 1
        assert rebuilt.source_variable == "value_normalized"
        assert rebuilt.output_variable == "embedding"
        assert rebuilt.averages_variable == "window_averages"
