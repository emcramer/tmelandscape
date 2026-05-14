# Decision: accept Option 5 for WSS-elbow auto-selection — ship multiple metrics

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted (supersedes the Recommended item in
  [`2026-05-14-wss-elbow-algorithm-options.md`](./2026-05-14-wss-elbow-algorithm-options.md))
- **Owner / decider:** Eric

## Context

The [WSS-elbow algorithm-options entry](./2026-05-14-wss-elbow-algorithm-options.md)
proposed six choices for replacing the marginal-decrease fallback. Status was
*Proposed*; recommendation was Option 0 (fix fallback) + Option 2 (add L-method).

Eric's response, 2026-05-14 (third clarification of the session):

> Implement option 5 for the elbow picking algorithm. This follows the
> same design philosophy as allowing a user to pick which metric to use
> for choosing cluster number.

Option 5 is "ship multiple algorithms; let the user pick". This honours
the existing `cluster_count_metric` enum philosophy — name the algorithm,
let the data answer.

## Decision

Implement **Option 5**: extend `cluster_count_metric` from
`{"wss_elbow", "calinski_harabasz", "silhouette"}` to additionally
include:

- `"wss_lmethod"` — Salvador & Chan 2004 L-method (two-linear-fit
  knee detection on the WSS curve).
- `"wss_asymptote_fit"` — exponential decay fit `WSS(k) = A·exp(−B·(k−k_min)) + C`;
  pick smallest k where the remaining distance to the fitted asymptote
  is below a threshold (default 0.1 = "90% of the reduction achieved").
- `"wss_variance_explained"` — pick smallest k where
  `1 − WSS(k)/WSS(k_min)` crosses a threshold (default 0.85).

`"wss_elbow"` keeps its current behaviour (kneed + fixed fallback,
including the k=1 private anchor). Option 0 (fix the marginal-decrease
fallback) is **not** separately required — users who hit the kneed
fallback can switch to a different metric. The fallback's current
"collapses to `k_min`" behaviour is documented as a known limitation,
not a bug.

## Consequences

- **Code:** new metric branches in `tmelandscape.cluster.selection`.
  Each new metric is a small (≤30 LOC) function with sensible default
  parameters (the per-metric thresholds are not exposed as
  `ClusterConfig` knobs for the v0.7.1 ship; can be exposed later if
  needed).
- **Config:** `ClusterConfig.cluster_count_metric` literal grows from
  3 options to 6.
- **ADR 0010:** amended (not superseded) to record the additional
  metrics.
- **Tests:** the existing `test_cluster_selection.py` parametrize is
  extended; each new metric gets a recovery test on the 3-blob fixture
  and a basic shape/determinism check.
- **MCP / CLI:** no surface change — the metric name is a string passed
  through `ClusterConfig`; both surfaces already accept arbitrary
  config kwargs.
- **Docs:** `docs/concepts/cluster.md` documents all six metrics.
- **Reversibility:** trivial — each new metric is locally contained;
  removing one is a delete-three-functions diff.

## Design choices for the new metrics

### `wss_lmethod`

- Iterate split-point `k_c` over `[k_min+1, k_max-1]` (interior only;
  need ≥2 points on each side).
- For each split: fit two linear regressions (left + right); sum the
  residual SSE; pick the `k_c` minimising total SSE.
- Implementation lives in private helper `_lmethod_knee`.
- Requires `k_max - k_min ≥ 3` (4 candidate ks minimum). If the
  user-requested range is smaller, raise a clear `ValueError`.

### `wss_asymptote_fit`

- Fit `WSS(k) = A·exp(−B·(k − k_min)) + C` via `scipy.optimize.curve_fit`.
- Initial guess: `A = WSS(k_min) − WSS(k_max)`, `B = 1/(k_max − k_min)`,
  `C = WSS(k_max)`. Bounds: `A ≥ 0`, `B > 0`, `C ≥ 0`.
- Pick smallest k where `(WSS(k) − C) / (WSS(k_min) − C) ≤ ε`. Default
  `ε = 0.1` ("90% of reduction").
- If fit fails to converge (RuntimeError / OptimizeWarning), fall back
  to `wss_variance_explained` semantics with the same threshold (1 − ε).
- Implementation in private helper `_asymptote_fit_knee`.

### `wss_variance_explained`

- Compute `var_explained(k) = 1 − WSS(k) / WSS(k_min)`.
- Pick smallest k where `var_explained(k) ≥ threshold`. Default
  threshold `0.85`.
- If no k satisfies the threshold, pick `k_max` (asymptotic fallback).
- Implementation in private helper `_variance_explained_knee`.

## References

- Owner directive: 2026-05-14 transcript (the "Implement option 5"
  clarification).
- [WSS-elbow algorithm options](./2026-05-14-wss-elbow-algorithm-options.md)
- [ADR 0010 — Cluster-count auto-selection](../../adr/0010-cluster-count-auto-selection.md)
- Salvador, S. & Chan, P. "Determining the Number of Clusters/Segments
  in Hierarchical Clustering/Segmentation Algorithms." 2004.
