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
    # The maximin criterion maximises minimum pairwise distance; it requires
    # at least 2 points to have a pairwise distance to optimise. Fall back to
    # an un-optimised draw for the degenerate n=1 case (still a valid LHS).
    criterion = "maximin" if n_samples >= 2 else None
    samples: np.ndarray = lhs(
        n_dims,
        samples=n_samples,
        criterion=criterion,
        seed=rng,
    )
    return samples
