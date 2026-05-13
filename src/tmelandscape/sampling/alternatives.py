"""Alternative unit-hypercube samplers backed by ``scipy.stats.qmc``.

These exist so a user can compare pyDOE3's LHS against scipy's optimised LHS,
Sobol, and Halton sequences without touching call sites. The scipy LHS variant
uses ``optimization='random-cd'`` to match the ``physim-calibration`` oracle.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.stats import qmc


def scipy_lhs_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Draw N samples in [0, 1]^d using scipy's optimised Latin Hypercube.

    Uses ``optimization='random-cd'`` (random column-pair swap minimising the
    centered discrepancy), matching the ``physim-calibration`` reference.
    """
    sampler = qmc.LatinHypercube(d=n_dims, optimization="random-cd", seed=seed)
    samples: np.ndarray = sampler.random(n_samples)
    return samples


def sobol_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Draw N samples in [0, 1]^d using a scrambled Sobol' sequence.

    Notes
    -----
    Sobol' balance properties require ``n_samples`` to be a power of two. If it
    is not, a :class:`UserWarning` is emitted (scipy emits its own as well) and
    the requested number of points is returned anyway.
    """
    if n_samples > 0 and (n_samples & (n_samples - 1)) != 0:
        warnings.warn(
            f"Sobol' balance properties require n_samples to be a power of 2; "
            f"got n_samples={n_samples}.",
            UserWarning,
            stacklevel=2,
        )
    sampler = qmc.Sobol(d=n_dims, scramble=True, seed=seed)
    samples: np.ndarray = sampler.random(n_samples)
    return samples


def halton_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Draw N samples in [0, 1]^d using a scrambled Halton sequence."""
    sampler = qmc.Halton(d=n_dims, scramble=True, seed=seed)
    samples: np.ndarray = sampler.random(n_samples)
    return samples
