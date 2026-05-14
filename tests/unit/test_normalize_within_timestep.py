"""Unit tests for :func:`tmelandscape.normalize.within_timestep.normalize_within_timestep`.

Covers the Stream A Phase 3.5 checklist from
``tasks/04-normalize-implementation.md``:

* Determinism (two calls on the same input return byte-identical output).
* Shape preservation.
* ``preserve_time_effect=True`` keeps the per-(timepoint, statistic) mean
  approximately equal to the input mean.
* ``preserve_time_effect=False`` yields per-column mean ~0 and std ~1 on
  non-degenerate inputs.
* Zero-std column passes through the transform unchanged.
* All-NaN column collapses to the configured ``fill_nan_with``.
* Mixed-NaN positions are filled per ``fill_nan_with``.
* Linearity / mean-shift property between the two ``preserve_time_effect``
  modes (the difference is exactly the per-(timepoint, statistic) mean).
"""

from __future__ import annotations

import numpy as np
import pytest

from tmelandscape.normalize.within_timestep import normalize_within_timestep

# --- fixture helpers ---------------------------------------------------------


def _well_conditioned_input(
    n_sim: int = 64, n_timepoint: int = 4, n_stat: int = 5, seed: int = 20260513
) -> np.ndarray:
    """Build a non-degenerate lognormal ensemble.

    Lognormal data is positive, skewed, and has different per-(timepoint,
    statistic) means — the regime the Yeo-Johnson + z-score pipeline was
    designed for. Each ``(timepoint, statistic)`` slab is given a distinct
    per-column scale (lognormal sigma) so the columns are non-degenerate
    and the Yeo-Johnson MLE has a well-defined optimum — no precision
    collapse — while the per-column means are still well separated
    enough to make the ``preserve_time_effect`` assertion meaningful.

    Notes
    -----
    Earlier drafts used a fixed sigma with a large additive shift; that
    combination drove the Yeo-Johnson MLE into a regime where the
    transformed column collapsed to (numerically) a constant, producing
    NaN z-scores. Drawing fresh lognormal samples per ``(timepoint,
    statistic)`` slab avoids that pathology while preserving the
    statistical properties the algorithm cares about.
    """
    rng = np.random.default_rng(seed)
    out = np.empty((n_sim, n_timepoint, n_stat), dtype=np.float64)
    for t in range(n_timepoint):
        for s in range(n_stat):
            # Per-slab mean and sigma so columns differ in both location
            # and scale; sigma stays moderate so the data is not so skewed
            # that yeojohnson collapses.
            mu = 0.5 + 0.3 * t + 0.1 * s
            sigma = 0.4 + 0.05 * s
            out[:, t, s] = rng.lognormal(mean=mu, sigma=sigma, size=n_sim)
    return out


# --- determinism / shape -----------------------------------------------------


def test_normalize_within_timestep_is_deterministic() -> None:
    """Two calls with the same input return byte-identical output."""
    value = _well_conditioned_input()

    out_a = normalize_within_timestep(value)
    out_b = normalize_within_timestep(value)

    assert out_a.shape == out_b.shape
    np.testing.assert_array_equal(out_a, out_b)


def test_normalize_within_timestep_is_deterministic_with_copy() -> None:
    """Determinism holds even if the caller mutates the original buffer
    between calls (i.e. the function does not retain state).
    """
    value = _well_conditioned_input()
    out_a = normalize_within_timestep(value)

    # Mutate the original to prove the function does not leak shared state.
    value_copy = value.copy()
    value[...] = 0.0
    out_b = normalize_within_timestep(value_copy)

    np.testing.assert_array_equal(out_a, out_b)


def test_output_shape_matches_input_shape() -> None:
    value = _well_conditioned_input(n_sim=7, n_timepoint=3, n_stat=4)
    out = normalize_within_timestep(value)
    assert out.shape == value.shape
    assert out.dtype == np.float64


def test_output_dtype_is_float64_even_for_float32_input() -> None:
    """The function promotes the working type to float64 for numerical stability."""
    value = _well_conditioned_input().astype(np.float32)
    out = normalize_within_timestep(value)
    assert out.dtype == np.float64


