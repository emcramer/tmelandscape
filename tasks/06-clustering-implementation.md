# 06 — Phase 5 clustering implementation

- **slug:** 06-clustering-implementation
- **status:** pre-drafted, awaiting kick-off
- **owner:** TBD (next orchestrator + 3 buddy-pair teams)
- **opened:** 2026-05-13 (drafted)
- **roadmap link:** Phase 5 — Step 5 clustering (target v0.6.0)

## Context

Step 5 of the pipeline: read the windowed embedding Zarr from Phase 4
and cluster the rows into a small number of discrete tumour-microenvironment
(TME) states. The algorithm is **two-stage Leiden + Ward**, per
[ADR 0007](../docs/adr/0007-two-stage-leiden-ward-clustering.md):

1. **Stage 1.** Build a kNN graph over the embedding rows; run
   Leiden community detection. This intentionally over-segments
   the data into many small communities.
2. **Stage 2.** Compute the mean embedding vector for each Leiden
   community; run scipy Ward hierarchical clustering on those means;
   cut the dendrogram at the user-supplied `n_final_clusters` to
   produce the final TME-state labels. The Ward step de-noises Leiden's
   over-segmentation into the small number of biologically interpretable
   states (the LCSS paper finds 6).

Reference oracle: `reference/01_abm_generate_embedding.py` lines
~519-720. Key details:

- kNN graph: `sklearn.neighbors.kneighbors_graph(metric='euclidean')`,
  default `n_neighbors = int(np.sqrt(n_windows))`.
- igraph wrapper: `ig.Graph(edges, directed=False)`; weights set to 1.0
  for unweighted Leiden.
- Leiden: `leidenalg.find_partition(graph_unweighted,
  leidenalg.CPMVertexPartition, resolution_parameter=1.0, seed=42)`.
  **The reference uses `CPMVertexPartition`** (not `ModularityVertexPartition`
  — a commented-out alternative).
- Cluster means: groupby Leiden label, mean over embedding rows.
- Ward: `scipy.spatial.distance.pdist(means, metric='euclidean')` →
  `scipy.cluster.hierarchy.linkage(D, method='ward')`.
- Final cut: `scipy.cluster.hierarchy.fcluster(Z, t=n_final_clusters,
  criterion='maxclust')` produces per-Leiden-cluster final-label
  assignments; per-window labels are derived by lookup.

## Binding invariants (from prior ADRs + project owner directives)

1. **Never overwrite the embedding Zarr.** The input is read-only;
   output is a NEW Zarr at the user-supplied path. Tests verify
   byte-equality of the input store before and after every call.
2. **`n_final_clusters` is a required user input.** The LCSS paper
   reports 6 TME states; the package does not bake "6" in. No default.
3. **The embedding array is passed through verbatim** into the output
   Zarr alongside the new label arrays so downstream consumers can do
   raw-vs-clustered comparison without re-running the embedding step.
4. **Three public surfaces.** Python API + CLI + MCP tool. Integration
   test proves equivalence across all three.

## Public API (frozen — every Implementer must match these signatures)

