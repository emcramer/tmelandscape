# Decision: viz.trajectories — ragged trajectories raise; `leiden_labels` optional; first-appearance sim ordering

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Implementer B1 + Reviewer B2 + Phase 6 orchestrator

## Context

Stream B (heatmaps + clustergrams) made three judgment calls during
implementation that the frozen contract permitted but did not pick. This
entry consolidates them so future readers have a single landing page.

## Decisions

### D1. Ragged trajectories raise, do not NaN-pad (`plot_trajectory_clustergram`)

The contract said "pick whichever is cleaner; document." B1 chose to
**raise** rather than NaN-pad. Rationale:

- `scipy.cluster.hierarchy.linkage(... metric="euclidean")` is ill-defined
  on NaN-bearing input vectors. NaN-padding would either require
  promoting to a masked-distance metric (extra plumbing) or silently
  drop sims (data loss).
- The data-correctness invariant (heatmap matches
  `cluster_labels.reshape(n_sim, n_window_per_sim)`) is easy to assert
  only on a rectangular matrix.
- A user with ragged trajectories has options: re-window upstream, drop
  short sims explicitly, or pad with a sentinel state of their own.

### D2. `leiden_labels` is optional (`plot_state_feature_clustermap`)

The contract listed `leiden_labels` among the required reads. B1 made
it optional with a graceful-degradation path: if absent, the row-colour
bar falls back to a single global modal-state colour (uniform bar). The
clustermap itself still renders correctly because it only needs
`leiden_cluster_means` and `linkage_matrix`.

Rationale: clusters produced by an old or hand-rolled pipeline may not
carry `leiden_labels`. The figure remains useful — just less
informative on the row-colour bar.

**Acknowledged limitation** (Reviewer B2): the uniform bar carries zero
per-row signal. A viewer might still mistake it for "every cluster has
the same modal state." Mitigation: the function emits a `warnings.warn`
when `leiden_labels` is absent so silent-degradation is observable
(deferred to v0.7.1 — non-blocking).

### D3. Sim-row ordering uses first-appearance, not sorted ids

In `plot_trajectory_clustergram`, sims are arranged on the y-axis in
their *first-appearance* order on the `window` axis (i.e. the order
`dict.fromkeys(simulation_id)` produces). This preserves the manifest
order that Phase 4 wrote when broadcasting per-sim coords. The audit
context suggested "sorted sim ids"; both are deterministic.

Rationale: preserving manifest order keeps adjacent sims (same
parameter combo, different ICs) next to each other in the heatmap —
which is biologically meaningful. Alphabetic sort would scatter ICs.

## Consequences

- **No code change** needed beyond what B1 shipped.
- **Test coverage**: B1's tests already exercise the ragged-raise path
  (`test_trajectory_clustergram_raises_on_ragged_trajectories`),
  optional-`leiden_labels` path (graceful degradation), and the
  first-appearance ordering (via deterministic fixture).
- **v0.7.1 follow-up**: add a `warnings.warn` to `_row_colors_from_modal_state`
  when `leiden_labels` is absent so the degradation is observable.
- **Reversibility:** each of the three decisions is locally
  reversible. D1 and D2 are predicate flips; D3 is a one-liner
  (`sorted(...)` vs `dict.fromkeys(...)`).

## References

- Implementer B1 Wave-1 report (Phase 6 Stream B).
- Reviewer B2 Wave-2 findings.
- [Phase 6 task file](../../../tasks/07-visualisation-implementation.md)
- `viz/trajectories.py` — implementation citing this decision.
