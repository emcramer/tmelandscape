"""Alternative clustering strategies.

This module is the registry anchor for future v0.6.x algorithm additions
(e.g. ``hdbscan``, ``gmm_bic``). v0.6.0 ships a single non-default strategy
here: :func:`cluster_identity`, a true passthrough that assigns every row to
cluster 0.

Why ship a passthrough?

* It exercises the "swap strategies" code path in the orchestrator without
  any algorithmic noise, which is useful both as a baseline (no-op
  clustering, for diffing against the Leiden+Ward result) and as a fixture
  for tests that want to assert orchestrator behaviour independently of the
  reference algorithm's numerical output.
* It documents the function signature future strategies will adopt
  (``(embedding) -> np.ndarray`` of int64 labels), keeping the registry
  pattern coherent before more algorithms land. This mirrors the pattern set
  by :mod:`tmelandscape.normalize.alternatives` and
  :mod:`tmelandscape.embedding.alternatives`.

See :doc:`/adr/0007-two-stage-leiden-ward-clustering` for the canonical
algorithm and :doc:`/adr/0010-cluster-count-auto-selection` for the
auto-selection policy that the canonical algorithm threads through.
"""

from __future__ import annotations

import numpy as np


def cluster_identity(embedding: np.ndarray) -> np.ndarray:
    """Passthrough baseline: assign every row to cluster 0.

    Parameters
    ----------
    embedding
        ``(n_window, n_feature)`` float array. Only the first dimension is
        read; the feature axis is otherwise ignored.

    Returns
    -------
    np.ndarray
        ``(n_window,)`` int64 array of zeros. Useful as a no-op baseline
        strategy / future-strategy anchor in tests.
    """
    return np.zeros(embedding.shape[0], dtype=np.int64)
