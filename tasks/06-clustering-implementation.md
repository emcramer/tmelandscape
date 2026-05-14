# 06 — Phase 5 clustering implementation

- **slug:** 06-clustering-implementation
- **status:** **REVISED 2026-05-13** — auto-selection of `n_final_clusters` added per owner directive (see [ADR 0010](../docs/adr/0010-cluster-count-auto-selection.md)). Ready for Wave 1 kick-off.
- **owner:** TBD (next orchestrator + 3 buddy-pair teams)
- **opened:** 2026-05-13 (drafted), revised 2026-05-13 (auto-selection)
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
   cut the dendrogram at `n_final_clusters` to produce the final
   TME-state labels. The Ward step de-noises Leiden's over-segmentation
   into a small number of biologically interpretable states.

**New as of revision (2026-05-13):** `n_final_clusters` is now
**optional**. When the user omits it, the package picks `k` by
optimising a metric over a candidate range. The default metric is
**WSS elbow** (within-cluster sum of squares; knee detection via
`kneed`). Alternatives are `calinski_harabasz` and `silhouette` from
scikit-learn. See [ADR 0010](../docs/adr/0010-cluster-count-auto-selection.md)
for rationale.

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
2. **`n_final_clusters` has no silent default.** Either the user
   supplies an explicit integer (>= 2), or they leave it `None` and
   the package picks `k` via a tunable metric. There is no baked-in
   "6 TME states" assumption. See [ADR 0010](../docs/adr/0010-cluster-count-auto-selection.md).
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

    # ----- Stage 1 — Leiden on kNN graph -------------------------------
    knn_neighbors: int | None = Field(
        default=None,
        ge=1,
        description=(
            "k for the kNN graph. None ⇒ heuristic int(sqrt(n_windows)). "
            "The reference uses sqrt-n."
        ),
    )
    leiden_partition: Literal["CPM", "Modularity", "RBConfiguration"] = "CPM"
    leiden_resolution: float = Field(default=1.0, gt=0.0)
    leiden_seed: int = Field(default=42)

    # ----- Stage 2 — Ward on Leiden cluster means ---------------------
    # OPTIONAL. None ⇒ auto-select k via `cluster_count_metric` over
    # [cluster_count_min, cluster_count_max]. No package default value.
    n_final_clusters: int | None = Field(default=None, ge=2)

    # Auto-selection knobs (used only when n_final_clusters is None).
    cluster_count_metric: Literal[
        "wss_elbow", "calinski_harabasz", "silhouette"
    ] = "wss_elbow"
    cluster_count_min: int = Field(default=2, ge=2)
    # None ⇒ runtime heuristic: min(12, n_leiden_clusters).
    cluster_count_max: int | None = Field(default=None, ge=2)

    # ----- Variable naming --------------------------------------------
    source_variable: str = Field(default="embedding", min_length=1)
    leiden_labels_variable: str = Field(default="leiden_labels", min_length=1)
    final_labels_variable: str = Field(default="cluster_labels", min_length=1)
    cluster_means_variable: str = Field(default="leiden_cluster_means", min_length=1)
    linkage_variable: str = Field(default="linkage_matrix", min_length=1)
    cluster_count_scores_variable: str = Field(
        default="cluster_count_scores", min_length=1
    )

    @model_validator(mode="after")
    def _no_collisions(self) -> "ClusterConfig":
        # Six variable names must all be distinct (else dict-dedupe on
        # data_vars silently drops one).
        names = [
            self.source_variable,
            self.leiden_labels_variable,
            self.final_labels_variable,
            self.cluster_means_variable,
            self.linkage_variable,
            self.cluster_count_scores_variable,
        ]
        if len(set(names)) != len(names):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                f"variable names must all be distinct; duplicates: {duplicates}"
            )
        return self

    @model_validator(mode="after")
    def _count_range_consistent(self) -> "ClusterConfig":
        if (
            self.cluster_count_max is not None
            and self.cluster_count_max < self.cluster_count_min
        ):
            raise ValueError(
                f"cluster_count_max ({self.cluster_count_max}) must be >= "
                f"cluster_count_min ({self.cluster_count_min})"
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
    # ----- new (auto-selection) -----
    n_final_clusters_used: int        # The k actually used (either user-supplied or auto-picked).
    cluster_count_metric_used: str    # "user_supplied" if user gave a value; otherwise the metric name.
    cluster_count_candidates: np.ndarray  # (n_candidates,) int — the k's evaluated. Empty array if user supplied k.
    cluster_count_scores: np.ndarray  # (n_candidates,) float — metric value at each candidate k. Empty array if user supplied k.


def cluster_leiden_ward(
    embedding: np.ndarray,
    *,
    knn_neighbors: int | None,
    leiden_partition: str = "CPM",
    leiden_resolution: float = 1.0,
    leiden_seed: int = 42,
    n_final_clusters: int | None,
    cluster_count_metric: str = "wss_elbow",
    cluster_count_min: int = 2,
    cluster_count_max: int | None = None,
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
        Number of final TME states to cut the Ward dendrogram into. If
        ``None``, k is picked automatically via ``cluster_count_metric``
        over the candidate range
        ``[cluster_count_min, min(cluster_count_max or 12, n_leiden_clusters)]``.
        If an integer, must be ``>= 2`` and ``<= n_leiden_clusters``; the
        Ward step raises a clear ``ValueError`` otherwise.
    cluster_count_metric
        Used only when ``n_final_clusters is None``:
        - ``"wss_elbow"`` (default): kneed-based knee of the WSS curve.
        - ``"calinski_harabasz"``: argmax of sklearn's CH index.
        - ``"silhouette"``: argmax of sklearn's silhouette score.
    cluster_count_min, cluster_count_max
        Inclusive bounds on the candidate-k range for auto-selection.
        ``cluster_count_max=None`` ⇒ ``min(12, n_leiden_clusters)``.

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
  `scipy.cluster.hierarchy.fcluster(Z, t=k, criterion='maxclust')`.
- Final per-window labels: `leiden_to_final[leiden_labels]`.
- Auto-selection (when `n_final_clusters is None`): delegate to
  `tmelandscape.cluster.selection.select_n_clusters` (see below).

### Cluster-count selection — `tmelandscape.cluster.selection`

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class SelectionResult:
    n_clusters: int
    metric: str                       # "wss_elbow" | "calinski_harabasz" | "silhouette"
    k_candidates: np.ndarray          # (n_candidates,) int — the k's evaluated, sorted ascending
    k_scores: np.ndarray              # (n_candidates,) float — metric value at each k


def select_n_clusters(
    embedding: np.ndarray,
    leiden_labels: np.ndarray,
    linkage_matrix: np.ndarray,
    *,
    metric: str = "wss_elbow",
    k_min: int = 2,
    k_max: int | None = None,
) -> SelectionResult:
    """Pick an optimal ``n_final_clusters`` for Ward cuts of the dendrogram.

    Parameters
    ----------
    embedding
        ``(n_window, n_feature)`` float array — same as the algorithm input.
    leiden_labels
        ``(n_window,)`` int array — Leiden community per row, from Stage 1.
    linkage_matrix
        ``((n_leiden - 1), 4)`` float array — Ward linkage from Stage 2.
    metric
        Which metric to optimise. Options:
        - ``"wss_elbow"``: minimise WSS, knee detected via ``kneed.KneeLocator``
          with ``curve="convex"``, ``direction="decreasing"``. If kneed
          cannot detect a knee (e.g. monotonic-but-no-elbow), fall back to
          the smallest k with the largest marginal-decrease slope.
        - ``"calinski_harabasz"``: ``sklearn.metrics.calinski_harabasz_score``,
          argmax.
        - ``"silhouette"``: ``sklearn.metrics.silhouette_score`` (Euclidean,
          n_window subsample cap to avoid O(n²) blowup on large ensembles),
          argmax.
    k_min, k_max
        Inclusive bounds on the candidate range. ``k_max=None`` ⇒
        ``min(12, n_leiden_clusters)``. If ``k_min > n_leiden_clusters``,
        raise ``ValueError``.

    Returns
    -------
    SelectionResult
        With ``n_clusters`` = the chosen k.

    Notes
    -----
    The function evaluates each candidate by computing per-window final
    labels via ``fcluster(linkage_matrix, t=k, criterion='maxclust')``
    indexed through ``leiden_labels``, then scores the partition.

    WSS for a candidate k is the sum over final clusters of
    ``sum((X[labels == c] - centroid_c) ** 2)``.

    The Calinski-Harabasz and silhouette scores are skipped when only
    one cluster results from the cut (sklearn errors); the function
    treats those k's as ``-inf`` in the scoring array.
    """
```

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
        cluster_count_candidate (new — n_candidates; size 0 if user supplied k)
    Data variables:
        embedding              (window, embedding_feature)  — passed through
        window_averages        (window, statistic)          — passed through (if present in input)
        <leiden_labels_variable>          (window,)                            — new int array
        <final_labels_variable>           (window,)                            — new int array
        <cluster_means_variable>          (leiden_cluster, embedding_feature)  — new float64
        <linkage_variable>                (linkage_step, linkage_field)        — new float64
        <cluster_count_scores_variable>   (cluster_count_candidate,)           — new float64
                                                                                (empty if user supplied k)
    Coordinates along `window` (passed through from input):
        simulation_id, window_index_in_sim, start_timepoint, end_timepoint,
        parameter_combination_id, ic_id, parameter_<name>.
    Coordinate along `cluster_count_candidate`:
        the integer k values evaluated.
    Provenance .zattrs:
        cluster_config (JSON), n_leiden_clusters, knn_neighbors_used,
        n_final_clusters_used, cluster_count_metric_used,
        source_input_zarr, source_variable, created_at_utc,
        tmelandscape_version.
        Forwarded from input if present: source_embedding_config,
        source_normalize_config, source_manifest_hash.
    """
```

## Stream allocation (3 buddy pairs — mirrors Phase 3.5 / 4)

### Pair A — algorithm + auto-selection

**Implementer A1** writes:

- `src/tmelandscape/cluster/leiden_ward.py` — `cluster_leiden_ward`
  per the contract, plus the `ClusterResult` dataclass.
- `src/tmelandscape/cluster/selection.py` — `select_n_clusters` per
  the contract, plus the `SelectionResult` dataclass. **Replace** the
  existing skeleton (currently empty placeholder) entirely.
- `tests/unit/test_cluster_leiden_ward.py` — covers:
  - Determinism: same seed → byte-identical output. Verify by hashing
    `result.leiden_labels` + `result.final_labels` over two calls.
  - Shape: 100-row, 20-feature synthetic embedding with two well-separated
    Gaussian blobs and `n_final_clusters=2` yields a 2-cluster
    `final_labels`. (Leiden may produce more communities, but Ward
    collapses to 2.)
  - Auto-selection (the new path): same synthetic 2-blob fixture with
    `n_final_clusters=None`, `cluster_count_metric="wss_elbow"` →
    `result.n_final_clusters_used == 2` (or whatever the elbow finds —
    if kneed picks 2 reliably for 2-blob data, assert it; otherwise
    assert `2 <= chosen <= 4`).
  - Auto-selection determinism: same input → same chosen k across
    repeated calls.
  - Partition type literal: `leiden_partition` accepts "CPM",
    "Modularity", "RBConfiguration"; rejects others at call-site or
    config-level (orchestrator may dispatch).
  - kNN heuristic: passing `knn_neighbors=None` on a 64-row embedding
    sets `knn_neighbors_used == 8`.
  - `n_final_clusters > n_leiden_clusters` raises a clear `ValueError`.
  - When user supplies k: `cluster_count_metric_used == "user_supplied"`
    and `k_candidates` / `k_scores` are empty arrays.
  - 1-feature embedding (degenerate): no crash; the test confirms
    behaviour rather than asserting cluster identity.
  - `embedding` not mutated by the function.
- `tests/unit/test_cluster_selection.py` — covers:
  - WSS-elbow on a synthetic 3-blob dataset → chooses k=3 (or asserts
    a tight range, given kneed's sensitivity).
  - Calinski-Harabasz argmax on the same fixture matches expectation.
  - Silhouette argmax likewise.
  - `k_min > n_leiden_clusters` raises `ValueError`.
  - `k_max=None` ⇒ uses `min(12, n_leiden_clusters)`.
  - `k_scores` has the same length as `k_candidates`.
  - Determinism: same input → same `SelectionResult`.

**Reviewer A2** audits A1's work:

- Reference fidelity to `reference/01_abm_generate_embedding.py` lines
  ~519-720 (note: the reference does **not** auto-select k — the user's
  new directive extends the reference; ensure the Leiden+Ward core
  still matches the reference exactly).
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
- Auto-selection correctness: WSS formula matches "sum of squared
  Euclidean distances from each point to its assigned final-cluster
  centroid"; kneed parameters appropriate; the fallback when kneed
  fails is sensible; CH and silhouette use sklearn correctly; degenerate
  cases (1-cluster cut) handled.
- House-style: pure functions, mypy strict, ruff clean.

### Pair B — Zarr orchestrator

**Implementer B1** writes:

- `src/tmelandscape/cluster/__init__.py` — `cluster_ensemble` per
  the contract. Mirror the Phase 3.5 / 4 orchestrator patterns:
  - Input via `xr.open_zarr` context manager.
  - Pre-existence guard on `output_zarr`.
  - Defence-in-depth: all six variable names must be distinct
    (Stream C's config validator catches this too; orchestrator
    repeats for safety).
  - Materialise `embedding` to numpy; call Stream A's algorithm
    (passing all auto-selection knobs through).
  - Build output Dataset with embedding + window_averages
    passed through, plus the five new arrays (note: cluster-count-scores
    variable is empty-length when user supplied k explicitly).
  - Provenance forwarding from input attrs.
  - Partial-output cleanup on `to_zarr` failure.
  - **Replace** the existing skeleton `__init__.py` (currently just a
    docstring) entirely. Keep the high-level module docstring up to
    date with the revised submodule layout
    (`leiden_ward.py`, `selection.py`, `alternatives.py`).
- `tests/unit/test_cluster_ensemble.py` — input immutability, output
  pre-existence guard, variable-collision guard, provenance .zattrs,
  per-window coord propagation, `window_averages` passthrough when
  present in input, missing `source_variable` raises clearly, and
  auto-selection vs user-supplied-k path both produce a valid output
  Zarr (verify `cluster_count_metric_used` attribute and the
  `cluster_count_scores` array shape).

**Reviewer B2** audits B1's work — mirror Phase 3.5 / 4 reviewer
checklists; pay special attention to the dim/coord wiring for the new
`cluster_count_candidate` dimension and the partial-output cleanup
path.

### Pair C — config + alternatives

**Implementer C1** writes:

- `src/tmelandscape/config/cluster.py` — `ClusterConfig` per the
  contract (including the new optional `n_final_clusters`, the
  auto-selection knobs, the 6-way variable-collision validator, and
  the range-consistency validator).
- `src/tmelandscape/cluster/alternatives.py` — `cluster_identity`
  (returns single-cluster labels, all zeros) as passthrough baseline
  / future-strategy anchor.
- `tests/unit/test_cluster_config.py` — optional `n_final_clusters`
  (default `None`), explicit-int still accepted (>= 2), literal
  validations on partition and metric, the 6-way variable-collision
  validator, the count-range validator, JSON round-trip,
  `extra="forbid"`.
- `tests/unit/test_cluster_alternatives.py` — `cluster_identity` shape
  and zero-fill.

**Reviewer C2** audits C1's work — mirror Phase 3.5 / 4 reviewer
checklists; verify that the auto-selection fields are documented in
field descriptions (so they show up in JSON-Schema for the MCP server).

## Cleanup (orchestrator, before Wave 1)

The pre-existing `src/tmelandscape/cluster/` skeleton uses a
`leiden.py` + `meta.py` + `labels.py` layout that does **not** match
the contract above. Delete those three files before Wave 1 kicks off
so that Stream A and B see a clean slate. Keep nothing but
`__init__.py` (which Stream B will rewrite) and `selection.py` (which
Stream A will rewrite). `labels.py` (human-readable state names) is
out of scope for v0.6.0 — defer to a later phase.

## Integration (orchestrator, after all three pairs return)

1. Apply review findings.
2. Write CLI: `src/tmelandscape/cli/cluster.py` (verb `tmelandscape
   cluster`). The CLI must expose the auto-selection knobs:
   `--cluster-count-metric`, `--cluster-count-min`,
   `--cluster-count-max`; `--n-final-clusters` defaults to `None`
   (auto-select).
3. Strategy-discovery CLI: `tmelandscape cluster-strategies list`.
4. MCP tools: `cluster_ensemble_tool` + `list_cluster_strategies_tool`.
   Register on the MCP server.
5. Integration test: `tests/integration/test_clustering_end_to_end.py` —
   Python API + CLI + MCP equivalence on a synthetic embedding Zarr.
   Cover both paths: explicit-k and auto-selected-k.
6. Docs: `docs/concepts/cluster.md` (already a placeholder; fill in
   with the algorithm description + Pydantic field table + worked
   example, including the auto-selection knobs).
7. Update STATUS.md + ROADMAP.md + CHANGELOG.md.
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
- 2026-05-13 (Claude Code orchestrator, revision): Project owner
  directed that `n_final_clusters` be optional with auto-selection
  via WSS elbow (default), Calinski-Harabasz, or silhouette. Contract
  revised: `n_final_clusters` is now `int | None` (no package default),
  three new config fields added (`cluster_count_metric`,
  `cluster_count_min`, `cluster_count_max`), and `selection.py` joins
  the Stream A module set. ADR 0010 captures the rationale.
  Dependency pins also bumped to tagged form
  (`tissue_simulator@v0.1.4`, `spatialtissuepy@v0.0.1`) per
  [ADR 0008](../docs/adr/0008-dependency-pin-policy.md). Tests still
  green (247 passed). Ready for Wave 1.
