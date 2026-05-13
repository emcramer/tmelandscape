"""Tests for the scipy.qmc-backed unit-hypercube samplers."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from tmelandscape.sampling.alternatives import (
    halton_unit_hypercube,
    scipy_lhs_unit_hypercube,
    sobol_unit_hypercube,
)

Sampler = Callable[[int, int, int], np.ndarray]

# Sobol' requires n to be a power of 2 for balance properties; use 64 in tests
# to avoid the (intentional) warning we emit otherwise.
SAMPLERS: list[tuple[str, Sampler, int]] = [
    ("scipy_lhs", scipy_lhs_unit_hypercube, 50),
    ("sobol", sobol_unit_hypercube, 64),
    ("halton", halton_unit_hypercube, 50),
]


@pytest.mark.parametrize(("name", "sampler", "n_samples"), SAMPLERS)
def test_same_seed_produces_identical_output(name: str, sampler: Sampler, n_samples: int) -> None:
    a = sampler(n_samples, 3, 42)
    b = sampler(n_samples, 3, 42)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize(("name", "sampler", "n_samples"), SAMPLERS)
def test_shape_matches_requested_dimensions(name: str, sampler: Sampler, n_samples: int) -> None:
    samples = sampler(n_samples, 5, 0)
    assert samples.shape == (n_samples, 5)


@pytest.mark.parametrize(("name", "sampler", "n_samples"), SAMPLERS)
def test_samples_lie_in_unit_hypercube(name: str, sampler: Sampler, n_samples: int) -> None:
    samples = sampler(n_samples, 3, 7)
    assert samples.min() >= 0.0
    assert samples.max() <= 1.0


@pytest.mark.parametrize(("name", "sampler", "n_samples"), SAMPLERS)
def test_no_duplicate_rows_in_a_draw(name: str, sampler: Sampler, n_samples: int) -> None:
    samples = sampler(n_samples, 3, 123)
    unique_rows = np.unique(samples, axis=0)
    assert unique_rows.shape[0] == samples.shape[0]


@pytest.mark.parametrize(("name", "sampler", "n_samples"), SAMPLERS)
def test_different_seeds_produce_different_samples(
    name: str, sampler: Sampler, n_samples: int
) -> None:
    a = sampler(n_samples, 3, 1)
    b = sampler(n_samples, 3, 2)
    assert not np.array_equal(a, b)


def test_sobol_warns_on_non_power_of_two() -> None:
    with pytest.warns(UserWarning, match="power of 2"):
        sobol_unit_hypercube(50, 3, seed=42)


def test_sobol_no_warning_on_power_of_two() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # Should not raise: no warnings expected for n=64.
        sobol_unit_hypercube(64, 3, seed=42)
