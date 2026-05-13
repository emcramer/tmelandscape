"""Step 5 — two-stage clustering of the time-delay-embedded windows.

Reference oracle: ``reference/01_abm_generate_embedding.py`` (clustering section,
lines ~550-710) and ``reference/02_abm_state_space_analysis.marimo.py`` (analysis).

The pipeline is:

1. :mod:`tmelandscape.cluster.leiden` — build a kNN graph over the windowed
   feature space, then run Leiden community detection (``leidenalg``).
   Over-segments deliberately.
2. :mod:`tmelandscape.cluster.meta` — compute the mean of each Leiden community
   in feature space, then run Ward hierarchical clustering on those means to
   merge over-segmented communities into the final ~6 TME states.
3. :mod:`tmelandscape.cluster.selection` — resolution / k selection for both
   stages (Leiden resolution sweep; Ward elbow / silhouette).
4. :mod:`tmelandscape.cluster.labels` — persistence and human-readable state
   labels (Effector-Dominant, Exhausted-Dominant, Immune-Excluded, etc.).

See ADR 0007 for the rationale.
"""
