# 0010 — Cluster-count auto-selection (no silent default for `n_final_clusters`)

- **Status:** Accepted (revised 2026-05-14: (a) default `k_max` cap narrowed from 20 to 12 — see [decision log](../development/decisions/2026-05-14-cluster-count-max-default.md); (b) Option-5 metric expansion adds three more metrics — see [decision log](../development/decisions/2026-05-14-wss-elbow-option-5-accepted.md))
- **Date:** 2026-05-13 (revised 2026-05-14)
- **Deciders:** Eric, Claude

## Context

[ADR 0007](0007-two-stage-leiden-ward-clustering.md) established the
two-stage Leiden + Ward clustering pipeline. The original Phase 5 task
file (`tasks/06-clustering-implementation.md`) froze the contract for
`ClusterConfig.n_final_clusters` as **a required user input with no
default** — Eric's binding directive was that the package must not bake
in the LCSS paper's "6 TME states" silently.

During Phase 5 kick-off (2026-05-13), Eric refined this directive:

> Do not assume a default value for the hierarchical clustering.
> Optimize based on a metric such as the elbow of the WSS, the
> Calinski-Harabasz score, the silhouette score, etc. Default to the
> elbow of the WSS — I think you can determine this by calculating
> the marginal decrease in WSS as you increment cluster number and
> then finding the point of diminishing margins.

The original "required, no default" framing satisfied the no-silent-bias
invariant but pushed an unanswerable question onto every user: *how do
I know how many TME states there are in my ensemble?* The refined
directive keeps the no-silent-bias property while giving users a
principled way to let the data answer.

## Decision

`ClusterConfig.n_final_clusters` becomes **`int | None`**, with **no
package default**. Semantics:

- If the user supplies an explicit integer (>= 2), the package cuts the
  Ward dendrogram at exactly that k.
- If the user leaves it `None`, the package **picks k automatically**
  by optimising `cluster_count_metric` over the range
  `[cluster_count_min, cluster_count_max]`.

**Six metrics are supported** as of v0.7.1, with **WSS elbow as the
default**. Four operate on the WSS-vs-k curve directly; two delegate
to sklearn:

