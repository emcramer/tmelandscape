"""Sliding-window (time-delay) embedding for ensemble trajectories.

Reference oracle: ``reference/utils.py::window_trajectory_data`` (lines
87-140). The reference operates on a long-form pandas DataFrame keyed by
``(sim_id, time_step)``; this module ports the same algorithm to the
dense ``(n_sim, n_timepoint, n_statistic)`` array layout used by the
rest of the package.

Algorithm (per simulation ``s``, independently):

1. Take its ``(n_timepoint, n_statistic)`` slab.
2. Slide a window of length ``W = window_size`` along the timepoint
   axis with step ``step_size``.
3. For each window position ``i`` (``start = i * step_size``):

   * Flatten the ``(W, n_statistic)`` submatrix to a length-``W * n_statistic``
     vector with ``np.ravel(order="C")`` (row-major).
   * Compute the per-statistic mean across the window's ``W`` timesteps
     using ``np.nanmean``, so NaN-only columns produce NaN means but
     finite columns survive.

4. Skip the simulation if ``n_timepoint < W``; record its index in
   ``skipped_simulations`` for the orchestrator to warn about.

The function is pure: no I/O, no global RNG, no mutation of ``value``.
Output dtype is always ``float64``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass
class WindowedEnsemble:
    """Result of running sliding-window embedding over all simulations.

    Attributes
    ----------
    embedding
        ``(n_total_windows, window_size * n_statistic)`` float64 array.
        Each row is one flattened window (row-major,
        ``np.ravel(order="C")``).
    averages
        ``(n_total_windows, n_statistic)`` float64 array. Per-window
        per-statistic mean over the window's ``window_size`` timesteps,
        computed via ``np.nanmean`` so NaN-only stat columns yield NaN
        but finite columns survive.
    simulation_index
        ``(n_total_windows,)`` ``int64`` array mapping each window back
        to its source simulation's position in the input's
        ``simulation`` dim (i.e. axis 0 of ``value``).
    window_index_in_sim
        ``(n_total_windows,)`` ``int64`` array of each window's offset
        within its source simulation (0, 1, 2, ...). Matches the
        reference's ``window_index_in_sim``.
    start_timepoint
        ``(n_total_windows,)`` ``int64`` array — first timepoint covered
        (``= window_index_in_sim * step_size``).
    end_timepoint
        ``(n_total_windows,)`` ``int64`` array — last timepoint covered
        (inclusive, ``= start_timepoint + window_size - 1``).
    skipped_simulations
        Simulation indices that contributed zero windows because their
        ``n_timepoint < window_size``. The orchestrator surfaces these
        as a structured warning.
    """

    embedding: NDArray[np.float64]
    averages: NDArray[np.float64]
    simulation_index: NDArray[np.int64]
    window_index_in_sim: NDArray[np.int64]
    start_timepoint: NDArray[np.int64]
    end_timepoint: NDArray[np.int64]
    skipped_simulations: list[int]


def window_trajectory_ensemble(
    value: np.ndarray,
    *,
    window_size: int,
    step_size: int = 1,
) -> WindowedEnsemble:
    """Build a sliding-window embedding from a 3D ensemble array.

    Parameters
    ----------
    value
        ``(n_sim, n_timepoint, n_statistic)`` float array. The 3D Zarr
        ``value`` cube. NaN entries (ragged sims, missing stats) are
        tolerated: NaN positions propagate into the flattened windows
        and into ``averages`` (via ``np.nanmean``).
    window_size
        Length of the sliding window in timepoints. Must be >= 1.
    step_size
        Number of timepoints between consecutive window starts. Must be
        >= 1. The reference uses 1.

    Returns
    -------
    WindowedEnsemble
        See dataclass docstring. Embedding/averages dtype is ``float64``;
        index arrays are ``int64``. ``skipped_simulations`` is a plain
        ``list[int]`` of source-axis-0 indices.

    Raises
    ------
    ValueError
        If ``value`` is not 3D, or if ``window_size`` / ``step_size`` are
        below 1.

    Notes
    -----
    Pure function: no I/O, no global RNG, no mutation of ``value``. The
    reference uses a Python double loop; this implementation does the
    same (the inner numpy operations dominate). Empirically the
    bottleneck is ~20 ms per 1000 windows of ``W=50`` with
    ``n_stat=30`` on Python 3.11 — fine for v0.5.0 ensemble sizes
    (~100 sims, ~1000 timepoints). A vectorised
    ``np.lib.stride_tricks.sliding_window_view`` pass is a possible
    v0.5.x optimisation if real-world ensembles outgrow the loop.
    """
    if window_size < 1:
        raise ValueError(f"`window_size` must be >= 1; got {window_size}")
    if step_size < 1:
        raise ValueError(f"`step_size` must be >= 1; got {step_size}")
    if value.ndim != 3:
        raise ValueError(
            f"`value` must be a 3D (n_sim, n_timepoint, n_statistic) array; got ndim={value.ndim}"
        )

    # Promote to float64 without mutating the caller's buffer. ``np.asarray``
    # would alias if ``value`` is already float64; ``np.array(..., copy=False)``
    # likewise. We never write into ``arr`` here, but we still pass it through
    # ``np.asarray`` to guarantee a contiguous float64 view of the data the
    # downstream slicing + flattening operate on.
    arr = np.asarray(value, dtype=np.float64)
    n_sim, n_timepoint, n_statistic = arr.shape

    feature_dim = window_size * n_statistic

    # Pre-count the per-sim window count so we can allocate output arrays
    # exactly once, avoiding any list-of-arrays copy. The reference appends
    # to Python lists; we precompute instead.
    per_sim_window_counts: list[int] = []
    skipped_simulations: list[int] = []
    for s in range(n_sim):
        if n_timepoint < window_size:
            per_sim_window_counts.append(0)
            skipped_simulations.append(s)
            continue
        # Number of valid starts: floor((n_timepoint - window_size) / step_size) + 1
        n_windows_s = (n_timepoint - window_size) // step_size + 1
        per_sim_window_counts.append(n_windows_s)

    n_total_windows = int(sum(per_sim_window_counts))

    # Pre-allocate. For an empty ensemble (n_sim == 0) or a fully-skipped
    # ensemble (every sim too short), n_total_windows == 0 and the loops
    # below are no-ops, producing zero-length arrays of the documented
    # shape.
    embedding = np.empty((n_total_windows, feature_dim), dtype=np.float64)
    averages = np.empty((n_total_windows, n_statistic), dtype=np.float64)
    simulation_index = np.empty(n_total_windows, dtype=np.int64)
    window_index_in_sim = np.empty(n_total_windows, dtype=np.int64)
    start_timepoint = np.empty(n_total_windows, dtype=np.int64)
    end_timepoint = np.empty(n_total_windows, dtype=np.int64)

    # ``np.nanmean`` emits a ``RuntimeWarning("Mean of empty slice")`` when
    # an entire stat column within a window is NaN. The NaN return value is
    # exactly what the contract says we should produce, so silence the
    # warning (mirroring the pattern used in
    # ``tmelandscape.normalize.within_timestep``).
    cursor = 0
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
        for s, n_windows_s in enumerate(per_sim_window_counts):
            if n_windows_s == 0:
                continue
            sim_slab = arr[s]  # shape (n_timepoint, n_statistic)
            for i in range(n_windows_s):
                start = i * step_size
                stop = start + window_size  # exclusive
                window = sim_slab[start:stop, :]  # (window_size, n_statistic)

                embedding[cursor] = np.ravel(window, order="C")
                averages[cursor] = np.nanmean(window, axis=0)
                simulation_index[cursor] = s
                window_index_in_sim[cursor] = i
                start_timepoint[cursor] = start
                end_timepoint[cursor] = stop - 1  # inclusive
                cursor += 1

    # Defensive: cursor should equal n_total_windows by construction. A
    # mismatch would indicate a counting bug; surface it loudly rather
    # than returning a partially-filled buffer.
    if cursor != n_total_windows:  # pragma: no cover - guarded by construction
        raise RuntimeError(
            f"internal error: filled {cursor} windows but expected {n_total_windows}"
        )

    return WindowedEnsemble(
        embedding=embedding,
        averages=averages,
        simulation_index=simulation_index,
        window_index_in_sim=window_index_in_sim,
        start_timepoint=start_timepoint,
        end_timepoint=end_timepoint,
        skipped_simulations=skipped_simulations,
    )
