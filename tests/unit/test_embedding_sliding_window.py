"""Unit tests for :func:`tmelandscape.embedding.sliding_window.window_trajectory_ensemble`.

Covers the Stream A Phase 4 checklist from
``tasks/05-embedding-implementation.md``:

* Deterministic (two calls on the same input return byte-identical output).
* Shape correctness: ``(n_sim=3, n_tp=10, n_stat=4)`` with ``window_size=5``
  yields ``n_total_windows == 18``, ``embedding.shape == (18, 20)``,
  ``averages.shape == (18, 4)``.
* Step-size: ``window_size=5, step_size=2`` on a 10-timepoint sim yields
  3 windows per sim.
* ``skipped_simulations``: a sim with ``n_timepoint=3`` and
  ``window_size=5`` is skipped and its index lands in
  ``skipped_simulations``.
* NaN handling: a window containing NaN flattens NaN; ``averages`` for
  an all-NaN stat column in a window is NaN, finite columns survive.
* ``n_sim=0``: returns a ``WindowedEnsemble`` with zero-length arrays.
* Flatten ordering: ``np.ravel(order="C")`` reference comparison on a
  hand-built small case.
* Pure-function: input array is unmodified after the call.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from tmelandscape.embedding.sliding_window import (
    WindowedEnsemble,
    window_trajectory_ensemble,
)

# --- fixture helpers ---------------------------------------------------------


def _deterministic_input(
    n_sim: int = 3, n_timepoint: int = 10, n_statistic: int = 4, seed: int = 20260513
) -> np.ndarray:
    """Build a well-behaved random ensemble for shape/determinism tests."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(size=(n_sim, n_timepoint, n_statistic))


# --- determinism ------------------------------------------------------------


def test_deterministic_two_calls_same_output() -> None:
    """Two calls on the same input produce byte-identical results."""
    value = _deterministic_input()

    out_a = window_trajectory_ensemble(value, window_size=5)
    out_b = window_trajectory_ensemble(value, window_size=5)

    np.testing.assert_array_equal(out_a.embedding, out_b.embedding)
    np.testing.assert_array_equal(out_a.averages, out_b.averages)
    np.testing.assert_array_equal(out_a.simulation_index, out_b.simulation_index)
    np.testing.assert_array_equal(out_a.window_index_in_sim, out_b.window_index_in_sim)
    np.testing.assert_array_equal(out_a.start_timepoint, out_b.start_timepoint)
    np.testing.assert_array_equal(out_a.end_timepoint, out_b.end_timepoint)
    assert out_a.skipped_simulations == out_b.skipped_simulations


# --- shape correctness ------------------------------------------------------


def test_shape_correctness_3sims_10tp_4stats_w5() -> None:
    """``(n_sim=3, n_tp=10, n_stat=4)`` with ``window_size=5`` ->
    18 total windows; embedding (18, 20); averages (18, 4).
    """
    value = _deterministic_input(n_sim=3, n_timepoint=10, n_statistic=4)

    result = window_trajectory_ensemble(value, window_size=5)

    # (10 - 5) // 1 + 1 == 6 per sim, times 3 sims == 18 total.
    assert result.embedding.shape == (18, 5 * 4)
    assert result.averages.shape == (18, 4)
    assert result.simulation_index.shape == (18,)
    assert result.window_index_in_sim.shape == (18,)
    assert result.start_timepoint.shape == (18,)
    assert result.end_timepoint.shape == (18,)
    assert result.skipped_simulations == []

    # Dtypes
    assert result.embedding.dtype == np.float64
    assert result.averages.dtype == np.float64
    assert result.simulation_index.dtype == np.int64
    assert result.window_index_in_sim.dtype == np.int64
    assert result.start_timepoint.dtype == np.int64
    assert result.end_timepoint.dtype == np.int64

    # End-timestep convention: inclusive, == start + window_size - 1.
    np.testing.assert_array_equal(result.end_timepoint, result.start_timepoint + 5 - 1)

    # Per-sim window counts: each sim should appear 6 times consecutively.
    np.testing.assert_array_equal(
        result.simulation_index,
        np.repeat(np.arange(3, dtype=np.int64), 6),
    )
    # window_index_in_sim cycles 0..5 for each sim.
    np.testing.assert_array_equal(
        result.window_index_in_sim,
        np.tile(np.arange(6, dtype=np.int64), 3),
    )


# --- step size --------------------------------------------------------------


def test_step_size_2_on_10tp_sim_yields_3_windows_per_sim() -> None:
    """``window_size=5, step_size=2`` on a 10-timepoint sim ->
    ``(10 - 5) // 2 + 1 == 3`` windows per sim.
    """
    n_sim = 2
    value = _deterministic_input(n_sim=n_sim, n_timepoint=10, n_statistic=3)

    result = window_trajectory_ensemble(value, window_size=5, step_size=2)

    n_per_sim = 3
    assert result.embedding.shape == (n_sim * n_per_sim, 5 * 3)
    assert result.averages.shape == (n_sim * n_per_sim, 3)

    # Start timepoints for the first sim should be [0, 2, 4].
    np.testing.assert_array_equal(
        result.start_timepoint[:n_per_sim], np.array([0, 2, 4], dtype=np.int64)
    )
    # Window indices within sim are still [0, 1, 2] regardless of step size.
    np.testing.assert_array_equal(
        result.window_index_in_sim[:n_per_sim], np.array([0, 1, 2], dtype=np.int64)
    )
    # End timepoints inclusive: start + 4.
    np.testing.assert_array_equal(
        result.end_timepoint[:n_per_sim], np.array([4, 6, 8], dtype=np.int64)
    )