1. **`wss_elbow`** *(default)*: cut the dendrogram at each candidate k,
   compute the within-cluster sum of squares (Σ over clusters of Σ ‖x − μ_c‖²),
   then find the elbow of the WSS vs. k curve via
   [`kneed.KneeLocator`](https://pypi.org/project/kneed/) with
   `curve="convex"`, `direction="decreasing"`. The algorithm
   internally evaluates an additional k=1 anchor so kneed sees the
   convex shape; the returned candidates / scores arrays expose only
   the user-requested range. If kneed cannot detect a knee, fall back
   to the k with the largest marginal-decrease slope in WSS. (The
   fallback's current behaviour under the k=1 anchor regime is
   documented as a known limitation; users who hit it can switch to
   one of the alternative WSS metrics below.)
2. **`wss_lmethod`** *(added v0.7.1)*: Salvador & Chan 2004 L-method —
   for each interior split-point k_c, fit two linear regressions
   (left + right segments of the WSS curve); pick the split minimising
   total residual SSE. Robust to noise; requires ≥ 4 candidate ks.
3. **`wss_asymptote_fit`** *(added v0.7.1)*: fit `WSS(k) = A·exp(−B·(k − k_min)) + C`
   via `scipy.optimize.curve_fit`; pick smallest k where the remaining
   distance to the fitted asymptote falls below 10% (default
   threshold). Falls back to `wss_variance_explained` at threshold 0.9
   on fit failure (rare on real Ward-WSS curves).
4. **`wss_variance_explained`** *(added v0.7.1)*: pick smallest k where
   `1 − WSS(k)/WSS(k_min)` reaches 0.85 (default threshold). Returns
   `k_max` if no k satisfies the threshold (asymptotic fallback).
5. **`calinski_harabasz`**: `sklearn.metrics.calinski_harabasz_score`,
   argmax over candidates.
6. **`silhouette`**: `sklearn.metrics.silhouette_score` (Euclidean),
   argmax over candidates. For large ensembles a subsample cap may be
   applied to keep this O(n).

The four WSS-based metrics share the WSS computation; they differ only
in how the chosen k is extracted from the WSS curve. The CH and
silhouette metrics compute their own per-window scores from the
candidate label assignments. See
[decision log: Option-5 acceptance](../development/decisions/2026-05-14-wss-elbow-option-5-accepted.md)
for the rationale and the per-metric algorithm details.

The candidate range defaults to `[2, min(12, n_leiden_clusters)]`. The
upper-bound cap of 12 (revised 2026-05-14, was 20) reflects the
biologically interpretable upper bound for TME states — anything past
~8-10 final states becomes hard to interpret, and 12 leaves a small
buffer above that range. Both bounds are user-overridable via
`cluster_count_min` and `cluster_count_max`. See
[decision log: cluster_count_max default](../development/decisions/2026-05-14-cluster-count-max-default.md).

The output Zarr stores per-candidate metric values in a new
`cluster_count_scores` variable, dimensioned by a new
`cluster_count_candidate` axis. Both arrays are empty (length 0) when
the user supplied k explicitly, so downstream consumers can tell the
two paths apart by inspection.

The provenance `.zattrs` records `cluster_count_metric_used`:
`"user_supplied"` when the user gave a value; otherwise the metric
name (`"wss_elbow"` etc.).

## Consequences

- **No silent science-shaping default.** The package never picks `k=6`
  on its own. When a user accepts the auto-selection default, the
  *method* is named (`wss_elbow`) but the *number* falls out of the
  data, not a literature convention.
- **Reproducibility is preserved.** Given fixed inputs and seeds,
  auto-selection is deterministic. The chosen `k`, the candidate range,
  and the per-k scores are all written into the output Zarr provenance,
  so a re-runner can audit exactly how the choice was made.
- **Three-surface obligation extends.** The new knobs
  (`cluster_count_metric`, `cluster_count_min`, `cluster_count_max`)
  must appear in:
  - `ClusterConfig` (Pydantic) — done as part of Phase 5.
  - `tmelandscape cluster` CLI as flags.
  - `cluster_ensemble_tool` MCP tool (auto-derived from Pydantic
    JSON-Schema, so the burden is just descriptive Field docs).
- **Light deviation from the reference.** The reference notebook
  (`reference/01_abm_generate_embedding.py`) does not auto-select k —
  the author hand-picked `k=6` based on the LCSS paper. The Leiden + Ward
  core is unchanged from the reference; the auto-selection layer sits
  on top.
- **Task file revision.** `tasks/06-clustering-implementation.md` is
  amended to reflect the new contract. The "Pair A" stream gains a
  second module (`selection.py`) and a second test file
  (`tests/unit/test_cluster_selection.py`).

## Alternatives considered

- **Keep `n_final_clusters` required, no default, no auto-pick.**
  Honest about the choice, but in practice users without LCSS-paper
  domain knowledge have no anchor. Rejected: the cost of a principled
  auto-default is small (a few hundred lines plus tests); the
  usability gain is large.
- **Auto-select silently when omitted, but with a hardcoded k=6
  fallback if the metric is inconclusive.** Slips a literature
  convention back in through the side door. Rejected on the binding
  invariant grounds that prompted ADR 0009.
- **Expose only the WSS elbow.** Simpler API. Rejected because Eric's
  directive explicitly named CH and silhouette as legitimate
  alternatives; downstream users with non-Gaussian cluster geometry
  may prefer silhouette.
- **Compute all three metrics every run, return all three, let the
  user pick post-hoc.** Triples the runtime of the most expensive
  pipeline step. Rejected; users can re-run with `cluster_count_metric`
  flipped if they want comparison.

## References

- [ADR 0007](0007-two-stage-leiden-ward-clustering.md) — the underlying
  two-stage Leiden + Ward decision.
- [ADR 0009](0009-no-hardcoded-statistics-panel.md) — the precedent
  for "no silent science-shaping default" applied to the statistics
  panel.
- `tasks/06-clustering-implementation.md` (repo root, not on the docs site) —
  the revised contract.
- [`kneed`](https://github.com/arvkevi/kneed) — elbow / knee detection
  library, already in core deps.
