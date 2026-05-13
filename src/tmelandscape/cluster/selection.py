"""Cluster-count / resolution selection for both clustering stages.

* Leiden resolution sweep (parameter ``resolution`` of ``leidenalg``).
* Ward cluster-count selection (WSS elbow with ``kneed``, silhouette, gap statistic).

Implementation deferred to Phase 5.
"""

from __future__ import annotations
