"""Stage 2 of clustering: Ward hierarchical clustering on Leiden cluster means.

Reference: ``reference/01_abm_generate_embedding.py`` lines ~680-710 (``pdist`` +
``scipy.cluster.hierarchy.linkage(..., method='ward')`` over per-Leiden-community
mean feature vectors). Implementation deferred to Phase 5.
"""

from __future__ import annotations