### Config — `tmelandscape.config.cluster`

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ClusterConfig(BaseModel):
    """User-supplied configuration for `cluster_ensemble`."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["leiden_ward"] = "leiden_ward"

    # Stage 1 — Leiden on kNN graph
    knn_neighbors: int | None = Field(
        default=None,
        ge=1,
        description=(
            "k for the kNN graph. None ⇒ heuristic int(sqrt(n_windows)). "
            "Required reading the reference: ~15 is reasonable for small "
            "ensembles, but the reference uses sqrt-n."
        ),
    )
    leiden_partition: Literal["CPM", "Modularity", "RBConfiguration"] = "CPM"
    leiden_resolution: float = Field(default=1.0, gt=0.0)
    leiden_seed: int = Field(default=42)

    # Stage 2 — Ward on Leiden cluster means
    n_final_clusters: int = Field(..., ge=2)   # REQUIRED, no default

    # Variable naming
    source_variable: str = Field(default="embedding", min_length=1)
    leiden_labels_variable: str = Field(default="leiden_labels", min_length=1)
    final_labels_variable: str = Field(default="cluster_labels", min_length=1)
    cluster_means_variable: str = Field(default="leiden_cluster_means", min_length=1)
    linkage_variable: str = Field(default="linkage_matrix", min_length=1)

    @model_validator(mode="after")
    def _no_collisions(self) -> "ClusterConfig":
        # Five variable names must all be distinct (else dict-dedupe on
        # data_vars silently drops one).
        names = [
            self.source_variable,
            self.leiden_labels_variable,
            self.final_labels_variable,
            self.cluster_means_variable,
            self.linkage_variable,
        ]
        if len(set(names)) != len(names):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                f"variable names must all be distinct; duplicates: {duplicates}"
            )
        return self
```

### Algorithm — `tmelandscape.cluster.leiden_ward`

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class ClusterResult:
    leiden_labels: np.ndarray         # (n_window,) int — Leiden community for each row
    final_labels: np.ndarray          # (n_window,) int — Ward-cut final cluster (1..n_final_clusters)
    leiden_cluster_means: np.ndarray  # (n_leiden_clusters, n_feature) float64
    linkage_matrix: np.ndarray        # ((n_leiden_clusters - 1), 4) float64
    leiden_to_final: np.ndarray       # (n_leiden_clusters,) int — Leiden→final mapping
    n_leiden_clusters: int
    knn_neighbors_used: int


def cluster_leiden_ward(
    embedding: np.ndarray,
    *,
    knn_neighbors: int | None,
    leiden_partition: str = "CPM",
    leiden_resolution: float = 1.0,
    leiden_seed: int = 42,
    n_final_clusters: int,
) -> ClusterResult:
    """Two-stage Leiden + Ward clustering of an embedding matrix.

    Parameters
    ----------
    embedding
        ``(n_window, n_feature)`` float array. Each row is one window.
    knn_neighbors
        k for the kNN graph. ``None`` ⇒ ``int(sqrt(n_window))`` per the
        reference heuristic. Stored on the result as
        ``knn_neighbors_used`` so callers can introspect what the
        heuristic chose.
    leiden_partition
        Which leidenalg partition type to use:
        - ``"CPM"`` → ``leidenalg.CPMVertexPartition`` (reference).
        - ``"Modularity"`` → ``leidenalg.ModularityVertexPartition``.
        - ``"RBConfiguration"`` → ``leidenalg.RBConfigurationVertexPartition``.
    leiden_resolution, leiden_seed
        Leiden parameters; defaults match the reference.
    n_final_clusters
        Number of final TME states to cut the Ward dendrogram into.
        Must be >= 2 and <= the number of Leiden clusters discovered
        (the Ward step raises a clear error if `n_final_clusters >
        n_leiden_clusters`).

    Returns
    -------
    ClusterResult
        See dataclass docstring.
    """
```

Pure function: no I/O, no global numpy random (seed plumbed through),
deterministic given the same inputs and seed.

Implementation notes:

- Build kNN: `sklearn.neighbors.kneighbors_graph(embedding, n_neighbors=k,
  metric='euclidean', mode='connectivity', include_self=False)`.
  Convert sparse → igraph via `nonzero()` → `ig.Graph(edges,
  directed=False)`. Unweight edges for Leiden (set all weights to 1.0).
- Leiden: `leidenalg.find_partition(graph_unweighted,
  <PartitionClass>, resolution_parameter=leiden_resolution,
  seed=leiden_seed)`.
- Cluster means: `np.array([embedding[leiden_labels == c].mean(axis=0)
  for c in unique_leiden])`. Order rows by sorted Leiden label so
  `leiden_to_final[c]` indexes by community id directly.
- Ward: `scipy.spatial.distance.pdist(means, metric='euclidean')` →
  `scipy.cluster.hierarchy.linkage(D, method='ward')` →
  `scipy.cluster.hierarchy.fcluster(Z, t=n_final_clusters,
  criterion='maxclust')`.
- Final per-window labels: `leiden_to_final[leiden_labels]`.

### Zarr orchestrator — `tmelandscape.cluster.__init__`

```python
from pathlib import Path
from tmelandscape.config.cluster import ClusterConfig

def cluster_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: ClusterConfig,
) -> Path:
    """Read a windowed-embedding Zarr (from Phase 4), run two-stage
    clustering, write a NEW Zarr at ``output_zarr``.

    Refuses to overwrite an existing ``output_zarr``. Input is read-only
    (byte-equality verified in tests).

    Output Zarr layout
    ------------------
    Dimensions:
        window (passed through from input)
        embedding_feature (passed through from input)
        statistic (passed through from input — for `window_averages`)
        leiden_cluster (new — n_leiden_clusters)
        linkage_step (new — n_leiden_clusters - 1)
        linkage_field (new — fixed at 4: idx_a, idx_b, distance, n_in_cluster)
    Data variables:
        embedding              (window, embedding_feature)  — passed through
        window_averages        (window, statistic)          — passed through (if present in input)
        <leiden_labels_variable>   (window,)                 — new int array
        <final_labels_variable>    (window,)                 — new int array
        <cluster_means_variable>   (leiden_cluster, embedding_feature) — new float64
        <linkage_variable>         (linkage_step, linkage_field)        — new float64
    Coordinates along `window` (passed through from input):
        simulation_id, window_index_in_sim, start_timepoint, end_timepoint,
        parameter_combination_id, ic_id, parameter_<name>.
    Provenance .zattrs:
        cluster_config (JSON), n_leiden_clusters, knn_neighbors_used,
        n_final_clusters, source_input_zarr, source_variable,
        created_at_utc, tmelandscape_version.
        Forwarded from input if present: source_embedding_config,
        source_normalize_config, source_manifest_hash.
    """
```

## Stream allocation (3 buddy pairs — mirrors Phase 3.5 / 4)

### Pair A — algorithm

**Implementer A1** writes:

- `src/tmelandscape/cluster/leiden_ward.py` — `cluster_leiden_ward`
  per the contract, plus the `ClusterResult` dataclass.
- `tests/unit/test_cluster_leiden_ward.py` — covers:
  - Determinism: same seed → byte-identical output. Verify by hashing
    `result.leiden_labels` + `result.final_labels` over two calls.
  - Shape: 100-row, 20-feature synthetic embedding with two well-separated
    Gaussian blobs and `n_final_clusters=2` yields a 2-cluster
    `final_labels`. (Leiden may produce more communities, but Ward
    collapses to 2.)
  - Partition type literal: `leiden_partition` accepts "CPM",
    "Modularity", "RBConfiguration"; rejects others at call-site or
    config-level (orchestrator may dispatch).
  - kNN heuristic: passing `knn_neighbors=None` on a 64-row embedding
    sets `knn_neighbors_used == 8`.
  - `n_final_clusters > n_leiden_clusters` raises a clear `ValueError`.
  - 1-feature embedding (degenerate): no crash; the test confirms
    behaviour rather than asserting cluster identity.
  - `embedding` not mutated by the function.

**Reviewer A2** audits A1's work:

- Reference fidelity to `reference/01_abm_generate_embedding.py` lines
  ~519-720.
- Determinism: even with `np.random.default_rng` plumbed correctly,
  does `leidenalg.find_partition`'s seed truly stabilise across
  multiple runs? Run the algorithm 5 times on a fixed input and
  compare.
- igraph conversion correctness: edge list deduplication, undirected
  semantics, weight handling (the reference sets weights to 1.0 then
  passes the unweighted graph).
- Ward step: `fcluster(..., t=n_final_clusters, criterion='maxclust')`
  returns 1-based labels. Confirm orchestrator-side handling is
  consistent.
- House-style: pure function, mypy strict, ruff clean.

### Pair B — Zarr orchestrator

**Implementer B1** writes:

- `src/tmelandscape/cluster/__init__.py` — `cluster_ensemble` per
  the contract. Mirror the Phase 3.5 / 4 orchestrator patterns:
  - Input via `xr.open_zarr` context manager.
  - Pre-existence guard on `output_zarr`.
  - Defence-in-depth: all five variable names must be distinct
    (Stream C's config validator catches this too; orchestrator
    repeats for safety).
  - Materialise `embedding` to numpy; call Stream A's algorithm.
  - Build output Dataset with embedding + window_averages
    passed through, plus the four new arrays.
  - Provenance forwarding from input attrs.
  - Partial-output cleanup on `to_zarr` failure.
- `tests/unit/test_cluster_ensemble.py` — input immutability, output
  pre-existence guard, variable-collision guard, provenance .zattrs,
  per-window coord propagation, `window_averages` passthrough when
  present in input, missing `source_variable` raises clearly.

**Reviewer B2** audits B1's work — mirror Phase 3.5 / 4 reviewer
checklists.

### Pair C — config + alternatives

**Implementer C1** writes:

- `src/tmelandscape/config/cluster.py` — `ClusterConfig` per the
  contract.
- `src/tmelandscape/cluster/alternatives.py` — `cluster_identity`
  (returns single-cluster labels, all zeros) as passthrough baseline
  / future-strategy anchor.
- `tests/unit/test_cluster_config.py` — required `n_final_clusters`,
  literal validations, the 5-way variable-collision validator, JSON
  round-trip, `extra="forbid"`.
- `tests/unit/test_cluster_alternatives.py` — `cluster_identity` shape
  and zero-fill.

**Reviewer C2** audits C1's work — mirror Phase 3.5 / 4 reviewer
checklists.

## Integration (orchestrator, after all three pairs return)

1. Apply review findings.
2. Write CLI: `src/tmelandscape/cli/cluster.py` (verb `tmelandscape
   cluster`).
3. Strategy-discovery CLI: `tmelandscape cluster-strategies list`.
4. MCP tools: `cluster_ensemble_tool` + `list_cluster_strategies_tool`.
   Register on the MCP server.
5. Integration test: `tests/integration/test_clustering_end_to_end.py` —
   Python API + CLI + MCP equivalence on a synthetic embedding Zarr.
6. Docs: `docs/concepts/cluster.md` (already a placeholder; fill in
   with the algorithm description + Pydantic field table + worked
   example).
7. Update STATUS.md + ROADMAP.md.
8. Bump to v0.6.0; verify all 247+ existing tests still pass plus the
   new clustering tests; commit; tag; push.

## House-style invariants (binding on every Implementer)

Same as Phases 3.5 / 4. See `AGENTS.md` and previous task files
(`tasks/04-normalize-implementation.md`,
`tasks/05-embedding-implementation.md`) for the full list.

## Session log

- 2026-05-13 (Claude Code orchestrator, handoff prep): Task file
  pre-drafted with frozen API contracts. Reference algorithm
  re-confirmed against `reference/01_abm_generate_embedding.py`
  lines ~519-720. Ready for the next agent team to kick off Wave 1.