def test_rejects_non_3d_input() -> None:
    flat = np.zeros((10, 5))
    with pytest.raises(ValueError, match="3D"):
        normalize_within_timestep(flat)


# --- preserve_time_effect=True ----------------------------------------------


def test_preserve_time_effect_keeps_per_step_mean() -> None:
    """With ``preserve_time_effect=True``, the per-(timepoint, statistic)
    mean of the output approximates the per-(timepoint, statistic) mean of
    the input.

    Tolerance: 1e-9 absolute. The output mean is exactly
    ``mean(zscore(yj(input))) + mean(input)``, and ``mean(zscore(...))`` is
    numerically zero (it is a *sample* mean of a z-scored sample, which is
    zero to machine precision when no NaNs are present).
    """
    value = _well_conditioned_input()

    out = normalize_within_timestep(value, preserve_time_effect=True)

    np.testing.assert_allclose(out.mean(axis=0), value.mean(axis=0), atol=1e-9)


# --- preserve_time_effect=False ---------------------------------------------


def test_preserve_time_effect_false_produces_zero_mean() -> None:
    value = _well_conditioned_input()

    out = normalize_within_timestep(value, preserve_time_effect=False)

    # zscore (sample mean) of a finite, non-degenerate slab is zero to
    # numerical precision.
    np.testing.assert_allclose(out.mean(axis=0), 0.0, atol=1e-9)


def test_preserve_time_effect_false_produces_unit_std() -> None:
    value = _well_conditioned_input()

    out = normalize_within_timestep(value, preserve_time_effect=False)

    # ddof=0 matches scipy.stats.zscore's default; the resulting
    # population std is exactly 1 for non-degenerate input.
    np.testing.assert_allclose(out.std(axis=0, ddof=0), 1.0, atol=1e-9)


# --- linearity / mean-shift property ----------------------------------------


def test_preserve_time_effect_is_a_pure_mean_shift() -> None:
    """The only difference between the two modes should be the
    per-(timepoint, statistic) mean added back. Equivalently:
    ``out_preserve - out_no_preserve`` is constant along the n_sim axis
    and equal to the input's per-column mean.
    """
    value = _well_conditioned_input()

    out_preserve = normalize_within_timestep(value, preserve_time_effect=True)
    out_no_preserve = normalize_within_timestep(value, preserve_time_effect=False)

    delta = out_preserve - out_no_preserve

    # Delta is constant across simulations -> std along axis 0 is zero.
    np.testing.assert_allclose(delta.std(axis=0), 0.0, atol=1e-12)
    # Delta equals the per-column input mean.
    np.testing.assert_allclose(delta[0], value.mean(axis=0), atol=1e-12)


# --- zero-std column --------------------------------------------------------


def test_zero_std_column_passes_through_transform_unchanged() -> None:
    """A constant input column should skip the transform entirely. With
    ``preserve_time_effect=False`` the output equals the constant input
    (the reference's ``if x.std() > 0 else x`` branch returns x
    unchanged, and the mean re-addition is disabled).
    """
    constant_value = 3.5
    value = np.full((6, 2, 3), constant_value, dtype=np.float64)

    out = normalize_within_timestep(value, preserve_time_effect=False)

    np.testing.assert_array_equal(out, value)


def test_zero_std_column_matches_reference_behaviour_with_mean_added_back() -> None:
    """Reference behaviour for a constant column: the transform passes
    it through, and ``preserve_time_effect=True`` then adds the mean
    back. The reference's ``custom_normalization(x) if x.std() > 0 else x``
    path produces ``x + mean(x) == 2 * x`` for a constant column.
    """
    constant_value = 3.5
    value = np.full((6, 1, 1), constant_value, dtype=np.float64)

    out = normalize_within_timestep(value, preserve_time_effect=True)

    np.testing.assert_allclose(out, value + constant_value)


# --- NaN handling -----------------------------------------------------------


