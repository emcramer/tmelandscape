"""Alternative normalisation strategies.

This module is the registry anchor for future v0.4.x algorithm additions
(e.g. ``feature_distribution_normalization``, ``local_time_normalization``).
v0.4.0 ships a single non-default strategy here: :func:`normalize_identity`,
a true passthrough.

Why ship a passthrough?

* It exercises the "swap strategies" code path in the orchestrator without
  any algorithmic noise, which is useful both as a baseline (no-op
  normalisation, for diffing against raw) and as a fixture for tests that
  want to assert orchestrator behaviour independently of the reference
  algorithm's numerical output.
* It documents the function signature future strategies will adopt
  (``(value, **_) -> np.ndarray``), keeping the registry pattern coherent
  before more algorithms land.
"""

from __future__ import annotations

import numpy as np


def normalize_identity(value: np.ndarray, **_: object) -> np.ndarray:
    """Passthrough normalisation: return the input array unchanged.

    Parameters
    ----------
    value
        Any ``np.ndarray``. Shape and dtype are preserved.
    **_
        Accepted and ignored. Lets callers pass the same kwargs they would
        give a real strategy (``preserve_time_effect``, ``fill_nan_with``,
        ...) without code branches at the call site.

    Returns
    -------
    np.ndarray
        The input array, returned by reference (no copy). Use this strategy
        as a baseline for diffing or as a test hook when you want to verify
        orchestrator plumbing independently of any numerical transform.
    """
    return value
