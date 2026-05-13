"""Within-time-step normalization (default).

Reference oracle: ``reference/00_abm_normalization.py``. Implementation deferred
to Phase 3.5; this module exists to anchor the package layout.

Algorithm (from the reference):

1. Group rows by ``time_step``.
2. Compute the mean of each feature column per time step.
3. Apply a power transform (``sklearn.preprocessing.PowerTransformer``) per time step.
4. Z-score normalize the transformed data (``StandardScaler``).
5. Re-add the original per-time-step mean to preserve the temporal trend.
"""

from __future__ import annotations