def test_all_nan_column_collapses_to_fill_value() -> None:
    """An all-NaN column has no finite values; after the transform it
    should be replaced with ``fill_nan_with`` and (since the raw mean
    is NaN) ``preserve_time_effect`` must NOT add NaN back on top.
    """
    value = np.full((5, 2, 3), np.nan, dtype=np.float64)
    fill = 0.0

    out = normalize_within_timestep(value, preserve_time_effect=True, fill_nan_with=fill)

    np.testing.assert_array_equal(out, np.full_like(value, fill))


def test_all_nan_column_uses_custom_fill_value() -> None:
    value = np.full((4, 1, 2), np.nan, dtype=np.float64)
    fill = -7.5

    out = normalize_within_timestep(value, preserve_time_effect=False, fill_nan_with=fill)

    np.testing.assert_array_equal(out, np.full_like(value, fill))


def test_all_nan_column_preserves_nan_when_fill_is_nan() -> None:
    """Passing ``fill_nan_with=np.nan`` is the documented opt-out: NaNs
    are not substituted.
    """
    value = np.full((4, 1, 2), np.nan, dtype=np.float64)

    out = normalize_within_timestep(value, preserve_time_effect=False, fill_nan_with=np.nan)

    assert np.isnan(out).all()


def test_mixed_nan_positions_are_filled() -> None:
    """A column with a few NaN positions interspersed with valid data:
    the valid positions get the Yeo-Johnson + z-score treatment and the
    NaN positions are filled with ``fill_nan_with``.
    """
    rng = np.random.default_rng(7)
    n_sim = 12
    # One-(timepoint, statistic) column so we can target specific NaN rows.
    value = rng.lognormal(size=(n_sim, 1, 1))
    nan_rows = np.array([2, 5, 9])
    value[nan_rows, 0, 0] = np.nan
    fill = -99.0

    out = normalize_within_timestep(value, preserve_time_effect=False, fill_nan_with=fill)

    # NaN rows -> fill value.
    np.testing.assert_array_equal(out[nan_rows, 0, 0], np.full(nan_rows.shape, fill))

    # Finite rows -> normalised (no NaN, no fill).
    finite_rows = np.setdiff1d(np.arange(n_sim), nan_rows)
    finite_out = out[finite_rows, 0, 0]
    assert np.isfinite(finite_out).all()
    assert not np.any(finite_out == fill)

    # The finite slice should be standard-scaled (zero mean, unit std)
    # because preserve_time_effect=False and the transform saw only the
    # finite rows.
    np.testing.assert_allclose(finite_out.mean(), 0.0, atol=1e-9)
    np.testing.assert_allclose(finite_out.std(ddof=0), 1.0, atol=1e-9)


def test_mixed_nan_with_preserve_time_effect_uses_nanmean() -> None:
    """``preserve_time_effect=True`` adds back the per-column nanmean.
    NaN positions get filled first (so they end up at
    ``fill_nan_with + nanmean``), and finite positions get
    ``zscore + nanmean``.
    """
    rng = np.random.default_rng(11)
    n_sim = 16
    value = rng.lognormal(size=(n_sim, 1, 1)) + 5.0  # large positive mean
    value[[3, 8], 0, 0] = np.nan

    out = normalize_within_timestep(value, preserve_time_effect=True, fill_nan_with=0.0)

    raw_mean = np.nanmean(value, axis=0)
    # Output mean equals raw nanmean: the z-scored finite slice contributes
    # zero, the filled NaN positions contribute (fill_nan_with == 0) plus the
    # mean, so summing across all positions and dividing by n_sim recovers
    # the raw mean exactly.
    np.testing.assert_allclose(out.mean(axis=0), raw_mean, atol=1e-9)


# --- input immutability -----------------------------------------------------


def test_function_does_not_mutate_input() -> None:
    """Pure function contract: the caller's array is untouched."""
    value = _well_conditioned_input()
    snapshot = value.copy()

    _ = normalize_within_timestep(value)

    np.testing.assert_array_equal(value, snapshot)
