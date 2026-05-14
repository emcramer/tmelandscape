# Decision: LCSS-3 vector field uses "both endpoints in state s" inclusion

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Implementer A1 + Reviewer A2 + Phase 6 orchestrator

## Context

LCSS Figure 3 overlays a state-coloured per-state vector field on the
UMAP scatter. The TNBC manuscript Methods section (lines 880-896)
describes the vector-field methodology but with prose that admits two
distinct interpretations of which window-to-window displacements count
"as state s":

- **"Both endpoints in state s"** (strict): include displacement
  `w_i → w_{i+1}` in the per-state quiver for `s` iff *both* `w_i` and
  `w_{i+1}` are currently assigned to state `s`. Each per-state quiver
  describes intra-state flow only.
- **"Originates in state s"** (loose): include the displacement iff
  `w_i` is in state `s` (irrespective of `w_{i+1}`'s state). Per-state
  quivers also describe the exit-trajectories from `s`.

The two semantics produce visibly different vector fields, especially
near state boundaries — the loose form has more displacements per
state, and they tend to fan outwards across the boundary.

The Methods prose ("displacement vectors were aggregated based on their
corresponding TME state assignment", singular "their state assignment")
is ambiguous between the two.

## Options considered

### Option A — Strict ("both endpoints in state s")

- Pros: conservative; the per-state quiver field describes only *within
  state s* dynamics — clean separation between flows; if a downstream
  consumer wants exit dynamics they can compose two states' fields
  themselves.
- Cons: drops the inter-state transition flows that may be the most
  informative part of the figure for tumour-state-transition biology.

### Option B — Loose ("originates in state s")

- Pros: captures exit-from-state-s trajectories; closer to typical
  Markov-chain-style flow visualisation.
- Cons: per-state quivers double-count the boundary region (s→t
  displacement appears in s's field but not in t's); harder to interpret
  at glance if every quiver "spills" across state boundaries.

## Decision

**Option A** (strict — "both endpoints in state s"). Rationale:

- A1 implemented it this way after independently weighting the
  ambiguity.
- The strict form has cleaner downstream semantics: each per-state
  quiver describes one population's intra-state behaviour with no
  cross-state contamination.
- If a future user (or the TNBC author) prefers the loose form, it is a
  ~5-line implementation change in `_per_state_displacements` — the
  inclusion predicate is the only thing that flips.
- Reviewer A2 read the Methods prose independently and concluded
  Option A is defensible.

## Consequences

- **No code change** needed beyond what A1 shipped.
- **Docstring**: `_per_state_displacements` (in `viz/embedding.py`)
  states the chosen semantics explicitly.
- **Reconciliation hook**: if Stream C's TNBC-6b (which has a similar
  vector-field over a different phase space) lands with the *loose*
  interpretation, the two functions should be reconciled before v0.7.0
  ships, with this decision-log entry updated to a "superseded by"
  status. (As of Wave-3 audit, Stream C also uses the strict
  interpretation — no reconciliation needed.)
- **Reversibility:** trivial — a one-line predicate flip switches
  Option A → Option B. The test
  (`test_vector_field_quiver_matches_mean_displacement`) would need to
  regenerate its expected quiver values.

## References

- Implementer A1 Wave-1 report (Phase 6 Stream A).
- Reviewer A2 Wave-2 findings (SMELL S3).
- TNBC manuscript Methods lines 880-896 (the ambiguous prose).
- `viz/embedding.py::_per_state_displacements` (the implementation
  citing this decision).
- Stream C's `viz/dynamics.py::_mean_displacement_grid` (uses the same
  strict interpretation — confirmed by reviewer C2).