def test_step_size_larger_than_remainder_still_yields_one_window() -> None:
    """``window_size == n_timepoint`` with any ``step_size`` yields exactly
    one window per sim, with start=0 and end=W-1.
    """
    value = _deterministic_input(n_sim=4, n_timepoint=5, n_statistic=2)

    result = window_trajectory_ensemble(value, window_size=5, step_size=7)

    assert result.embedding.shape == (4, 5 * 2)
    np.testing.assert_array_equal(result.start_timepoint, np.zeros(4, dtype=np.int64))
    np.testing.assert_array_equal(result.end_timepoint, np.full(4, 4, dtype=np.int64))


# --- skipped simulations ----------------------------------------------------


def test_skipped_simulations_when_too_short() -> None:
    """A sim with ``n_timepoint=3`` and ``window_size=5`` contributes no
    windows; its index lands in ``skipped_simulations``.
    """
    # Build a per-sim ragged ensemble by padding short sims with NaN. The
    # signature only accepts a single 3D array, so we represent shorter
    # sims as full-length NaN rows. But the skipped-sim contract is about
    # ``n_timepoint`` being too small for the *whole array*, so we test
    # that case here.
    value = _deterministic_input(n_sim=2, n_timepoint=3, n_statistic=2)

    result = window_trajectory_ensemble(value, window_size=5)

    assert result.embedding.shape == (0, 5 * 2)
    assert result.averages.shape == (0, 2)
    assert result.simulation_index.shape == (0,)
    # Every sim is too short -> all indices skipped.
    assert result.skipped_simulations == [0, 1]


def test_skipped_simulations_returns_list_of_python_ints() -> None:
    """The ``skipped_simulations`` field is a plain Python ``list[int]``
    so it round-trips cleanly through JSON / Pydantic in the orchestrator.
    """
    value = _deterministic_input(n_sim=3, n_timepoint=2, n_statistic=2)

    result = window_trajectory_ensemble(value, window_size=4)

    assert isinstance(result.skipped_simulations, list)
    for idx in result.skipped_simulations:
        # int (not np.int64) so the orchestrator can JSON-serialize the
        # list without an explicit cast.
        assert type(idx) is int
    assert result.skipped_simulations == [0, 1, 2]


# --- NaN handling -----------------------------------------------------------


def test_nan_in_window_flattens_to_nan_in_embedding() -> None:
    """A NaN at ``(sim, timepoint, stat)`` propagates into every window
    that covers that timepoint, in the flattened embedding row.
    """
    n_sim, n_tp, n_stat = 1, 6, 2
    value = np.arange(n_sim * n_tp * n_stat, dtype=np.float64).reshape(n_sim, n_tp, n_stat)
    # Place a single NaN at (sim=0, timepoint=2, stat=1).
    value[0, 2, 1] = np.nan

    result = window_trajectory_ensemble(value, window_size=3)

    # Each sim contributes (6 - 3) // 1 + 1 == 4 windows.
    # Windows starting at t=0, t=1, t=2 all cover t=2. Window starting at
    # t=3 does not.
    assert result.embedding.shape == (4, 3 * 2)
    nan_rows = np.isnan(result.embedding).any(axis=1)
    np.testing.assert_array_equal(nan_rows, np.array([True, True, True, False]))


def test_averages_uses_nanmean_finite_columns_survive() -> None:
    """In a window where stat-column 0 is all-NaN but stat-column 1 is
    finite, ``averages`` row should be ``[NaN, mean(finite)]``.
    """
    n_sim, n_tp, n_stat = 1, 3, 2
    value = np.zeros((n_sim, n_tp, n_stat), dtype=np.float64)
    # Stat 0 entirely NaN across the only window.
    value[0, :, 0] = np.nan
    # Stat 1: finite values 1, 2, 3 -> mean 2.0.
    value[0, :, 1] = np.array([1.0, 2.0, 3.0])

    # Use catch_warnings as a tripwire: the implementation must silence
    # the ``Mean of empty slice`` RuntimeWarning that nanmean emits for
    # the all-NaN column.
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = window_trajectory_ensemble(value, window_size=3)

    assert result.averages.shape == (1, 2)
    assert np.isnan(result.averages[0, 0])
    assert result.averages[0, 1] == pytest.approx(2.0)


