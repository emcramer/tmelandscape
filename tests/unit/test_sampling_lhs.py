"""Tests for the pyDOE3-backed unit-hypercube LHS sampler."""

from __future__ import annotations

import numpy as np

from tmelandscape.sampling.lhs import lhs_unit_hypercube


def test_same_seed_produces_identical_output() -> None:
    a = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=42)
    b = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=42)
    np.testing.assert_array_equal(a, b)


def test_shape_matches_requested_dimensions() -> None:
    samples = lhs_unit_hypercube(n_samples=37, n_dims=5, seed=0)
    assert samples.shape == (37, 5)


def test_samples_lie_in_unit_hypercube() -> None:
    samples = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=7)
    assert samples.min() >= 0.0
    assert samples.max() <= 1.0


def test_no_duplicate_rows_in_a_draw() -> None:
    samples = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=123)
    unique_rows = np.unique(samples, axis=0)
    assert unique_rows.shape[0] == samples.shape[0]


def test_different_seeds_produce_different_samples() -> None:
    a = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=1)
    b = lhs_unit_hypercube(n_samples=50, n_dims=3, seed=2)
    assert not np.array_equal(a, b)
