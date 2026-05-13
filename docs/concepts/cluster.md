# Concept: clustering (step 5)

> _Placeholder — will be filled in during Phase 5._

Clusters the time-delay-embedded windows into discrete TME states. Default: hierarchical agglomerative clustering with Ward linkage (matches the LCSS paper). Cluster count is selected via WSS-elbow with `kneed`; silhouette and gap statistic are also available.
