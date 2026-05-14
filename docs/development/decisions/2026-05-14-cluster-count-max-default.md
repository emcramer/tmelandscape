# Decision: narrow `cluster_count_max` heuristic from `min(20, n_leiden)` to `min(12, n_leiden)`

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Eric

## Context

The v0.6.0 implementation of cluster-count auto-selection
([ADR 0010](../../adr/0010-cluster-count-auto-selection.md)) defaulted
the candidate-k range upper bound to `min(20, n_leiden_clusters)` when
the user left `cluster_count_max` unset. The bound of 20 was a guess at
"a reasonable cap that won't run forever on small ensembles" — not
biologically motivated.

At the v0.6.0 handoff (2026-05-14), the owner gave a concrete biological
rationale:

> The test range should be 2-12 clusters for the hierarchical
> clustering phase. Anything past 8-10 clusters becomes biologically
> less interpretable (too many states/attractors to consider and some
> may not be relevant).

## Options considered

### Option A — Leave the default at 20

- Pros: zero behaviour change; users with truly fine-grained ensembles
  still get to see candidates up to 20.
- Cons: defaults exist for a reason; "20" was an engineer's guess, not
  a domain choice; users who accept the default will see auto-picks in
  a range that includes biologically uninterpretable k's; conflicts
  with the owner's stated mental model.

### Option B — Narrow to `min(12, n_leiden_clusters)`

- Pros: matches the owner's domain knowledge of where TME-state
  interpretability flattens out; faster auto-selection on large
  ensembles (fewer candidate cuts to score); a user who genuinely wants
  k up to 20 can still set `cluster_count_max=20` explicitly.
- Cons: behaviour change for any caller who relied on the implicit
  upper bound of 20. (No such caller exists in the wild — v0.6.0
  shipped this morning.)

### Option C — Narrow further to `min(10, n_leiden_clusters)`

- Pros: even tighter alignment with the "8-10 biologically
  interpretable" zone.
- Cons: the owner's stated number was 12, and 12 gives a small buffer
  for cases where the chosen k lands at the upper bound but is still
  defensible (e.g. an ensemble with 11 well-separated states).

## Decision

**Option B — narrow to `min(12, n_leiden_clusters)`.** This matches the
owner's stated range exactly and keeps the explicit-override path
unchanged.

## Consequences

- **Code change in `src/tmelandscape/cluster/selection.py`:** the
  `_DEFAULT_K_MAX_CAP` constant (or equivalent) drops from 20 to 12.
- **Field description on `ClusterConfig.cluster_count_max`** updates
  to say "None ⇒ `min(12, n_leiden_clusters)`".
- **ADR 0010** updated to reflect the new default in its prose.
- **`docs/concepts/cluster.md`** updated.
- **`tasks/06-clustering-implementation.md`** updated for traceability.
- **Tests:** any test that probed the resolved upper bound of the
  candidate range gets the new constant (12, not 20). The integration
  test `test_auto_selection_writes_per_candidate_scores` doesn't pin
  the upper bound — it only checks `chosen >= 2 and chosen <=
  n_leiden_clusters`, which remains true. The unit test
  `test_kmax_none_uses_heuristic_cap` (or its equivalent) updates to
  expect 12.
- **Version bump:** v0.6.1 (patch). Pre-1.0 SemVer permits a default
  narrowing on a patch release because no caller of v0.6.0 has had time
  to depend on the old default.
- **Reversibility:** trivial — one-line constant change.

## References

- [ADR 0010 — Cluster-count auto-selection](../../adr/0010-cluster-count-auto-selection.md)
- [tasks/06-clustering-implementation.md](../../../tasks/06-clustering-implementation.md)
- Owner directive: 2026-05-14 transcript ("The test range should be
  2-12 clusters […]. Anything past 8-10 clusters becomes biologically
  less interpretable.")
