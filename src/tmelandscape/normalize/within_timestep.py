"""Within-time-step normalisation (default Phase 3.5 algorithm).

Reference oracle: ``reference/00_abm_normalization.py``. The reference
implementation operates on a long-form pandas DataFrame keyed by
``(sim_id, time_step)`` and applies, per ``time_step`` group:

1. Per-feature mean across simulations (``m_t``).
2. ``scipy.stats.yeojohnson`` per feature column (skipped if std == 0).
3. ``scipy.stats.zscore`` per feature column.
4. ``fillna(0)`` to absorb NaNs the transform might introduce.
5. Add ``m_t`` back if ``preserve_time_effect`` is set.

This module ports that recipe to the dense ``(n_sim, n_timepoint, n_stat)``
array layout used by the rest of the package. The function is pure (no
I/O, no global RNG); randomness is irrelevant — the transform is fully
deterministic given its input.

Edge cases (resolved here, surfaced in the test suite):

* ``scipy.stats.yeojohnson`` rejects non-finite inputs, so we mask NaN
  positions before calling it and re-insert NaN afterwards.
* ``scipy.stats.yeojohnson`` produces nonsense on a zero-variance column
  (its MLE blows up). We therefore short-circuit zero-std columns and
  pass them through unchanged before the z-score step ever sees them,
  matching the reference's ``if x.std() > 0`` guard.
* An all-NaN column has ``m_t = NaN`` and no finite values to transform;
  it is filled with ``fill_nan_with`` and the (NaN) mean is not added
  back, so the column collapses cleanly to the fill value.
"""

from __future__ import annotations

import warnings

import numpy as np
from numpy.typing import NDArray
from scipy.stats import yeojohnson, zscore


def normalize_within_timestep(
    value: NDArray[np.floating],
    *,
    preserve_time_effect: bool = True,
    fill_nan_with: float = 0.0,
) -> NDArray[np.float64]:
    """Apply per-time-step Yeo-Johnson + z-score, optionally re-adding the
    pre-transform per-step mean.

    Parameters
    ----------
    value
        ``(n_sim, n_timepoint, n_stat)`` float array. NaN entries (ragged
        timepoints, all-NaN columns) are tolerated.
    preserve_time_effect
        If True, the per-timepoint, per-statistic mean computed from the
        raw input is added back after standard scaling so the temporal
        trend survives into the embedding step. Default True (reference
        behaviour).
    fill_nan_with
        Scalar substituted for NaN values that emerge from (or persist
        through) the transform. Default ``0.0`` (reference behaviour).
        Pass ``np.nan`` to leave NaNs untouched.

    Returns
    -------
    np.ndarray
        Same-shape ``float64`` array. Deterministic for the same input.
        Float inputs of lower precision (``float32`` etc.) are silently
        promoted to ``float64`` — the underlying ``scipy.stats.yeojohnson``
        + ``zscore`` chain works in double precision, and writing back to
        a lower-precision view of the caller's buffer would silently lose
        precision. Callers passing very large ensembles should expect a
        2x memory hit on the output relative to a float32 input.

    Notes
    -----
    The function is pure: no I/O, no global RNG, no mutation of ``value``.
    Zero-variance columns pass through unchanged (the reference's
    ``if x.std() > 0 else x`` branch). All-NaN columns collapse to
    ``fill_nan_with``.
    """
    if value.ndim != 3:
        raise ValueError(
            f"`value` must be a 3D (n_sim, n_timepoint, n_stat) array; got ndim={value.ndim}"
        )

    # Work on a float64 copy so we can write NaN substitutions without
    # mutating the caller's array and without losing precision on float32
    # inputs.
    arr = np.asarray(value, dtype=np.float64)
    n_sim, n_timepoint, n_stat = arr.shape

    # Per-(timepoint, statistic) mean computed from the *raw* input,
    # before any transformation. NaN entries are skipped (nanmean) so a
    # ragged timepoint does not pull the mean toward zero.
    if n_sim == 0:
        m_t = np.full((n_timepoint, n_stat), np.nan, dtype=np.float64)
    else:
        # ``np.nanmean`` emits a ``RuntimeWarning("Mean of empty slice")``
        # when a column is all-NaN and returns NaN, which is exactly the
        # behaviour we want. Silence the warning rather than the result.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Mean of empty slice", category=RuntimeWarning
            )
            m_t = np.nanmean(arr, axis=0)

    out = np.empty_like(arr)

    # Process each (timepoint, statistic) slab independently. The slabs
    # are 1D over the n_sim axis, mirroring the reference's per-group
    # transform on a single feature column.
    for t in range(n_timepoint):
        for s in range(n_stat):
            column = arr[:, t, s]
            out[:, t, s] = _normalize_column(column)

    # Fill NaNs that survived the transform (zero-std + all-NaN + any
    # transient NaN from zscore on degenerate input) with the user's
    # scalar. We do this *before* re-adding ``m_t`` so the reference's
    # "fillna(0) then add the mean" order is preserved exactly.
    if not np.isnan(fill_nan_with):
        nan_mask = np.isnan(out)
        if nan_mask.any():
            out[nan_mask] = fill_nan_with

    if preserve_time_effect:
        # Broadcast (n_timepoint, n_stat) across the n_sim axis. NaN
        # entries in m_t (all-NaN raw columns) propagate as NaN -> we
        # mask those so the column stays at ``fill_nan_with`` rather
        # than becoming NaN after the addition.
        finite_mean = np.where(np.isnan(m_t), 0.0, m_t)
        out = out + finite_mean[np.newaxis, :, :]

    return out


