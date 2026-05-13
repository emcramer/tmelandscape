"""Step 3.5 — normalize spatial-statistic time series between summarize and embedding.

The reference oracle is ``reference/00_abm_normalization.py``. The normalization
preserves time-effect by re-adding the per-timestep mean after standard scaling;
see ADR 0006 for the rationale and ADR 0007 for how it interacts with clustering.

Modules:

* :mod:`tmelandscape.normalize.within_timestep` — default reference algorithm
  (per-step mean → power transform → z-score → +mean).
* :mod:`tmelandscape.normalize.feature_filter` — configurable column drop
  (six cell-density features by default).
* :mod:`tmelandscape.normalize.alternatives` — global / local-time variants.
"""
