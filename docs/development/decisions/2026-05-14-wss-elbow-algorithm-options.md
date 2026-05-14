# Decision: WSS-elbow algorithm — options for replacing the marginal-decrease fallback

- **Date:** 2026-05-14 (UTC)
- **Status:** Proposed
- **Owner / decider:** Eric (decision pending)

## Context

The v0.6.0 cluster-count auto-selector
([ADR 0010](../../adr/0010-cluster-count-auto-selection.md)) uses
`kneed.KneeLocator(curve="convex", direction="decreasing")` on the WSS
curve to pick `k`. When kneed cannot detect a knee (e.g. a near-linear
or monotonically-flat curve), the algorithm falls back to "the k just
after the largest marginal decrease in WSS" — i.e. the larger-k side of
the steepest segment.

Reviewer A2 surfaced two related concerns about this design:

1. The fallback is **effectively neutralised** by a private `k=1` anchor
   inserted before the candidate range. The 1→2 transition is always
   the steepest in a convex decreasing curve, so `argmin(deltas) + 1`
   always returns `k_candidates[1] = k_min`. The fallback never gets to
   exercise its intended logic.
2. The `k=1` anchor itself could in principle bias kneed toward small
   k in pathological cases where the true elbow is at k≥4.

At the v0.6.0 handoff (2026-05-14), the owner asked:

> Is there an algorithm that we can implement for the elbow selection
> that will perform better than finding the largest marginal drop in
> the WSS? Perhaps a limit finding algorithm that treats the WSS curve
> as if it were approaching an asymptote on a finite-horizon?

This entry surveys the options and proposes a recommendation.

## Options considered

For each: a one-paragraph sketch, pros, cons, and an "implementation
cost" estimate. All options keep the existing `wss_elbow` metric label;
the difference is in the algorithm that maps the WSS-vs-k curve to a
chosen k.

### Option 0 — Keep kneed; just **fix** the marginal-decrease fallback

The simplest move: stop computing the fallback on the anchored array.
When kneed returns `None`, compute `argmin(np.diff(scores)) + 1` on the
**public** `k_candidates` / `scores` arrays (no `k=1` anchor in front).

- Pros: minimal change; behaviour matches the docstring; reviewer's
  observation directly addressed.
- Cons: fallback is still "largest single drop", which is
  noise-sensitive on real WSS curves with multiple comparable drops.
  It does not actually answer the owner's "better algorithm" question.
- Implementation cost: **< 1 hour**, ~10 LOC.

### Option 1 — Asymptote-fit (the owner's suggestion)

Treat the WSS curve as approaching an asymptote. Fit a parametric
model — most natural is exponential decay:

  WSS(k) ≈ A · exp(−B · (k − k_min)) + C

