"""Unit tests for ``tmelandscape.config.sweep``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.sweep import (
    IcSourceOwnData,
    IcSourceStructured,
    ParameterSpec,
    SAParams,
    SweepConfig,
)

_STUB_SOURCE_CSV = "tests/data/ic_source_structured.csv"


def _valid_param() -> ParameterSpec:
    return ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0)


def _valid_ic_source() -> IcSourceOwnData:
    return IcSourceOwnData(source_csv=_STUB_SOURCE_CSV)


def _valid_config() -> SweepConfig:
    return SweepConfig(
        parameters=[_valid_param()],
        n_parameter_samples=8,
        n_initial_conditions=2,
        seed=42,
        ic_source=_valid_ic_source(),
    )


class TestParameterSpec:
    def test_valid_construction_defaults_to_linear(self) -> None:
        spec = ParameterSpec(name="foo", low=0.0, high=1.0)
        assert spec.scale == "linear"

    def test_high_must_be_strictly_above_low(self) -> None:
        with pytest.raises(ValidationError, match="strictly greater"):
            ParameterSpec(name="foo", low=1.0, high=1.0)
        with pytest.raises(ValidationError, match="strictly greater"):
            ParameterSpec(name="foo", low=2.0, high=1.0)

    def test_scale_accepts_linear_and_log10(self) -> None:
        assert ParameterSpec(name="foo", low=0.1, high=1.0, scale="linear").scale == "linear"
        assert ParameterSpec(name="foo", low=0.1, high=1.0, scale="log10").scale == "log10"

    def test_log10_rejects_nonpositive_low(self) -> None:
        # Regression: log10 of 0 or negative silently produced NaN downstream.
        with pytest.raises(ValidationError, match="log10"):
            ParameterSpec(name="foo", low=0.0, high=1.0, scale="log10")
        with pytest.raises(ValidationError, match="log10"):
            ParameterSpec(name="foo", low=-1e-4, high=1.0, scale="log10")

    def test_log10_accepts_strictly_positive_bounds(self) -> None:
        spec = ParameterSpec(name="foo", low=1e-6, high=1.0, scale="log10")
        assert spec.scale == "log10"

    def test_linear_still_allows_nonpositive_low(self) -> None:
        spec = ParameterSpec(name="foo", low=-1.0, high=1.0, scale="linear")
        assert spec.low == -1.0

    def test_scale_rejects_other_strings(self) -> None:
        with pytest.raises(ValidationError):
            ParameterSpec(name="foo", low=0.1, high=1.0, scale="logarithmic")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            ParameterSpec(name="foo", low=0.1, high=1.0, scale="log")  # type: ignore[arg-type]


class TestSweepConfig:
    def test_valid_construction(self) -> None:
        cfg = _valid_config()
        assert cfg.sampler == "pyDOE3"
        assert cfg.n_parameter_samples == 8
        assert cfg.n_initial_conditions == 2
        assert cfg.seed == 42
        assert len(cfg.parameters) == 1

    def test_requires_at_least_one_parameter(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[],
                n_parameter_samples=8,
                n_initial_conditions=2,
                seed=0,
                ic_source=_valid_ic_source(),
            )

    def test_n_parameter_samples_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=0,
                n_initial_conditions=2,
                seed=0,
                ic_source=_valid_ic_source(),
            )
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=-1,
                n_initial_conditions=2,
                seed=0,
                ic_source=_valid_ic_source(),
            )

    def test_n_initial_conditions_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=0,
                seed=0,
                ic_source=_valid_ic_source(),
            )

    def test_sampler_accepts_documented_backends(self) -> None:
        for sampler in ("pyDOE3", "scipy-lhs", "scipy-sobol", "scipy-halton"):
            cfg = SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=2,
                seed=0,
                ic_source=_valid_ic_source(),
                sampler=sampler,  # type: ignore[arg-type]
            )
            assert cfg.sampler == sampler

    def test_sampler_rejects_unknown_backend(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=2,
                seed=0,
                ic_source=_valid_ic_source(),
                sampler="random",  # type: ignore[arg-type]
            )


class TestIcSource:
    def test_ic_source_is_required(self) -> None:
        with pytest.raises(ValidationError, match="ic_source"):
            SweepConfig(  # type: ignore[call-arg]
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=2,
                seed=0,
            )

    def test_own_data_mode_parses(self) -> None:
        cfg = SweepConfig.model_validate(
            {
                "parameters": [{"name": "x", "low": 0.0, "high": 1.0}],
                "n_parameter_samples": 4,
                "n_initial_conditions": 2,
                "seed": 0,
                "ic_source": {"mode": "own_data", "source_csv": _STUB_SOURCE_CSV},
            }
        )
        assert isinstance(cfg.ic_source, IcSourceOwnData)
        assert cfg.ic_source.source_csv == _STUB_SOURCE_CSV

    def test_structured_mode_parses_with_description(self) -> None:
        cfg = SweepConfig.model_validate(
            {
                "parameters": [{"name": "x", "low": 0.0, "high": 1.0}],
                "n_parameter_samples": 4,
                "n_initial_conditions": 2,
                "seed": 0,
                "ic_source": {
                    "mode": "structured",
                    "source_csv": _STUB_SOURCE_CSV,
                    "description": "tumor disc + CD8 annulus",
                },
            }
        )
        assert isinstance(cfg.ic_source, IcSourceStructured)
        assert cfg.ic_source.description == "tumor disc + CD8 annulus"

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig.model_validate(
                {
                    "parameters": [{"name": "x", "low": 0.0, "high": 1.0}],
                    "n_parameter_samples": 4,
                    "n_initial_conditions": 2,
                    "seed": 0,
                    "ic_source": {"mode": "made_up", "source_csv": _STUB_SOURCE_CSV},
                }
            )

    def test_ic_defaults(self) -> None:
        cfg = _valid_config()
        assert cfg.ic_scaffold_strategy == "uniform_random"
        assert cfg.ic_network_mode == "radius"
        assert cfg.ic_network_radius_um is None
        assert isinstance(cfg.ic_sa_params, SAParams)
        assert cfg.ic_sa_params.initial_temp == 10.0
        assert cfg.ic_sa_params.final_temp == 0.01
        assert cfg.ic_sa_params.cooling_rate == 0.9997
        assert cfg.ic_sa_params.max_iterations == 60_000


class TestRoundTrip:
    def test_parameter_spec_dict_round_trip(self) -> None:
        original = ParameterSpec(name="foo", low=1e-3, high=1.0, scale="log10")
        dumped = original.model_dump()
        rebuilt = ParameterSpec.model_validate(dumped)
        assert rebuilt == original

    def test_sweep_config_dict_round_trip_own_data(self) -> None:
        original = SweepConfig(
            parameters=[
                ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0),
                ParameterSpec(name="cycle_rate", low=1e-4, high=1e-2, scale="log10"),
            ],
            n_parameter_samples=16,
            n_initial_conditions=3,
            sampler="scipy-sobol",
            seed=7,
            ic_source=IcSourceOwnData(source_csv=_STUB_SOURCE_CSV),
        )
        rebuilt = SweepConfig.model_validate(original.model_dump())
        assert rebuilt == original

    def test_sweep_config_dict_round_trip_structured(self) -> None:
        original = SweepConfig(
            parameters=[_valid_param()],
            n_parameter_samples=4,
            n_initial_conditions=2,
            seed=0,
            ic_source=IcSourceStructured(
                source_csv=_STUB_SOURCE_CSV,
                description="tumor disc",
            ),
            ic_network_radius_um=15.0,
        )
        rebuilt = SweepConfig.model_validate(original.model_dump())
        assert rebuilt == original
