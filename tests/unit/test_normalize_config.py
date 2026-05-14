"""Unit tests for :class:`tmelandscape.config.normalize.NormalizeConfig`.

Contract under test (see ``tasks/04-normalize-implementation.md`` and
ADR 0009):

* Default construction succeeds with the documented defaults.
* ``extra="forbid"`` rejects unknown kwargs.
* ``drop_columns`` defaults to ``[]`` (no built-in feature drops).
* ``output_variable`` is a non-empty string and must not collide with the
  raw ``value`` array preserved in the output Zarr.
* ``strategy`` Literal rejects values other than ``"within_timestep"``.
* The config round-trips losslessly through JSON.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.normalize import NormalizeConfig


class TestNormalizeConfigDefaults:
    def test_default_construction_succeeds(self) -> None:
        cfg = NormalizeConfig()
        assert cfg.strategy == "within_timestep"
        assert cfg.preserve_time_effect is True
        assert cfg.drop_columns == []
        assert cfg.fill_nan_with == 0.0
        assert cfg.output_variable == "value_normalized"

    def test_drop_columns_default_is_a_fresh_list(self) -> None:
        # default_factory must hand out a fresh list per instance — otherwise
        # mutating one config silently mutates the next-constructed one.
        cfg_a = NormalizeConfig()
        cfg_b = NormalizeConfig()
        cfg_a.drop_columns.append("some_statistic")
        assert cfg_b.drop_columns == []

    def test_accepts_explicit_overrides(self) -> None:
        cfg = NormalizeConfig(
            strategy="within_timestep",
            preserve_time_effect=False,
            drop_columns=["density_tumor", "density_M0_macrophage"],
            fill_nan_with=-1.0,
            output_variable="value_zscore",
        )
        assert cfg.preserve_time_effect is False
        assert cfg.drop_columns == ["density_tumor", "density_M0_macrophage"]
        assert cfg.fill_nan_with == -1.0
        assert cfg.output_variable == "value_zscore"


class TestNormalizeConfigExtraForbid:
    def test_unknown_kwarg_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NormalizeConfig(Foo=1)  # type: ignore[call-arg]

    def test_unknown_kwarg_with_real_kwargs_still_rejected(self) -> None:
        # Co-occurring with valid kwargs must not silently pass the extra.
        with pytest.raises(ValidationError):
            NormalizeConfig(preserve_time_effect=False, also_normalise_z=True)  # type: ignore[call-arg]


class TestNormalizeConfigDropColumns:
    def test_default_is_empty_list(self) -> None:
        # ADR 0009: no built-in feature-drop list.
        assert NormalizeConfig().drop_columns == []

    def test_accepts_list_of_strings(self) -> None:
        names = ["alpha", "beta", "gamma"]
        cfg = NormalizeConfig(drop_columns=names)
        assert cfg.drop_columns == names

    def test_accepts_empty_list_explicitly(self) -> None:
        cfg = NormalizeConfig(drop_columns=[])
        assert cfg.drop_columns == []

    def test_rejects_non_string_entries(self) -> None:
        with pytest.raises(ValidationError):
            NormalizeConfig(drop_columns=[1, 2, 3])  # type: ignore[list-item]


class TestNormalizeConfigOutputVariable:
    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            NormalizeConfig(output_variable="")

    def test_rejects_value_collision(self) -> None:
        # Design call (see config docstring): ``output_variable="value"``
        # would shadow the raw array preserved by the orchestrator for
        # raw-vs-normalised comparison. Fail fast at config-construction.
        with pytest.raises(ValidationError, match="value"):
            NormalizeConfig(output_variable="value")

    def test_accepts_arbitrary_non_value_name(self) -> None:
        cfg = NormalizeConfig(output_variable="value_zscore_v2")
        assert cfg.output_variable == "value_zscore_v2"


class TestNormalizeConfigStrategy:
    def test_default_is_within_timestep(self) -> None:
        assert NormalizeConfig().strategy == "within_timestep"

    def test_rejects_unknown_strategy(self) -> None:
        with pytest.raises(ValidationError):
            NormalizeConfig(strategy="foo")  # type: ignore[arg-type]


class TestNormalizeConfigRoundTrip:
    def test_dict_round_trip_with_defaults(self) -> None:
        original = NormalizeConfig()
        rebuilt = NormalizeConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_dict_round_trip_with_overrides(self) -> None:
        original = NormalizeConfig(
            preserve_time_effect=False,
            drop_columns=["a", "b"],
            fill_nan_with=1.5,
            output_variable="my_norm",
        )
        rebuilt = NormalizeConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_json_string_round_trip(self) -> None:
        original = NormalizeConfig(
            preserve_time_effect=False,
            drop_columns=["density_tumor"],
            fill_nan_with=-99.0,
            output_variable="value_alt",
        )
        rebuilt = NormalizeConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original

    def test_json_round_trip_preserves_defaults(self) -> None:
        original = NormalizeConfig()
        rebuilt = NormalizeConfig.model_validate_json(original.model_dump_json())
        assert rebuilt == original
        assert rebuilt.drop_columns == []
        assert rebuilt.strategy == "within_timestep"


class TestFillNanWithNaNRejection:
    """Regression: `fill_nan_with=NaN` would corrupt JSON round-trip.

    Pydantic serialises NaN as the JSON literal ``null``; reparse then
    fails with `Input should be a valid number`, lossily breaking the
    documented round-trip invariant for any persisted config. The
    validator rejects NaN at construction time so failure surfaces at
    the API boundary.
    """

    def test_rejects_nan_fill_value(self) -> None:
        import math

        with pytest.raises(ValidationError, match="NaN"):
            NormalizeConfig(fill_nan_with=math.nan)

    def test_rejects_numpy_nan_fill_value(self) -> None:
        import numpy as np

        with pytest.raises(ValidationError, match="NaN"):
            NormalizeConfig(fill_nan_with=float(np.nan))

    def test_accepts_finite_fill_value(self) -> None:
        cfg = NormalizeConfig(fill_nan_with=-999.5)
        # Round-trip cleanly: NaN-rejection does not block legitimate fills.
        assert NormalizeConfig.model_validate_json(cfg.model_dump_json()) == cfg
