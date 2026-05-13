"""Latin Hypercube Sampling in the unit hypercube via pyDOE3.

The default LHS backend for `tmelandscape`. The ``maximin`` criterion is used to
maximise the minimum pairwise distance between points, which gives stronger
space-filling than an un-optimised LHS draw at minor extra cost.
"""

from __future__ import annotations

import numpy as np
from pyDOE3 import lhs


def lhs_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Draw N samples in [0, 1]^d using pyDOE3 LHS.

    Parameters
    ----------
    n_samples
        Number of points to draw.
    n_dims
        Dimensionality of the unit hypercube.
    seed
        RNG seed; same seed -> identical output.

    Returns
    -------
    np.ndarray
        Array of shape ``(n_samples, n_dims)`` with values in ``[0, 1]``.
    """
    rng = np.random.default_rng(seed)
    samples: np.ndarray = lhs(
        n_dims,
        samples=n_samples,
        criterion="maximin",
        seed=rng,
    )
    return samples