def _normalize_column(column: NDArray[np.float64]) -> NDArray[np.float64]:
    """Apply Yeo-Johnson + z-score to a single 1D slab.

    Returns a same-length float64 array with NaN at any position that
    started NaN, plus NaN at every position if the column had zero
    variance among its finite entries (zero-std columns are passed
    through unchanged; downstream NaN-fill logic handles the rest).
    """
    n = column.shape[0]
    if n == 0:
        return column.copy()

    finite_mask = np.isfinite(column)
    n_finite = int(finite_mask.sum())

    # No finite values -> the column is all NaN. The reference's
    # ``if x.std() > 0`` guard would short-circuit (std of all-NaN is
    # NaN, which is not > 0), leaving the column unchanged; the
    # subsequent ``fillna(0)`` would then replace every entry. We
    # mirror that by returning the column as-is and letting the caller
    # apply ``fill_nan_with``.
    if n_finite == 0:
        return column.copy()

    finite_values = column[finite_mask]

    # Use ddof=0 to match scipy.stats.zscore's default and the
    # population-variance convention used downstream. The reference
    # used pandas' ddof=1 default in its guard, but the difference is
    # immaterial for the std > 0 test (both are zero iff the column is
    # constant). Using ddof=0 here keeps the guard consistent with the
    # zscore call that follows.
    if float(finite_values.std(ddof=0)) == 0.0:
        # Constant column (after NaN removal): pass through unchanged.
        # The reference returns the raw column in this branch; any NaN
        # entries it carries are filled by the caller's fill_nan_with.
        return column.copy()

    # Yeo-Johnson is undefined on non-finite inputs. Apply it only to
    # the finite slice; reassemble afterwards.
    transformed = np.full(n, np.nan, dtype=np.float64)

    # ``scipy.stats.yeojohnson`` can emit a precision-loss RuntimeWarning
    # for inputs whose MLE-selected lambda collapses the transformed
    # values to (numerically) a constant — e.g. a nearly-constant input
    # column. We swallow that warning here; the downstream zero-std
    # guard catches the collapse and returns the raw column unchanged.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Precision loss occurred in moment calculation",
            category=RuntimeWarning,
        )
        yj_values = yeojohnson(finite_values)[0]

    # Guard against the Yeo-Johnson MLE collapsing the column to a
    # constant (its ``lmbda`` is unbounded for nearly-degenerate inputs).
    # When that happens, zscore would divide by zero and return NaN.
    # The reference is silent on this regime — its toy data never
    # triggers it — but we still want a sensible answer, so we fall
    # back to the raw column (matching the ``std == 0`` short-circuit).
    if float(yj_values.std(ddof=0)) == 0.0:
        return column.copy()

    # zscore on the post-power-transform slice. nan_policy='omit' is
    # unnecessary here because we already removed NaNs, but ddof=0 is
    # the default and matches the reference (which used scipy.stats.zscore).
    zscored = zscore(yj_values, ddof=0)
    transformed[finite_mask] = zscored
    return transformed
