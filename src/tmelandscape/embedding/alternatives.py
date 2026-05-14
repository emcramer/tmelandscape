"""Alternative embedding strategies.

This module is the registry anchor for future v0.5.x algorithm additions
(e.g. ``fnn_optimised_window``, ``mutual_information_lag``). v0.5.0 ships a
single non-default strategy here: :func:`embed_identity`, a true passthrough.

Why ship a passthrough?

* It exercises the "swap strategies" code path in the orchestrator without
  any algorithmic noise, which is useful both as a baseline (no-op
  embedding, for diffing against the windowed result) and as a fixture for
  tests that want to assert orchestrator behaviour independently of the
  reference algorithm's numerical output.
* It documents the function signature future strategies will adopt
  (``(value, **_) -> np.ndarray``), keeping the registry pattern coherent
  before more algorithms land. This mirrors the pattern set by
  :mod:`tmelandscape.normalize.alternatives`.
"""

from __future__ import annotations

import numpy as np


def embed_identity(value: np.ndarray, **_: object) -> np.ndarray:
    """Passthrough embedding: return the input array unchanged.

    Parameters
    ----------
    value
        Any ``np.ndarray``. Shape and dtype are preserved.
    **_
        Accepted and ignored. Lets callers pass the same kwargs they would
        give a real strategy (``window_size``, ``step_size``, ...) without
        code branches at the call site.

    Returns
    -------
    np.ndarray
        The input array, returned by reference (no copy). Use this strategy
        as a baseline for diffing or as a test hook when you want to verify
        orchestrator plumbing independently of any numerical transform.
    """
    return value
