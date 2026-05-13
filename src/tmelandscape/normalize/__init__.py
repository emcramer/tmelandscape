"""Step 3.5 — normalise spatial-statistic time series between summarise and embed.

The reference oracle is ``reference/00_abm_normalization.py``. The normalisation
preserves time-effect by re-adding the per-timestep mean after standard scaling.

Two binding invariants from the project owner (ADRs 0006 and 0009):

* **Never overwrite the raw ensemble.** Normalisation always writes to a new
  variable (or a new Zarr store), preserving the immutable raw output of
  step 3 for re-runs with different normalisation strategies.
* **Do not drop features by default.** Earlier iterations of the reference
  oracle stripped six cell-density columns; that choice was specific to one
  application of the method, not a property of the algorithm. The default
  behaviour is to normalise every column the user supplies; column dropping
  is an explicit opt-in.

Modules:

* :mod:`tmelandscape.normalize.within_timestep` — default reference algorithm
  (per-step mean -> power transform -> z-score -> +mean).
* :mod:`tmelandscape.normalize.feature_filter` — explicit, user-supplied
  column-drop helper. No built-in list.
* :mod:`tmelandscape.normalize.alternatives` — global / local-time variants.
"""
