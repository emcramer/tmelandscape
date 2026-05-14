# Concept: clustering (step 5)

Step 5 reads the windowed-embedding Zarr from step 4 and assigns each
row (one window) to a discrete tumour-microenvironment (TME) state via a
two-stage Leiden + Ward pipeline. The output is a new Zarr that
carries the original `embedding` array through untouched, plus per-window
integer labels at both the Leiden (over-segmented) and the final
(Ward-merged) levels, plus the per-Leiden-cluster mean embedding vectors
and the Ward linkage matrix.

The algorithm matches `reference/01_abm_generate_embedding.py` lines
~519-720 exactly for the Leiden + Ward core; see
[ADR 0007](../adr/0007-two-stage-leiden-ward-clustering.md). The
cluster-count auto-selection layer is a tmelandscape addition on top of
the reference; see
[ADR 0010](../adr/0010-cluster-count-auto-selection.md).

## Inputs

- The windowed-embedding Zarr from `tmelandscape embed`. By default the
  algorithm reads the `embedding` variable; pass a different
  `source_variable` to cluster a different 2D array.
- A `ClusterConfig` (Pydantic) carrying the optional `n_final_clusters`
  and the auto-selection knobs.

## Algorithm — `leiden_ward` (default)

**Stage 1 — Leiden community detection on a kNN graph.**

1. Build a kNN graph over the `(n_window, n_feature)` embedding using
   `sklearn.neighbors.kneighbors_graph(metric='euclidean',
   mode='connectivity', include_self=False)`. The neighbour count
   defaults to `int(sqrt(n_window))` (the reference heuristic) when
   `knn_neighbors=None`.
2. Convert the sparse graph to igraph (undirected, unweighted; edge
   weights set to 1.0 to mirror the reference).
3. Run `leidenalg.find_partition` with the chosen partition class
   (`CPMVertexPartition` by default — matches the reference). Output:
   one integer Leiden community id per row.

**Stage 2 — Ward hierarchical clustering on Leiden cluster means.**

