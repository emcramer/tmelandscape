# 0007 — Two-stage clustering: Leiden + Ward-on-means

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

ADR 0003 and the original development plan assumed clustering was a single scipy hierarchical agglomerative step with Ward linkage, following the LCSS paper's description ("hierarchical agglomerative clustering using the Euclidean distance and Ward criterion"). Phase 1 reference audit revealed that the actual upstream implementation (`reference/01_abm_generate_embedding.py` lines ~550–710) uses a **two-stage** procedure:

1. **Stage 1 — Leiden community detection on a kNN graph.** Build a kNN graph (`sklearn.neighbors.kneighbors_graph`) over the time-delay-embedded windowed feature space. Run `leidenalg.find_partition` with a `ModularityVertexPartition` (or similar). This intentionally over-segments the data into many small communities.

2. **Stage 2 — Ward on Leiden cluster means.** Compute the per-community mean feature vector for each Leiden community. Run `scipy.cluster.hierarchy.linkage(..., method='ward')` on those means. Cut the dendrogram at the elbow / silhouette-optimal point to produce the final ~6 TME states.

This two-stage decomposition is intentional: Leiden is good at finding fine-grained graph structure but doesn't expose a natural number-of-clusters parameter; Ward on the centroids of Leiden's output recovers a parsimonious final partition while inheriting Leiden's locality sensitivity. The LCSS paper's single-line description compresses the two stages.

## Decision

Adopt the two-stage Leiden + Ward-on-means as the **default** clustering pipeline for tmelandscape v1. Submodule layout:

```
src/tmelandscape/cluster/
├── __init__.py
├── leiden.py        # Stage 1: kNN graph + Leiden community detection
├── meta.py          # Stage 2: Ward on cluster means
├── selection.py     # Leiden resolution sweep + Ward elbow/silhouette
└── labels.py        # State-label persistence + interpretable names
```

Add `leidenalg`, `python-igraph`, and `networkx` to **core dependencies** (not optional). Users who skip clustering (e.g. only run `sample` + `summarize`) accept the small install cost in exchange for a single-`uv sync` workflow.

A future `method=` argument may expose `'ward-only'` for users who want the LCSS-paper-simplified pipeline, but the default is `'leiden+ward'`.

## Consequences

- Numerical agreement with the upstream reference is preserved.
- `tmelandscape.cluster.fit_clusters(...)` returns both Leiden labels and the final Ward labels, plus the meta-dendrogram, so users can inspect either level.
- The `Landscape` bundle on disk stores both label arrays and the linkage matrix — projection (future module) can choose which level to map onto.
- Core deps grow: `leidenalg` (compiled extension; wheels available for x86_64 macOS/Linux + arm64 macOS), `python-igraph` (compiled extension; wheels available), `networkx` (pure Python).
- The reference's `cluster_leiden` function uses an unweighted variant (`graph_unweighted.es['weight'] = 1.0`). tmelandscape will support both weighted and unweighted Leiden; default to unweighted to match the reference.

## Alternatives considered

- **Ward-only (matches LCSS paper literally):** simpler code, no Leiden/igraph deps, but diverges from the actual upstream pipeline. Numerical-agreement tests against the three real Zenodo sims would fail. Rejected.
- **Leiden-only (no meta-clustering):** Leiden's clusters are too fine-grained and depend on the resolution parameter in ways that aren't stable across simulations. Rejected.
- **Ward-only with Leiden behind a feature flag:** deferred. Adding the flag later is cheap if needed.