— via `scipy.optimize.curve_fit`. The asymptote is `C` (the noise
floor). Declare the elbow at the smallest `k` where the *remaining
distance to the asymptote* falls below a tolerance, e.g. `(WSS(k) − C)
/ (WSS(k_min) − C) < ε` (default ε = 0.1 means "we've covered 90% of
the achievable WSS reduction").

- Pros: matches the owner's mental model; well-defined on convex
  decreasing curves; the tolerance `ε` is interpretable in domain
  language ("90% of the reduction").
- Cons: the exponential-decay assumption can fail (real WSS curves may
  decay slower-than-exponential); the fit may not converge on
  short / noisy curves (the candidate range is `[2, 12]` for typical
  ensembles — only 11 points, with `scipy.optimize.curve_fit` requiring
  3-parameter inference); the choice of `ε` is arbitrary.
- Implementation cost: **half day**, ~80 LOC including unit tests
  for the fitting fallbacks (failed fit, monotonic-but-non-convex, etc.).

### Option 2 — L-method (Salvador & Chan 2004)

Fits **two** linear regressions to the WSS curve — one to the left
portion `[k_min, k]`, one to the right portion `[k, k_max]` — for each
candidate split point `k`, and picks the `k` that minimises total
residual sum of squares. This is a well-validated algorithm in the
clustering literature and is specifically designed for knee detection on
WSS-vs-k curves.

- Pros: no parametric model assumption (just piecewise linearity);
  robust to noise; well-cited in the clustering literature
  (e.g. used as a baseline in several knee-detection papers); cheap
  (O(n²) on the candidate count).
- Cons: requires at least 4 candidates (otherwise the two linear fits
  each have <2 points); a separate implementation rather than reusing a
  pip package; the chosen k is constrained to be strictly interior to
  the candidate range (excludes the endpoints, which is usually what
  you want but is worth noting).
- Implementation cost: **half day**, ~60 LOC including unit tests.

### Option 3 — Variance-explained threshold

Pick the smallest `k` at which `(1 − WSS(k) / WSS(k_min))` crosses a
threshold (e.g. 0.85 for "85% of the reduction"). Simpler than the
asymptote fit; doesn't require fitting a model.

- Pros: trivial to implement (5 lines); interpretable.
- Cons: threshold is a magic number with no domain justification at
  any specific value; sensitive to the choice of `k_min`.
- Implementation cost: **< 1 hour**, ~20 LOC.

### Option 4 — Replace kneed with a "second-derivative argmax"

Numerically estimate the second derivative of the WSS curve and pick
its argmax (most curvature ⇒ elbow). Conceptually clean but very
noise-sensitive on a small number of points.

- Pros: textbook-correct definition of "elbow".
- Cons: noise-amplifying (second derivative of an 11-point curve is
  basically guesswork); requires smoothing for robustness; gives up
  the well-tested kneed implementation.
- Implementation cost: **half day** including the smoothing strategy.

### Option 5 — Ship multiple algorithms; let the user pick

Expand the `cluster_count_metric` enum from
`{"wss_elbow", "calinski_harabasz", "silhouette"}` to additionally
include `"wss_asymptote_fit"`, `"wss_lmethod"`, `"wss_variance_explained"`.
`"wss_elbow"` continues to mean "kneed + fixed fallback".

- Pros: nothing to deprecate; multiple metrics for the user to
  triangulate; the existing `wss_elbow` behaviour stays for users who
  have already calibrated on it.
- Cons: surface area grows; each new metric needs documentation and
  tests; users have to read the docs to understand the differences.
- Implementation cost: depends on which combination ships;
  Option 1 + 2 added as new metrics would be **one to one-and-a-half days**.

## Recommendation

**Option 0 + Option 2 (L-method) added as a new metric, behind a new
`cluster_count_metric="wss_lmethod"` literal.** Concretely:

1. Fix the existing fallback per Option 0 (no behaviour change for
   well-behaved curves; addresses the reviewer's specific observation).
2. Add `"wss_lmethod"` as a new metric option. Keep `"wss_elbow"` as
   the default (kneed-based). Document both in
   `docs/concepts/cluster.md` so the user can compare on real data.

Why not Option 1 (asymptote fit) as the recommendation? Two reasons:

- The candidate range is small (`[2, 12]` ⇒ 11 points). Fitting a
  three-parameter exponential reliably on 11 points with non-trivial
  noise is fragile. The L-method's piecewise-linear assumption is
  weaker and easier to satisfy.
- Asymptote fitting introduces a magic `ε` ("close to asymptote means
  what?"). The L-method has no analogous knob.

That said, Option 1 is the owner's stated preference and is defensible
on its own terms; if the owner prefers that direction, the
implementation cost is comparable. Both could ship side by side
under Option 5.

## Consequences (if the recommendation is accepted)

- New module function `tmelandscape.cluster.selection._wss_lmethod_knee`
  (private) or extension of `select_n_clusters` to dispatch on a new
  metric literal.
- `cluster_count_metric` literal grows to include `"wss_lmethod"`.
- `ClusterConfig` gains the new literal option.
- ADR 0010 amended (not superseded) to record the additional metric.
- New unit tests in `tests/unit/test_cluster_selection.py`.
- Documentation updated in `docs/concepts/cluster.md`.
- This work targets v0.6.2 or v0.7.0 (not bundled with the v0.6.1
  housekeeping commit).

## References

- Eric, 2026-05-14 transcript ("Is there an algorithm […]").
- [ADR 0010 — Cluster-count auto-selection](../../adr/0010-cluster-count-auto-selection.md)
- Reviewer A2 finding RISK #1 on `selection.py:286-329` (see
  Phase 5 session log).
- Salvador, S. & Chan, P. "Determining the Number of Clusters/Segments
  in Hierarchical Clustering/Segmentation Algorithms." 2004.
- Satopaa, V. et al. "Finding a 'Kneedle' in a Haystack: Detecting
  Knee Points in System Behavior." 2011. (kneed's underlying paper.)

## Decision pending from owner

**Eric: pick one of the following before this gets implemented.**

- (a) Option 0 only — just fix the fallback; no new metric.
- (b) Option 0 + Option 2 (L-method) added as a new metric. *Recommended.*
- (c) Option 0 + Option 1 (asymptote fit) added as a new metric.
- (d) Option 0 + Options 1 *and* 2 added as new metrics.
- (e) Something else / defer further.
