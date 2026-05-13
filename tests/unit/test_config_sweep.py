"""Unit tests for ``tmelandscape.config.sweep``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tmelandscape.config.sweep import ParameterSpec, SweepConfig


def _valid_param() -> ParameterSpec:
    return ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0)


def _valid_config() -> SweepConfig:
    return SweepConfig(
        parameters=[_valid_param()],
        n_parameter_samples=8,
        n_initial_conditions=2,
        seed=42,
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
            )

    def test_n_parameter_samples_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=0,
                n_initial_conditions=2,
                seed=0,
            )
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=-1,
                n_initial_conditions=2,
                seed=0,
            )

    def test_n_initial_conditions_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=0,
                seed=0,
            )

    def test_sampler_accepts_documented_backends(self) -> None:
        for sampler in ("pyDOE3", "scipy-lhs", "scipy-sobol", "scipy-halton"):
            cfg = SweepConfig(
                parameters=[_valid_param()],
                n_parameter_samples=4,
                n_initial_conditions=2,
                seed=0,
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
                sampler="random",  # type: ignore[arg-type]
            )


class TestRoundTrip:
    def test_parameter_spec_dict_round_trip(self) -> None:
        original = ParameterSpec(name="foo", low=1e-3, high=1.0, scale="log10")
        dumped = original.model_dump()
        rebuilt = ParameterSpec.model_validate(dumped)
        assert rebuilt == original

    def test_sweep_config_dict_round_trip(self) -> None:
        original = SweepConfig(
            parameters=[
                ParameterSpec(name="oxygen_uptake", low=0.1, high=2.0),
                ParameterSpec(name="cycle_rate", low=1e-4, high=1e-2, scale="log10"),
            ],
            n_parameter_samples=16,
            n_initial_conditions=3,
            sampler="scipy-sobol",
            seed=7,
        )
        rebuilt = SweepConfig.model_validate(original.model_dump())
        assert rebuilt == original