def test_averages_partial_nan_column_uses_finite_entries_only() -> None:
    """If a column within a window has some NaNs and some finite values,
    ``np.nanmean`` averages only the finite entries.
    """
    value = np.array(
        [[[1.0], [np.nan], [3.0], [5.0]]],  # shape (1, 4, 1)
        dtype=np.float64,
    )

    result = window_trajectory_ensemble(value, window_size=3)

    # Two windows: [1, nan, 3] -> mean 2.0; [nan, 3, 5] -> mean 4.0.
    np.testing.assert_allclose(result.averages.ravel(), np.array([2.0, 4.0]))


# --- empty ensemble ---------------------------------------------------------


def test_n_sim_zero_returns_zero_length_arrays() -> None:
    """An empty ensemble (``n_sim=0``) returns a ``WindowedEnsemble``
    with zero-length arrays and no crash.
    """
    value = np.empty((0, 10, 3), dtype=np.float64)

    result = window_trajectory_ensemble(value, window_size=4)

    assert isinstance(result, WindowedEnsemble)
    assert result.embedding.shape == (0, 4 * 3)
    assert result.averages.shape == (0, 3)
    assert result.simulation_index.shape == (0,)
    assert result.window_index_in_sim.shape == (0,)
    assert result.start_timepoint.shape == (0,)
    assert result.end_timepoint.shape == (0,)
    assert result.skipped_simulations == []


# --- flatten ordering -------------------------------------------------------


def test_flatten_uses_row_major_c_order() -> None:
    """Round-trip a hand-built window through ``window_trajectory_ensemble``
    and confirm the flattened row matches ``np.ravel(order="C")`` on the
    same submatrix.
    """
    # One sim, 3 timepoints, 2 statistics. With window_size=3 there is
    # exactly one window, covering the entire slab.
    slab = np.array(
        [
            [10.0, 11.0],
            [20.0, 21.0],
            [30.0, 31.0],
        ],
        dtype=np.float64,
    )
    value = slab[np.newaxis, :, :]  # shape (1, 3, 2)

    result = window_trajectory_ensemble(value, window_size=3)

    expected_flat = np.ravel(slab, order="C")
    # Row-major over (window_size, n_statistic): first row is
    # [10, 11, 20, 21, 30, 31].
    np.testing.assert_array_equal(expected_flat, np.array([10.0, 11.0, 20.0, 21.0, 30.0, 31.0]))
    np.testing.assert_array_equal(result.embedding[0], expected_flat)


def test_flatten_ordering_matches_manual_construction_on_multi_window_sim() -> None:
    """Two consecutive windows on a 4-timepoint sim with window_size=3
    produce concatenated flattened rows that exactly match manual
    ``np.ravel(order="C")`` slicing.
    """
    slab = np.array(
        [
            [1.0, 2.0],
            [3.0, 4.0],
            [5.0, 6.0],
            [7.0, 8.0],
        ],
        dtype=np.float64,
    )
    value = slab[np.newaxis, :, :]

    result = window_trajectory_ensemble(value, window_size=3, step_size=1)

    expected = np.stack(
        [
            np.ravel(slab[0:3, :], order="C"),
            np.ravel(slab[1:4, :], order="C"),
        ]
    )
    np.testing.assert_array_equal(result.embedding, expected)
    # Per-window averages: simple arithmetic means along axis 0.
    np.testing.assert_allclose(
        result.averages,
        np.stack([slab[0:3, :].mean(axis=0), slab[1:4, :].mean(axis=0)]),
    )
    np.testing.assert_array_equal(result.start_timepoint, np.array([0, 1], dtype=np.int64))
    np.testing.assert_array_equal(result.end_timepoint, np.array([2, 3], dtype=np.int64))


# --- input immutability -----------------------------------------------------


def test_function_does_not_mutate_input() -> None:
    """Pure-function contract: the caller's array is untouched after call."""
    value = _deterministic_input()
    snapshot = value.copy()

    _ = window_trajectory_ensemble(value, window_size=5, step_size=2)

    np.testing.assert_array_equal(value, snapshot)


def test_function_does_not_mutate_input_with_nan() -> None:
    """Same immutability guarantee when the input contains NaN."""
    value = _deterministic_input()
    value[0, 3, 1] = np.nan
    value[1, :, 2] = np.nan
    snapshot = value.copy()

    _ = window_trajectory_ensemble(value, window_size=5)

    # NaN positions compare unequal, so use a NaN-aware check.
    np.testing.assert_array_equal(np.isnan(value), np.isnan(snapshot))
    finite_mask = np.isfinite(snapshot)
    np.testing.assert_array_equal(value[finite_mask], snapshot[finite_mask])


# --- input validation -------------------------------------------------------


def test_rejects_non_3d_input() -> None:
    flat = np.zeros((10, 5), dtype=np.float64)
    with pytest.raises(ValueError, match="3D"):
        window_trajectory_ensemble(flat, window_size=2)


def test_rejects_window_size_zero() -> None:
    value = _deterministic_input()
    with pytest.raises(ValueError, match="window_size"):
        window_trajectory_ensemble(value, window_size=0)


def test_rejects_step_size_zero() -> None:
    value = _deterministic_input()
    with pytest.raises(ValueError, match="step_size"):
        window_trajectory_ensemble(value, window_size=3, step_size=0)