1. Compute the mean embedding vector for each Leiden community.
2. `pdist(means, metric='euclidean')` → `linkage(D, method='ward')`.
3. Cut the dendrogram at `n_final_clusters`:
   - **If the user supplied an integer**, cut directly:
     `fcluster(Z, t=n_final_clusters, criterion='maxclust')`.
   - **If `n_final_clusters is None`**, *auto-select* `k` over the
     candidate range `[cluster_count_min, cluster_count_max]`
     (default upper bound `min(12, n_leiden_clusters)`) using the
     chosen `cluster_count_metric`. Six metrics ship as of v0.7.1:
     - `wss_elbow` *(default)*: minimise within-cluster sum of squares,
       knee detected via [`kneed.KneeLocator`](https://github.com/arvkevi/kneed).
       Uses a private k=1 anchor to expose the convex shape; the public
       candidates / scores arrays reflect only the user range.
     - `wss_lmethod` *(added v0.7.1)*: Salvador & Chan 2004 L-method —
       two-linear-fit knee detection. Robust to noise; requires ≥ 4
       candidate ks.
     - `wss_asymptote_fit` *(added v0.7.1)*: exponential-decay fit
       `WSS(k) = A·exp(−B·(k − k_min)) + C`; pick smallest k whose
       remaining distance to the fitted asymptote ≤ 0.1 (i.e. 90% of
       the achievable reduction). Falls back to `wss_variance_explained`
       at threshold 0.9 on fit failure.
     - `wss_variance_explained` *(added v0.7.1)*: smallest k whose
       `1 − WSS(k)/WSS(k_min)` reaches 0.85.
     - `calinski_harabasz`: argmax of
       `sklearn.metrics.calinski_harabasz_score`.
     - `silhouette`: argmax of `sklearn.metrics.silhouette_score`
       (subsampled at 5000 rows for ensembles larger than that, with a
       fixed `random_state=42`).

   The four `wss_*` metrics share the WSS computation; they only
   differ in how the chosen k is extracted from the WSS curve. The
   per-candidate `cluster_count_scores` in the output Zarr is the WSS
   curve for all four (uniform across the family); for CH and
   silhouette it is the sklearn score. Decision log:
   `2026-05-14-wss-elbow-option-5-accepted.md`.
4. Broadcast the Leiden→final mapping back to per-window labels:
   `final_labels = leiden_to_final[leiden_labels]`. Final labels are
   1-based (`1..n_final_clusters_used`) per scipy's `fcluster`
   convention.

## Discovering available strategies

```bash
tmelandscape cluster-strategies list
```

```python
from tmelandscape.cli.cluster_strategies import _catalogue
print(_catalogue())
```

MCP agents call `list_cluster_strategies`.

## `ClusterConfig` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `strategy` | `Literal["leiden_ward"]` | `"leiden_ward"` | Algorithm to apply. |
| `knn_neighbors` | `int \| None (>=1)` | `None` | kNN graph degree. `None` ⇒ `int(sqrt(n_window))`. |
| `leiden_partition` | `Literal["CPM", "Modularity", "RBConfiguration"]` | `"CPM"` | leidenalg partition class. `CPM` matches the reference. |
| `leiden_resolution` | `float (>0)` | `1.0` | Leiden resolution parameter (ignored for `Modularity`, which doesn't take one). |
| `leiden_seed` | `int` | `42` | Determinism anchor for `leidenalg.find_partition`. |
| `n_final_clusters` | `int \| None (>=2)` | `None` | Number of TME states. `None` ⇒ auto-select via `cluster_count_metric`. **No package default — see [ADR 0010](../adr/0010-cluster-count-auto-selection.md).** |
| `cluster_count_metric` | `Literal["wss_elbow", "wss_lmethod", "wss_asymptote_fit", "wss_variance_explained", "calinski_harabasz", "silhouette"]` | `"wss_elbow"` | Auto-selection metric. Only used when `n_final_clusters is None`. Six options as of v0.7.1 — see the algorithm section above for descriptions. |
| `cluster_count_min` | `int (>=2)` | `2` | Inclusive lower bound on the candidate-k range. |
| `cluster_count_max` | `int \| None (>=2)` | `None` | Inclusive upper bound. `None` ⇒ `min(12, n_leiden_clusters)`. |
| `source_variable` | `str` | `"embedding"` | Input array name. |
| `leiden_labels_variable` | `str` | `"leiden_labels"` | Output Leiden-labels variable name. |
| `final_labels_variable` | `str` | `"cluster_labels"` | Output final-labels variable name. |
| `cluster_means_variable` | `str` | `"leiden_cluster_means"` | Output Leiden-cluster-means variable name. |
| `linkage_variable` | `str` | `"linkage_matrix"` | Output Ward-linkage variable name. |
| `cluster_count_scores_variable` | `str` | `"cluster_count_scores"` | Output per-candidate metric scores variable name. |

The six variable names must be pairwise distinct (validated at
construction).

## Code example

```python
from pathlib import Path
import xarray as xr

from tmelandscape.config.cluster import ClusterConfig
from tmelandscape.cluster import cluster_ensemble

# Explicit k.
cluster_ensemble(
    "ensemble_embedded.zarr",
    "ensemble_clustered_k6.zarr",
    config=ClusterConfig(n_final_clusters=6),
)

# Auto-select k via WSS elbow.
cluster_ensemble(
    "ensemble_embedded.zarr",
    "ensemble_clustered_auto.zarr",
    config=ClusterConfig(cluster_count_metric="wss_elbow"),
)

ds = xr.open_zarr("ensemble_clustered_auto.zarr")
labels = ds["cluster_labels"]            # (n_window,) int — 1..n_final_clusters_used
print("chosen k:", ds.attrs["n_final_clusters_used"])
print("metric:", ds.attrs["cluster_count_metric_used"])
print("per-candidate scores:", ds["cluster_count_scores"].values)
```

## CLI

```bash
# Discover available strategies
tmelandscape cluster-strategies list

# Run clustering with explicit k
tmelandscape cluster \
    ensemble_embedded.zarr \
    ensemble_clustered.zarr \
    --config cluster_config.json
```

A minimal `cluster_config.json` for auto-selection:

```json
{
  "cluster_count_metric": "wss_elbow"
}
```

A minimal `cluster_config.json` for explicit k:

```json
{
  "n_final_clusters": 6
}
```

The JSON summary printed to stdout includes the output path and the
applied config; structured logs go to stderr.

## The output Zarr

Dimensions:

- `window` (passed through from input) — one row per window.
- `embedding_feature` (passed through) — flattened-window axis.
- `statistic` (passed through, when the input has `window_averages`).
- `leiden_cluster` (new) — one entry per Leiden community.
- `linkage_step` (new) — `n_leiden_clusters - 1` rows of the Ward
  linkage matrix.
- `linkage_field` (new, length 4) — the
  `(idx_a, idx_b, distance, n_in_cluster)` fields of scipy's linkage.
- `cluster_count_candidate` (new) — the k's evaluated by auto-selection;
  length 0 when the user supplied `n_final_clusters` explicitly.

Data variables:

- `embedding` (passthrough), `window_averages` (passthrough when
  present).
- `leiden_labels` `(window,)` — integer Leiden community per window.
- `cluster_labels` `(window,)` — final TME-state label per window,
  1-based.
- `leiden_cluster_means` `(leiden_cluster, embedding_feature)` — mean
  embedding per Leiden community.
- `linkage_matrix` `(linkage_step, linkage_field)` — Ward linkage.
- `cluster_count_scores` `(cluster_count_candidate,)` — metric value at
  each candidate k; length 0 on the user-supplied-k path.

Per-window coordinates (`simulation_id`, `window_index_in_sim`,
`start_timepoint`, `end_timepoint`, `parameter_combination_id`, `ic_id`,
`parameter_<name>`) are forwarded from the input.

Provenance `.zattrs`:

- `cluster_config` (JSON), `n_leiden_clusters`, `knn_neighbors_used`,
  `n_final_clusters_used`, `cluster_count_metric_used`,
  `source_input_zarr`, `source_variable`, `created_at_utc`,
  `tmelandscape_version`.
- Forwarded if present in input: `source_embedding_config`,
  `source_normalize_config`, `source_manifest_hash`. The orchestrator
  also lifts a bare `embedding_config` attr from the input into the
  `source_embedding_config` slot on output, so fresh Phase 4 stores get
  a clean audit chain.

## What's *not* in step 5

- **Choosing the cluster-count metric automatically.** The package
  exposes six metrics (`wss_elbow`, `wss_lmethod`, `wss_asymptote_fit`,
  `wss_variance_explained`, `calinski_harabasz`, `silhouette`); the
  user picks. There is no "best metric" the package
  selects for you.
- **Human-readable state names.** The output is integer labels
  (`1..n_final_clusters_used`). Mapping those to interpretable TME-state
  names (Effector-Dominant, Exhausted-Dominant, etc.) is a downstream
  analysis decision and is deferred to a later module.
- **Stability analysis across seeds.** A single `leiden_seed` is used;
  repeated runs at different seeds (to assess label stability) are a
  user-driven workflow, not a built-in feature.
